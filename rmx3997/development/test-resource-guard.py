"""Real child-process guard tests; telemetry is synthetic, allocation is tiny."""
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import resource_guard as guard

# All tempfile fixtures and subprocess caches use the caller's on-disk scratch.
assert os.environ['TMPDIR'].startswith('/home/build/.cache/codex-work/')

HEALTHY = {'MemAvailable': 25 * 1024 * 1024,
           'SwapTotal': 32 * 1024 * 1024, 'SwapFree': 32 * 1024 * 1024}


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'])
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def worker(self, command, telemetry, timeout=5):
        script = self.root / 'supervisor.py'
        script.write_text(
            'import json,sys,time\nfrom pathlib import Path\n'
            f'sys.path.insert(0, {str(ROOT)!r})\n'
            'from resource_guard import supervise\n'
            f'healthy={HEALTHY!r}\n' + telemetry + '\n'
            f'report=supervise({command!r}, telemetry=sample, timeout={timeout!r})\n'
            f'Path({str(self.root / "report.json")!r}).write_text(json.dumps(report))\n'
        )
        return [sys.executable, '-B', str(script)]

    def read_report(self):
        return json.loads((self.root / 'report.json').read_text())

    def run_worker(self, command, telemetry='def sample(): return healthy', timeout=5):
        subprocess.run(self.worker(command, telemetry, timeout), check=True, timeout=12)
        return self.read_report()

    def test_thresholds_and_swap_disabled(self):
        self.assertIsNone(guard.pressure(HEALTHY))
        for field, threshold in (('MemAvailable', guard.MIN_AVAILABLE_KIB),
                                  ('SwapFree', guard.MIN_SWAP_FREE_KIB)):
            self.assertIsNone(guard.pressure(dict(HEALTHY, **{field: threshold})))
            self.assertIsNotNone(guard.pressure(dict(HEALTHY, **{field: threshold - 1})))
        self.assertIsNone(guard.pressure(dict(HEALTHY, SwapTotal=0, SwapFree=0)))

    def test_early_exit_and_command_failure(self):
        for code in (0, 23):
            result = self.run_worker([sys.executable, '-c', f'raise SystemExit({code})'])
            self.assertEqual(result['returncode'], code)
            self.assertFalse(result['aborted'])
            self.assertEqual(result['unreaped_pids'], [])

    def test_fail_closed_before_launch(self):
        marker = self.root / 'must-not-exist'
        command = [sys.executable, '-c', f'open({str(marker)!r}, "w").close()']
        for sample in ('def sample(): raise ValueError("missing telemetry")',
                       'def sample(): return dict(healthy, MemAvailable=0)',
                       'def sample(): return dict(healthy, SwapFree=0)'):
            result = self.run_worker(command, sample)
            self.assertEqual(result['returncode'], 125)
            self.assertTrue(result['aborted'])
            self.assertFalse(marker.exists())

    def child_tree(self):
        script = self.root / 'tree.py'
        script.write_text(
            'import os,signal,time\nfrom pathlib import Path\n'
            'signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
            'child=os.fork()\n'
            'if child == 0: os.setsid()\n'
            f'Path({str(self.root)!r}, str(os.getpid())+".pid").write_text(str(os.getpid()))\n'
            'while True: time.sleep(0.01)\n'
        )
        return [sys.executable, '-B', str(script)]

    def assert_reaped(self, report):
        pids = list(self.root.glob('*.pid'))
        self.assertEqual(len(pids), 2)
        for path in pids:
            self.assertFalse(Path('/proc', path.read_text()).exists())
        self.assertEqual(report['unreaped_pids'], [])
        self.assertTrue(report['aborted'])

    def test_pressure_kills_and_reaps_escaping_descendants_preserves_other_process(self):
        other = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            sample = (f'def sample():\n'
                      f' if len(list(Path({str(self.root)!r}).glob("*.pid"))) == 2:\n'
                      '  return dict(healthy, MemAvailable=0)\n'
                      ' return healthy')
            result = self.run_worker(self.child_tree(), sample)
            self.assert_reaped(result)
            self.assertIn('MemAvailable', result['reason'])
            self.assertIsNone(other.poll())
        finally:
            other.terminate()
            other.wait(timeout=3)

    def test_timeout_kills_tree(self):
        result = self.run_worker(self.child_tree(), timeout=0.7)
        self.assert_reaped(result)
        self.assertEqual(result['reason'], 'timeout')

    def test_signal_cleanup(self):
        process = subprocess.Popen(self.worker(self.child_tree(), 'def sample(): return healthy'))
        try:
            deadline = time.monotonic() + 3
            while len(list(self.root.glob('*.pid'))) < 2 and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertEqual(len(list(self.root.glob('*.pid'))), 2)
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=8)
            result = self.read_report()
            self.assert_reaped(result)
            self.assertEqual(result['returncode'], 128 + signal.SIGTERM)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

    def test_telemetry_failure_after_launch_kills_tree(self):
        sample = (f'def sample():\n'
                  f' if len(list(Path({str(self.root)!r}).glob("*.pid"))) == 2:\n'
                  '  raise ValueError("telemetry lost")\n'
                  ' return healthy')
        result = self.run_worker(self.child_tree(), sample)
        self.assert_reaped(result)
        self.assertIn('telemetry failure', result['reason'])

    def test_leader_exit_with_live_descendants_aborts(self):
        for code in (0, 7):
            pidfile = self.root / ('orphan-' + str(code))
            command = [sys.executable, '-c',
                       'import os,time; child=os.fork(); '
                       f'open({str(pidfile)!r}, "w").write(str(child)) if child else None; '
                       f'os._exit({code}) if child else time.sleep(30)']
            result = self.run_worker(command)
            self.assertEqual(result['returncode'], 125)
            self.assertEqual(result['reason'], 'command exited with live descendants')
            self.assertEqual(result['unreaped_pids'], [])
            self.assertFalse(Path('/proc', pidfile.read_text()).exists())

    def test_cli_and_realme_launchers(self):
        report = self.root / 'cli.json'
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'resource_guard.py'),
                                 '--report', str(report), '--', sys.executable, '-c', 'pass'],
                                timeout=8, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(report.read_text())['aborted'])
        stage = self.root / 'stage'
        stage.mkdir()
        # build-stage changes to the real stage cwd; no kernel command is used.
        (stage / 'kernel/common').mkdir(parents=True)
        (stage / 'build-environment.json').write_text('{}')
        for launcher in ('run-target.py', 'build-stage.py'):
            for code in (0, 23):
                label = launcher + '-' + str(code)
                program = f'import sys; print("stdout marker"); print("stderr marker",file=sys.stderr); raise SystemExit({code})'
                command = [sys.executable, '-c', program]
                # run-target replaces the last two production targets.
                production = command + ['Image', 'modules'] if launcher == 'run-target.py' else command
                (stage / 'build-argv.json').write_text(json.dumps(production))
                result = subprocess.run([sys.executable, str(ROOT / launcher), str(stage), label],
                                        timeout=8, capture_output=True, text=True)
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                path = stage / (label + '.json' if launcher == 'run-target.py' else 'build-execution.json')
                record = json.loads(path.read_text())
                self.assertEqual(record['exit_code'], code)
                self.assertEqual(record['argv'], command)
                self.assertEqual(record['reason'], 'completed')
                self.assertEqual(record['forgejo_report']['returncode'], code)
                self.assertIsNone(record['forgejo_report']['reason'])
                self.assertFalse(record['aborted'])
                self.assertEqual(record['unreaped_pids'], [])
                self.assertEqual(record['min_available_kib'], 3*1024**2)
                self.assertEqual(record['min_swap_free_kib'], 4*1024**2)
                self.assertEqual(record['timeout_seconds'], 21600)
                self.assertEqual(record['poll_seconds'], 0.1)
                self.assertNotIn('log_limit_bytes', record)
                log = (stage / (label + '.log')).read_text()
                self.assertIn('stdout marker', log)
                self.assertIn('stderr marker', log)
        if os.environ.get('GUARD_TEST_EVIDENCE'):
            shutil.copytree(stage, Path(os.environ['GUARD_TEST_EVIDENCE']) / 'launcher-stage')
        # Existing logs remain protected by both launchers.
        result = subprocess.run([sys.executable, str(ROOT / 'run-target.py'), str(stage),
                                 'run-target.py-0'], capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
