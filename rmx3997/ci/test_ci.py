#!/usr/bin/env python3
"""Offline unit tests for rmx3997/ci/rmx_ci.py and upstream.py.

Run: python3 -I rmx3997/ci/test_ci.py (temporary files go to $TMPDIR)
No network, no host inputs: every HTTP call is stubbed.
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

CI = Path(__file__).resolve().parent


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, CI / file)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


rmx_ci = load('rmx_ci', 'rmx_ci.py')
upstream = load('upstream', 'upstream.py')


class ReportIssueLookup(unittest.TestCase):
    """The tracking issue must be found even when it is not on the first page."""

    def run_report(self, pages):
        calls = []

        def api(method, url, token, data=None):
            calls.append((method, url))
            if method == 'GET':
                page = int(url.rsplit('page=', 1)[1]) if 'page=' in url else 1
                return 200, pages[page - 1] if page <= len(pages) else []
            return 201, {}

        with tempfile.TemporaryDirectory() as d:
            stage = Path(d)
            (stage / 'check.json').write_text(json.dumps(
                [{'name': 'x', 'pin': 'a' * 40, 'tip': 'a' * 40, 'new': False}]))
            args = mock.Mock(stage=str(stage), api='https://forge.example/api/v1',
                             repo='owner/repo', repo_url='https://forge.example/owner/repo.git',
                             run_url='https://forge.example/run/1')
            with mock.patch.object(upstream, 'api', api), \
                    mock.patch.dict('os.environ', {'TOKEN': 't'}), \
                    mock.patch('builtins.print'):
                try:
                    upstream.cmd_report(args)
                except SystemExit:
                    pass
        return [c for c in calls if c[0] == 'POST']

    def test_issue_on_second_page_gets_a_comment(self):
        first = [{'number': n, 'title': 'other %d' % n} for n in range(1, 51)]
        second = [{'number': 77, 'title': upstream.ISSUE_TITLE}]
        posts = self.run_report([first, second])
        self.assertEqual(posts, [('POST', 'https://forge.example/api/v1/repos/owner/repo/issues/77/comments')])

    def test_no_issue_creates_one(self):
        posts = self.run_report([[{'number': 1, 'title': 'other'}]])
        self.assertEqual(posts, [('POST', 'https://forge.example/api/v1/repos/owner/repo/issues')])


class AvbInfoFields(unittest.TestCase):
    """Missing avbtool fields fail with a FAIL line, not an AttributeError."""

    def test_missing_field_dies_cleanly(self):
        with mock.patch('builtins.print') as p, self.assertRaises(SystemExit) as e:
            rmx_ci.avb_field(r'Salt:\s+([0-9a-f]+)', 'Algorithm: NONE\n', 'salt')
        self.assertEqual(e.exception.code, 1)
        self.assertIn('salt', p.call_args[0][0])

    def test_present_field(self):
        self.assertEqual(rmx_ci.avb_field(r'Salt:\s+([0-9a-f]+)', '    Salt: abc1\n', 'salt'), 'abc1')


class BuildSummary(unittest.TestCase):
    """build.sh keeps the build exit code and log tail when no execution record exists."""

    def test_missing_execution_record(self):
        text = (CI / 'build.sh').read_text()
        start = text.index('# --- build summary')
        end = text.index('# --- end build summary')
        snippet = text[start:end]
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'build.log').write_text('compiler said no\n')
            script = 'set -Eeuo pipefail\nSTAGE=%s\nSRC=/nonexistent\nrc=7\n%s' % (d, snippet)
            r = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
        self.assertEqual(r.returncode, 7, r.stdout + r.stderr)
        self.assertIn('no execution record', r.stdout)
        self.assertIn('compiler said no', r.stdout)


class MakefileVersion(unittest.TestCase):
    def test_fields(self):
        mk = 'VERSION = 5\nPATCHLEVEL = 15\nSUBLEVEL = 199\nEXTRAVERSION =\n'
        self.assertEqual([upstream.makefile_field(mk, k) for k in ('VERSION', 'PATCHLEVEL', 'SUBLEVEL')],
                         ['5', '15', '199'])

    def test_missing_field_dies_cleanly(self):
        with mock.patch('builtins.print'), self.assertRaises(SystemExit) as e:
            upstream.makefile_field('VERSION = 5\n', 'SUBLEVEL')
        self.assertEqual(e.exception.code, 1)


class AtomicWrite(unittest.TestCase):
    """Tracked-file rewrites (record-pins, layout --approve, refresh-config)."""

    def test_replaces_and_keeps_mode(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, 'f.json')
            p.write_text('old\n')
            p.chmod(0o644)
            rmx_ci.write_atomic(p, 'new\n')
            self.assertEqual(p.read_text(), 'new\n')
            self.assertEqual(p.stat().st_mode & 0o777, 0o644)
            self.assertEqual(sorted(x.name for x in Path(d).iterdir()), ['f.json'])

    def test_failed_write_keeps_old_file_and_no_temp(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, 'f.json')
            p.write_text('old\n')
            with mock.patch.object(rmx_ci.os, 'replace', side_effect=OSError('disk full')), \
                    self.assertRaises(OSError):
                rmx_ci.write_atomic(p, 'new\n')
            self.assertEqual(p.read_text(), 'old\n')
            self.assertEqual(sorted(x.name for x in Path(d).iterdir()), ['f.json'])

    def test_refresh_config_uses_it(self):
        src = (CI / 'rmx_ci.py').read_text()
        body = src[src.index('def cmd_refresh_config'):src.index('# --------------------------------------------------------------- boot image')]
        self.assertIn('write_atomic(path,', body)
        self.assertNotIn('.write_text(', body)


if __name__ == '__main__':
    unittest.main()
