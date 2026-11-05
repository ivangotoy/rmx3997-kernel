#!/usr/bin/python3
"""Legacy Realme log/result CLI over the unmodified Forgejo supervisor.

forgejo_report contains the exact supervisor report. Legacy aliases retain
argv/exit_code and reason='completed' only for a non-aborted child exit.
Logs contain merged child stdout/stderr, without the retired 64 MiB cap.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

# Resolve alongside this adapter, including when invoked from another cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import resource_guard


def guarded(argv, log, result):
    cwd = os.getcwd()
    # Redirect descriptors in this dedicated supervisor process: no collector
    # child can be mistaken for a descendant of the supervised command.
    with open(log, 'xb', buffering=0) as stream:
        saved = [os.dup(fd) for fd in (1, 2)]
        try:
            sys.stdout.flush()
            sys.stderr.flush()
            for fd in (1, 2):
                os.dup2(stream.fileno(), fd)
            report = resource_guard.supervise(argv)
        finally:
            for fd, original in zip((1, 2), saved):
                os.dup2(original, fd)
                os.close(original)
    record = dict(report)
    record.update(adapter_schema_version=1, forgejo_report=report,
                  guard_sha256=hashlib.sha256(Path(resource_guard.__file__).read_bytes()).hexdigest(),
                  argv=argv, cwd=cwd, exit_code=report['returncode'],
                  reason=report['reason'] if report['aborted'] else 'completed',
                  memory_floor_bytes=report['min_available_kib'] * 1024,
                  minimum_actual_MemAvailable_bytes=(report['minimum_available_kib'] * 1024
                      if report['minimum_available_kib'] is not None else None),
                  poll_seconds=resource_guard.POLL_SECONDS,
                  test_only_injected_pressure=False)
    Path(result).write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print('Resource guard: ' + (report['reason'] or 'command completed'), flush=True)
    return report['returncode']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log', required=True)
    parser.add_argument('--result', required=True)
    parser.add_argument('argv', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    argv = args.argv[1:] if args.argv[:1] == ['--'] else args.argv
    if not argv:
        parser.error('a foreground command is required')
    raise SystemExit(guarded(argv, args.log, args.result))


if __name__ == '__main__':
    main()
