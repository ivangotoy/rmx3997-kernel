#!/usr/bin/env python3
"""Foreground Linux build supervisor; abort before memory/swap exhaustion.

Only descendants of the supervised command are signalled. Subreaping retains
ownership when a compiler's parent exits. Bazel callers must use --batch so
the command cannot delegate compilation to an existing shared server.
"""
import argparse
import ctypes
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time

MIN_AVAILABLE_KIB = 3 * 1024 * 1024
MIN_SWAP_FREE_KIB = 4 * 1024 * 1024
POLL_SECONDS = 0.1
TERM_SECONDS = 2.0
KILL_SECONDS = 3.0


def memory():
    fields = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, _, value = line.partition(':')
        if key in ('MemAvailable', 'SwapTotal', 'SwapFree'):
            parts = value.split()
            if len(parts) != 2 or parts[1] != 'kB' or not parts[0].isdigit():
                raise ValueError('invalid memory telemetry: ' + key)
            fields[key] = int(parts[0])
    if set(fields) != {'MemAvailable', 'SwapTotal', 'SwapFree'}:
        raise ValueError('missing memory telemetry')
    if fields['SwapFree'] > fields['SwapTotal']:
        raise ValueError('inconsistent swap telemetry')
    return fields


def pressure(sample):
    if sample['MemAvailable'] < MIN_AVAILABLE_KIB:
        return 'MemAvailable below 3 GiB'
    if sample['SwapTotal'] and sample['SwapFree'] < MIN_SWAP_FREE_KIB:
        return 'SwapFree below 4 GiB'
    return None


def processes():
    result = {}
    for path in Path('/proc').glob('[0-9]*/stat'):
        try:
            # comm may contain spaces and parentheses; fields after its last
            # closing parenthesis start with state, ppid, pgrp, session.
            tail = path.read_text().rsplit(')', 1)[1].split()
            result[int(path.parent.name)] = (int(tail[1]), int(tail[19]))
        except (FileNotFoundError, ProcessLookupError):
            continue
    return result


def descendants(table, parent):
    owned = set()
    frontier = {parent}
    while frontier:
        frontier = {pid for pid, (ppid, _) in table.items()
                    if ppid in frontier and pid not in owned}
        owned.update(frontier)
    return {pid: table[pid][1] for pid in owned}


def signal_owned(owned, sig):
    table = processes()
    for pid, start in owned.items():
        if pid in table and table[pid][1] == start:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass


def reap(owned, command):
    command.poll()
    for pid in owned:
        if pid == command.pid:
            continue
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass


def supervise(command, *, timeout=21600, telemetry=memory):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('timeout must be positive')
    if descendants(processes(), os.getpid()):
        raise ValueError('guard requires a dedicated process without existing children')
    # PR_SET_CHILD_SUBREAPER: orphaned descendants are adopted by this guard,
    # not the runner. Fail closed if the kernel cannot provide that ownership.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), 'cannot enable child subreaper')
    stopped = []
    previous = {}
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        previous[sig] = signal.signal(sig, lambda number, frame: stopped.append(number))
    child = None
    report = {'schema_version': 1, 'command': command, 'aborted': False,
              'minimum_available_kib': None, 'minimum_swap_free_kib': None,
              'min_available_kib': MIN_AVAILABLE_KIB,
              'min_swap_free_kib': MIN_SWAP_FREE_KIB, 'timeout_seconds': timeout}
    reason = None
    start = time.monotonic()
    owned = {}
    try:
        while True:
            try:
                sample = telemetry()
                reason = pressure(sample)
                for field, key in (('MemAvailable', 'minimum_available_kib'),
                                   ('SwapFree', 'minimum_swap_free_kib')):
                    old = report[key]
                    report[key] = sample[field] if old is None else min(old, sample[field])
            except Exception as error:
                reason = 'telemetry failure: ' + str(error)
            if stopped:
                reason = 'signal ' + str(stopped[0])
            elif time.monotonic() - start >= timeout:
                reason = 'timeout'
            if reason:
                break
            if child is None:
                child = subprocess.Popen(command, start_new_session=True)
            owned = descendants(processes(), os.getpid())
            reap(owned, child)
            if child.returncode is not None:
                owned = descendants(processes(), os.getpid())
                if owned:
                    reason = 'command exited with live descendants'
                break
            time.sleep(POLL_SECONDS)
    except Exception as error:
        reason = 'supervisor failure: ' + str(error)
    finally:
        if child is not None:
            # Re-scan during shutdown: adopted grandchildren and children born
            # during TERM handling remain ours, even if they call setsid().
            deadline = time.monotonic() + TERM_SECONDS + KILL_SECONDS
            escalation = deadline - KILL_SECONDS
            while True:
                owned = descendants(processes(), os.getpid())
                reap(owned, child)
                owned = descendants(processes(), os.getpid())
                if not owned:
                    break
                signal_owned(owned, signal.SIGKILL if time.monotonic() >= escalation else signal.SIGTERM)
                if time.monotonic() >= deadline:
                    reason = 'owned processes did not terminate within cleanup deadline'
                    break
                time.sleep(POLL_SECONDS)
            report['unreaped_pids'] = sorted(owned)
            child.poll()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    report['aborted'] = reason is not None
    report['reason'] = reason
    report['elapsed_seconds'] = round(time.monotonic() - start, 3)
    report['returncode'] = (128 + stopped[0] if stopped else 125) if reason else child.returncode
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=float, default=21600)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('a foreground command is required')
    report = supervise(command, timeout=args.timeout)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print('Resource guard: ' + (report['reason'] or 'command completed'), flush=True)
    raise SystemExit(report['returncode'])


if __name__ == '__main__':
    main()
