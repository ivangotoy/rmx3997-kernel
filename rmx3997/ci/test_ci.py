#!/usr/bin/env python3
"""Offline unit tests for rmx3997/ci/rmx_ci.py and upstream.py.

Run: python3 -I rmx3997/ci/test_ci.py (temporary files go to $TMPDIR)
No network, no host inputs: every HTTP call is stubbed.
"""
import http.client
import importlib.util
import io
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest import mock
import zipfile

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


class GitTokenNotInArgv(unittest.TestCase):
    """The job token reaches git through its environment, never its argv."""

    def test_remote_refs_keeps_token_out_of_argv(self):
        calls = []

        def run(argv, **kw):
            calls.append((argv, kw['env']))
            return subprocess.CompletedProcess(argv, 0, 'a' * 40 + '\trefs/heads/main\n', '')

        with mock.patch.object(upstream.subprocess, 'run', run):
            upstream.remote_refs('https://forge.example/o/r.git', 'made-up-token', 'refs/heads/main')
        argv, env = calls[0]
        secret = upstream.base64.b64encode(b'x-access-token:made-up-token').decode()
        self.assertFalse([x for x in argv if 'made-up-token' in x or secret in x], argv)
        self.assertEqual(env.get('GIT_CONFIG_VALUE_0'), 'Authorization: basic ' + secret)
        self.assertNotIn('GIT_CONFIG_VALUE_0', upstream.GIT_ENV)


class GitNetworkTimeout(unittest.TestCase):
    """A hanging network git call fails on its own deadline, not the job timeout."""

    def run_with_hanging_git(self, fn):
        with tempfile.TemporaryDirectory() as d:
            stub = Path(d, 'git')
            stub.write_text('#!/bin/sh\nexec sleep 30\n')
            stub.chmod(0o755)
            env = dict(upstream.GIT_ENV, PATH=d + ':/usr/bin:/bin')
            with mock.patch.object(upstream, 'GIT_ENV', env), \
                    mock.patch.object(upstream, 'GIT_LS_REMOTE_TIMEOUT', 1, create=True), \
                    mock.patch.object(upstream, 'TRIES', 2), \
                    mock.patch.object(upstream.time, 'sleep'), \
                    mock.patch('builtins.print') as p:
                start = upstream.time.monotonic()
                with self.assertRaises(SystemExit) as e:
                    fn()
                took = upstream.time.monotonic() - start
        self.assertEqual(e.exception.code, 1)
        self.assertLess(took, 15)
        return ' '.join(str(c[0][0]) for c in p.call_args_list)

    def test_ls_remote_times_out(self):
        text = self.run_with_hanging_git(lambda: upstream.remote_head('https://forge.example/o/r.git', 'main'))
        self.assertIn('timed out after 1 s', text)

    def test_retried_ls_remote_times_out(self):
        text = self.run_with_hanging_git(
            lambda: upstream.remote_refs('https://forge.example/o/r.git', 'made-up-token', 'refs/heads/main'))
        self.assertIn('attempt 2 failed: timed out after 1 s', text)
        self.assertNotIn('made-up-token', text)


class GitTimeoutEndsHelpers(unittest.TestCase):
    """A timed-out git call also ends the processes git started (its remote
    helper), not only git itself."""

    def test_child_of_timed_out_git_is_killed(self):
        with tempfile.TemporaryDirectory() as d:
            pidfile = Path(d, 'child.pid')
            stub = Path(d, 'git')
            stub.write_text('#!/bin/sh\nsleep 60 &\necho $! > "$CHILD_PIDFILE"\nexec sleep 30\n')
            stub.chmod(0o755)
            env = dict(upstream.GIT_ENV, PATH=d + ':/usr/bin:/bin', CHILD_PIDFILE=str(pidfile))
            with mock.patch.object(upstream, 'GIT_ENV', env):
                r = upstream.git('ls-remote', 'https://forge.example.invalid/o/r.git', check=False, timeout=1)
            self.assertEqual(r.returncode, 124)
            child = int(pidfile.read_text())
            def state():
                try:
                    return Path('/proc/%d/stat' % child).read_text().rsplit(')', 1)[1].split()[0]
                except OSError:
                    return None

            try:
                for _ in range(50):
                    if state() in (None, 'Z'):
                        break
                    upstream.time.sleep(0.1)
                else:
                    self.fail('child of the timed-out git is still running')
            finally:
                try:
                    os.kill(child, 9)
                except OSError:
                    pass


class Reply:
    """What a stubbed urlopen returns: status and body, or read() raising."""

    def __init__(self, status=200, body=b'', exc=None):
        self.status, self.body, self.exc = status, body, exc

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        if self.exc:
            raise self.exc
        return self.body


def http_error(url, code):
    return urllib.error.HTTPError(url, code, 'x', {}, io.BytesIO(b''))


class OpenUrlRetry(unittest.TestCase):
    """GETs survive transient network errors; other methods fail cleanly."""

    def run_open_url(self, method, answers):
        seen = []

        def urlopen(req, timeout):
            seen.append(req.get_method())
            a = answers.pop(0)
            if isinstance(a, BaseException):
                raise a
            return a

        req = urllib.request.Request('https://forge.example/api/v1/x?token=made-up', method=method)
        with mock.patch.object(rmx_ci.urllib.request, 'urlopen', urlopen), \
                mock.patch.object(rmx_ci.time, 'sleep'), mock.patch('builtins.print') as p:
            try:
                res = rmx_ci.open_url(req)
            except SystemExit as e:
                res = ('exit', e.code)
        text = ' '.join(str(c[0][0]) for c in p.call_args_list)
        self.assertNotIn('made-up', text)
        return res, len(seen), text

    def test_get_retries_connection_errors_and_timeouts(self):
        res, n, _ = self.run_open_url('GET', [
            urllib.error.URLError(ConnectionRefusedError('refused')),
            Reply(exc=TimeoutError('read timed out')),
            Reply(exc=http.client.IncompleteRead(b'')),
            http_error('u', 503),
            Reply(200, b'ok')])
        self.assertEqual((res, n), ((200, b'ok'), 5))

    def test_get_gives_up_after_bounded_tries(self):
        res, n, text = self.run_open_url('GET', [urllib.error.URLError('down')] * rmx_ci.TRIES)
        self.assertEqual((res, n), (('exit', 1), rmx_ci.TRIES))
        self.assertIn('FAIL: GET https://forge.example/api/v1/x failed: down', text)

    def test_post_is_not_repeated_after_a_network_error(self):
        res, n, text = self.run_open_url('POST', [urllib.error.URLError('reset')])
        self.assertEqual((res, n), (('exit', 1), 1))
        self.assertIn('FAIL: POST https://forge.example/api/v1/x failed: reset', text)

    def test_post_returns_a_5xx_without_repeating(self):
        res, n, _ = self.run_open_url('POST', [http_error('u', 502)])
        self.assertEqual((res, n), ((502, b''), 1))

    def test_post_repeats_429(self):
        res, n, _ = self.run_open_url('POST', [http_error('u', 429), Reply(201, b'{}')])
        self.assertEqual((res, n), ((201, b'{}'), 2))


class GitHubCallsRetry(unittest.TestCase):
    """GitHub API calls and anonymous downloads use the same retry policy."""

    def call(self, fn, answers):
        seen = []

        def urlopen(req, timeout):
            seen.append(req.get_method())
            a = answers.pop(0)
            if isinstance(a, BaseException):
                raise a
            return a

        with mock.patch.object(rmx_ci.urllib.request, 'urlopen', urlopen), \
                mock.patch.object(rmx_ci.time, 'sleep'), mock.patch('builtins.print'):
            return fn(), len(seen)

    def test_gh_get_survives_a_reset_and_429(self):
        res = self.call(lambda: rmx_ci.gh('GET', 'https://api.github.example/r', 'made-up'),
                        [urllib.error.URLError(ConnectionResetError('reset')),
                         http_error('u', 429), Reply(200, b'[]')])
        self.assertEqual(res, ((200, b'[]'), 3))

    def test_fetch_survives_a_timeout(self):
        res = self.call(lambda: rmx_ci.fetch('https://forge.example/f.zip'),
                        [Reply(exc=TimeoutError('timed out')), Reply(200, b'zip')])
        self.assertEqual(res, ((200, b'zip'), 2))


class FakeForgejo:
    """Forgejo release API and download route for cmd_release, in memory."""
    API = 'https://forge.example/api/v1'
    BASE = API + '/repos/o/r'

    def __init__(self, existing=None, fail=None):
        self.existing, self.fail = existing, fail
        self.requests, self.assets, self.draft = [], {}, None

    def urlopen(self, req, timeout):
        m, url = req.get_method(), req.full_url
        self.requests.append((m, url, req.has_header('Authorization')))
        if self.fail and self.fail(m, url):
            raise http_error(url, 500)
        js = lambda x, st=200: Reply(st, json.dumps(x).encode())
        if m == 'GET' and url == self.BASE + '/releases/tags/rmx3997-v99':
            if self.existing is None:
                raise http_error(url, 404)
            return js(self.existing)
        if m == 'POST' and url == self.BASE + '/releases':
            self.draft = True
            return js({'id': 5}, 201)
        if m == 'POST' and url.startswith(self.BASE + '/releases/5/assets?name='):
            name = url.rsplit('=', 1)[1]
            self.assets[name] = req.data
            return js({'id': len(self.assets), 'name': name}, 201)
        if m == 'GET' and url.startswith(self.BASE + '/releases/5/assets/'):
            n = int(url.rsplit('/', 1)[1])
            return js({'size': len(list(self.assets.values())[n - 1])})
        if m == 'GET' and url == self.BASE + '/releases/5/assets':
            return js([{'name': n} for n in self.assets])
        if m == 'PATCH' and url == self.BASE + '/releases/5':
            self.draft = False
            return js({'draft': False})
        if m == 'GET' and url.startswith('https://forge.example/o/r/releases/download/rmx3997-v99/'):
            return Reply(200, self.assets[url.rsplit('/', 1)[1]])
        raise AssertionError('unexpected request %s %s' % (m, url))


def run_release(server):
    """cmd_release against FakeForgejo; returns (exit code or None, printed text)."""
    with tempfile.TemporaryDirectory() as d:
        stage = Path(d)
        dist = stage / 'dist'
        dist.mkdir()
        (dist / 'RMX3997-kernel-5.15.0-v99.zip').write_bytes(b'made-up zip')
        (dist / 'RMX3997-kernel-5.15.0-v99.zip.sha256').write_text('00  x\n')
        (stage / 'acceptance.json').write_text(json.dumps({'identity': {'release': '5.15.0-made-up'}}))
        a = mock.Mock(api=FakeForgejo.API, repo='o/r', tag='rmx3997-v99', commit='c' * 40,
                      dist=str(dist), run_url='https://forge.example/run/1')
        with mock.patch.object(rmx_ci.urllib.request, 'urlopen', server.urlopen), \
                mock.patch.object(rmx_ci.time, 'sleep'), \
                mock.patch.dict('os.environ', {'RELEASE_TOKEN': 'made-up-token'}), \
                mock.patch('builtins.print') as p:
            try:
                rmx_ci.cmd_release(a)
                code = None
            except SystemExit as e:
                code = e.code
    return code, '\n'.join(str(c[0][0]) for c in p.call_args_list)


class ReleaseDownloadIsAnonymous(unittest.TestCase):
    """The job token goes to the API only, never to the download route."""

    def test_round_trip_without_token(self):
        server = FakeForgejo()
        code, text = run_release(server)
        self.assertIsNone(code, text)
        downloads = [r for r in server.requests if '/releases/download/' in r[1]]
        self.assertEqual(len(downloads), 2)
        self.assertFalse([r for r in downloads if r[2]], downloads)
        self.assertTrue(all(r[2] for r in server.requests if r[1].startswith(FakeForgejo.API)))


class ReleaseLeftoverMessages(unittest.TestCase):
    """A failed release run says what it left on the server; it never deletes."""

    def check(self, server, want):
        code, text = run_release(server)
        self.assertEqual(code, 1, text)
        self.assertIn(want, text)
        self.assertFalse([r for r in server.requests if r[0] == 'DELETE'])
        return text

    def test_draft_found_on_rerun(self):
        self.check(FakeForgejo(existing={'id': 4, 'draft': True, 'tag_name': 'rmx3997-v99'}),
                   'unpublished draft release for rmx3997-v99 (id 4) exists')

    def test_failure_after_draft_creation_names_the_draft(self):
        server = FakeForgejo(fail=lambda m, url: m == 'POST' and '/assets?name=' in url)
        self.check(server, 'release rmx3997-v99 (id 5) is left on the server as an unpublished draft')
        self.assertTrue(server.draft)

    def test_failure_after_publishing_says_published(self):
        server = FakeForgejo(fail=lambda m, url: '/releases/download/' in url)
        text = self.check(server, 'release rmx3997-v99 (id 5) is already published')
        self.assertNotIn('draft', text)

    def test_clean_run_reports_no_leftover(self):
        code, text = run_release(FakeForgejo())
        self.assertIsNone(code, text)
        self.assertNotIn('FAIL', text)


class UpstreamApiRetry(unittest.TestCase):
    """upstream.py api() follows the same policy as rmx_ci.open_url()."""

    def call(self, method, answers):
        seen = []

        def urlopen(req, timeout):
            seen.append(req.get_method())
            a = answers.pop(0)
            if isinstance(a, BaseException):
                raise a
            return a

        with mock.patch.object(upstream.urllib.request, 'urlopen', urlopen), \
                mock.patch.object(upstream.time, 'sleep'), mock.patch('builtins.print') as p:
            try:
                res = upstream.api(method, 'https://forge.example/api/v1/x?page=1', 'made-up-token',
                                   None if method == 'GET' else {'body': 'b'})
            except SystemExit as e:
                res = ('exit', e.code)
        text = ' '.join(str(c[0][0]) for c in p.call_args_list)
        self.assertNotIn('made-up-token', text)
        return res, len(seen), text

    def test_get_survives_reset_timeout_and_503(self):
        res, n, _ = self.call('GET', [urllib.error.URLError(ConnectionResetError('reset')),
                                      Reply(exc=TimeoutError('timed out')), http_error('u', 503),
                                      Reply(200, b'[]')])
        self.assertEqual((res, n), ((200, []), 4))

    def test_post_without_answer_fails_cleanly_once(self):
        res, n, text = self.call('POST', [urllib.error.URLError('reset')])
        self.assertEqual((res, n), (('exit', 1), 1))
        self.assertIn('FAIL: POST https://forge.example/api/v1/x failed: reset', text)


class CheckLookupFailure(unittest.TestCase):
    """A failed upstream lookup in "check" is a FAIL line naming the component."""

    def test_rate_limited_release_lookup(self):
        manifest = {'components': {'zyc-clang': {'mode': 'release', 'github': 'o/clang', 'pin': 'v1'}}}
        err = urllib.error.HTTPError('u', 403, 'rate limit exceeded', {}, io.BytesIO(b''))
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(upstream, 'load', return_value=manifest), \
                mock.patch.object(upstream, 'latest_release', side_effect=err), \
                mock.patch('builtins.print') as p, self.assertRaises(SystemExit) as e:
            upstream.cmd_check(mock.Mock(stage=d))
        self.assertEqual(e.exception.code, 1)
        self.assertIn('FAIL: zyc-clang lookup: HTTP Error 403: rate limit exceeded', p.call_args[0][0])


class LatestReleaseLookup(unittest.TestCase):
    """The GitHub releases/latest lookup (zyc-clang, check and fresh) repeats a
    transient failure; a rate limit fails at once with a FAIL line."""

    def call(self, answers, fn=lambda: upstream.latest_release('made-up/clang')):
        seen = []

        def urlopen(req, timeout):
            seen.append(req.full_url)
            a = answers.pop(0)
            if isinstance(a, BaseException):
                raise a
            return a

        with mock.patch.object(upstream.urllib.request, 'urlopen', urlopen), \
                mock.patch.object(upstream.time, 'sleep'), mock.patch('builtins.print') as p:
            try:
                res = fn()
            except BaseException as e:
                res = e
        return res, len(seen), '\n'.join(str(c[0][0]) for c in p.call_args_list)

    def test_transient_errors_are_repeated(self):
        res, n, _ = self.call([urllib.error.URLError(ConnectionResetError('reset')),
                               Reply(exc=TimeoutError('timed out')), Reply(exc=http.client.IncompleteRead(b'')),
                               http_error('u', 503), Reply(200, b'{"tag_name": "v2"}')])
        self.assertEqual((res, n), ('v2', 5))

    def test_rate_limit_is_not_repeated(self):
        for code in (403, 429):
            res, n, _ = self.call([http_error('u', code)])
            self.assertIsInstance(res, urllib.error.HTTPError)
            self.assertEqual((res.code, n), (code, 1))

    def test_fresh_names_a_truncated_lookup(self):
        manifest = {'components': {'zyc-clang': {'mode': 'release', 'github': 'made-up/clang', 'pin': 'v1'}}}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, 'upstreams.json')
            path.write_text(json.dumps(manifest))
            res, n, text = self.call([Reply(exc=http.client.IncompleteRead(b''))] * upstream.TRIES,
                                     lambda: upstream.cmd_fresh(mock.Mock(manifest=str(path))))
        self.assertIsInstance(res, SystemExit)
        self.assertEqual((res.code, n), (1, upstream.TRIES))
        self.assertIn('FAIL: zyc-clang lookup: GET https://api.github.com/repos/made-up/clang/releases/latest failed', text)
        self.assertIn('LOOKUP-FAILED', text)


class PackageOffline(unittest.TestCase):
    """rmx_ci.py package with a made-up Image: complete, closed ZIP and its checksum.
    Host inputs (boot template, avbtool, lz4) are stubbed; the AnyKernel3
    members and their pins are the real ones from wk-anykernel."""

    MEMBERS = {
        'Image', 'LICENSE', 'META-INF/com/google/android/update-binary',
        'META-INF/com/google/android/updater-script', 'SHA256SUMS', 'anykernel.sh',
        'install-on-device.sh', 'manifest.json', 'tools/ak3-core.sh', 'tools/avbroot',
        'tools/avbroot-LICENSE', 'tools/avbroot-provenance.json', 'tools/busybox',
        'tools/busybox-LICENSE', 'tools/busybox-provenance.json', 'tools/magiskboot',
        'tools/magiskboot-LICENSE', 'tools/magiskboot-provenance.json', 'tools/rmx-avb.sh'}

    def test_package(self):
        ident = {'Image_sha256': 'a' * 64, 'vmlinux_sha256': 'b' * 64, 'config_sha256': 'c' * 64,
                 'release': '5.15.0-android13-8-gmadeup'}
        image_bytes = b'made-up kernel Image ' * 64
        packager = rmx_ci.load_packager()

        def boot(template, image, out_img, work):
            Path(out_img).write_bytes(b'made-up boot image')
            return {'kernel_lz4_bytes': 1}

        with tempfile.TemporaryDirectory() as d:
            stage = Path(d, 'stage')
            (stage / 'out/arch/arm64/boot').mkdir(parents=True)
            (stage / 'out/arch/arm64/boot/Image').write_bytes(image_bytes)
            (stage / 'acceptance.json').write_text(json.dumps(
                {'identity': ident, 'oem_crc': {'status': 'PASS'}}))
            (stage / 'toolchain.txt').write_text('clang: made-up 18\n')
            a = mock.Mock(stage=str(stage), label='rmx3997-v99', commit='c' * 40,
                          run_url='https://forge.example/run/1', private_dir=str(Path(d, 'private')))
            pins = {'files': {'boot_b_layout_template': {'path': str(Path(d, 'no-template'))}}}
            with mock.patch.object(packager, 'inspect', return_value=ident), \
                    mock.patch.object(rmx_ci, 'load_packager', return_value=packager), \
                    mock.patch.object(rmx_ci, 'load_pins', return_value=pins), \
                    mock.patch.object(rmx_ci, 'build_boot_image', boot), \
                    mock.patch.object(rmx_ci, 'verify_boot_image', return_value={'avb_digest_verified': True}), \
                    mock.patch('builtins.print'):
                rmx_ci.cmd_package(a)
            base = 'RMX3997-kernel-5.15.0-v99'
            zpath = stage / 'dist' / (base + '.zip')
            self.assertEqual(sorted(x.name for x in (stage / 'dist').iterdir()),
                             [base + '.zip', base + '.zip.sha256'])
            self.assertEqual((stage / 'dist' / (base + '.zip.sha256')).read_text(),
                             '%s  %s\n' % (hashlib.sha256(zpath.read_bytes()).hexdigest(), zpath.name))
            open_fds = [os.readlink('/proc/self/fd/' + f) for f in os.listdir('/proc/self/fd')
                        if os.path.islink('/proc/self/fd/' + f)]
            self.assertNotIn(str(zpath), open_fds)
            with zipfile.ZipFile(zpath) as z:
                self.assertIsNone(z.testzip())
                self.assertEqual(set(z.namelist()), self.MEMBERS)
                data = {n: z.read(n) for n in z.namelist()}
            self.assertEqual(data['Image'], image_bytes)
            sums = dict(reversed(l.split('  ', 1)) for l in data['SHA256SUMS'].decode().splitlines())
            self.assertEqual(set(sums), self.MEMBERS - {'SHA256SUMS'})
            for name, digest in sums.items():
                self.assertEqual(hashlib.sha256(data[name]).hexdigest(), digest, name)
            manifest = json.loads(data['manifest.json'])
            self.assertEqual((manifest['source_commit'], manifest['release']), ('c' * 40, ident['release']))
            self.assertEqual((stage / 'dist.env').read_text(),
                             'RMX_DIST=%s\nRMX_BASE=%s\n' % (stage / 'dist', base))
            self.assertTrue(Path(d, 'private', base, base + '.provenance.json').is_file())


class PromotePush(unittest.TestCase):
    """promote: one atomic push with both leases, token only in the environment,
    verified by ls-remote; a push that times out after landing still passes."""
    BASE, HEAD, TAGOBJ, TAG = 'b' * 40, 'h' * 40, 't' * 40, 'rmx3997-v99'

    def run_promote(self, push_times_out):
        calls, server = [], {'refs/heads/main': self.BASE}

        def run(argv, **kw):
            calls.append((argv, kw))
            a = argv[1:]
            if a[0] == 'rev-parse':
                return subprocess.CompletedProcess(argv, 0, self.TAGOBJ if a[1].startswith('refs/tags/')
                                                   else self.HEAD, '')
            if a[0] == 'merge-base':
                return subprocess.CompletedProcess(argv, 0, '', '')
            if a[0] == 'ls-remote':
                return subprocess.CompletedProcess(argv, 0, ''.join(
                    '%s\t%s\n' % (v, k) for k, v in server.items()), '')
            if a[0] == 'push':
                server.update({'refs/heads/main': self.HEAD, 'refs/tags/' + self.TAG: self.TAGOBJ})
                if push_times_out:
                    raise subprocess.TimeoutExpired(argv, kw['timeout'])
                return subprocess.CompletedProcess(argv, 0, '', '')
            raise AssertionError(argv)

        with tempfile.TemporaryDirectory() as d:
            stage = Path(d)
            (stage / 'b').mkdir()
            (stage / 'src').mkdir()
            (stage / 'b/acceptance.json').write_text('{}')
            (stage / 'b/dist.env').write_text('')
            (stage / 'candidate.json').write_text(json.dumps(
                {'base': self.BASE, 'release': {'tag': self.TAG, 'commit': self.HEAD}}))
            with mock.patch.object(upstream.subprocess, 'run', run), \
                    mock.patch.object(upstream.time, 'sleep'), \
                    mock.patch.dict('os.environ', {'TOKEN': 'made-up-token'}), \
                    mock.patch('builtins.print'):
                upstream.cmd_promote(mock.Mock(stage=d, repo_url='https://forge.example/o/r.git'))
            ok = (stage / 'promote.ok').read_text()
        return calls, ok

    def check(self, push_times_out):
        calls, ok = self.run_promote(push_times_out)
        self.assertEqual(ok, self.HEAD + '\n')
        pushes = [(argv, kw) for argv, kw in calls if argv[1] == 'push']
        self.assertEqual(len(pushes), 1)
        argv, kw = pushes[0]
        self.assertIn('--force-with-lease=refs/heads/main:' + self.BASE, argv)
        self.assertIn('--force-with-lease=refs/tags/%s:' % self.TAG, argv)
        self.assertIn('--atomic', argv)
        self.assertFalse([x for x in argv if 'made-up-token' in x or 'basic' in x], argv)
        self.assertTrue(kw['env']['GIT_CONFIG_VALUE_0'].startswith('Authorization: basic '))
        self.assertEqual(kw['timeout'], upstream.GIT_TRANSFER_TIMEOUT)
        self.assertNotIn('GIT_HTTP_LOW_SPEED_LIMIT', kw['env'])
        self.assertNotIn('GIT_HTTP_LOW_SPEED_TIME', kw['env'])

    def test_push(self):
        self.check(False)

    def test_push_timeout_after_the_refs_landed(self):
        self.check(True)


class LsRemoteStallAbort(unittest.TestCase):
    """ls-remote carries git's low-speed abort; fetch and push do not."""
    LOW = {'GIT_HTTP_LOW_SPEED_LIMIT': '1000', 'GIT_HTTP_LOW_SPEED_TIME': '60'}

    def capture(self, fn):
        calls = []

        def run(argv, **kw):
            calls.append((argv, kw['env']))
            return subprocess.CompletedProcess(argv, 0, 'a' * 40 + '\trefs/heads/main\n', '')

        with mock.patch.object(upstream.subprocess, 'run', run), mock.patch('builtins.print'):
            fn()
        return calls

    def assert_low_speed(self, env, present):
        for k, v in self.LOW.items():
            self.assertEqual(env.get(k), v if present else None, k)

    def test_remote_head(self):
        (argv, env), = self.capture(lambda: upstream.remote_head('https://forge.example/o/r.git', 'main'))
        self.assertEqual(argv[1], 'ls-remote')
        self.assert_low_speed(env, True)

    def test_remote_refs_keeps_auth(self):
        (argv, env), = self.capture(lambda: upstream.remote_refs('https://forge.example/o/r.git', 't', 'refs/heads/main'))
        self.assert_low_speed(env, True)
        self.assertTrue(env['GIT_CONFIG_VALUE_0'].startswith('Authorization: basic '))

    def test_cache_fetch_has_no_low_speed_abort(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(upstream, 'CACHE', Path(d)):
            Path(d, 'made-up.git').mkdir()
            calls = self.capture(lambda: upstream.cache('made-up', 'https://forge.example/o/r.git', ['main']))
        fetches = [env for argv, env in calls if 'fetch' in argv]
        self.assertEqual(len(fetches), 1)
        self.assert_low_speed(fetches[0], False)


class PruneStages(unittest.TestCase):
    """prune-stages removes only the build trees of old run-/upstream- stages."""

    def make(self, root, name, rels, age_days):
        stage = root / name
        stage.mkdir()
        for rel in rels:
            (stage / rel).mkdir(parents=True, exist_ok=True)
            (stage / rel / 'f').write_text('x')
        old = upstream.time.time() - age_days * 86400
        for p in sorted(stage.rglob('*'), reverse=True) + [stage]:
            os.utime(p, (old, old))
        return stage

    def run_prune(self, root, keep=None):
        a = mock.Mock(root=str(root), keep=str(keep) if keep else None, days=7)
        with mock.patch('builtins.print') as p:
            rmx_ci.cmd_prune_stages(a)
        return '\n'.join(str(c[0][0]) for c in p.call_args_list)

    def test_prune(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run_old = self.make(root, 'run-5-1', ['out', 'work', 'tmp', 'pycache', 'dist'], 10)
            (run_old / 'build.log').write_text('log')
            (run_old / 'acceptance.json').write_text('{}')
            up_old = self.make(root, 'upstream-6-2', ['b/out', 'b/work', 'b/tmp', 'b/dist', 'cfg', 'src'], 10)
            (up_old / 'candidate.json').write_text('{}')
            for st in (run_old, up_old):
                os.utime(st, (upstream.time.time() - 10 * 86400,) * 2)
            fresh = self.make(root, 'run-7-1', ['out'], 1)
            current = self.make(root, 'run-8-1', ['out'], 10)
            other = self.make(root, 'local-n17', ['out'], 10)
            cache = self.make(root, 'upstream', ['aosp.git'], 10)
            odd = self.make(root, 'run-9-1x', ['out'], 10)
            outside = self.make(root, 'outside', ['keepme'], 10)
            linked = self.make(root, 'run-10-1', [], 10)
            (linked / 'out').symlink_to(outside / 'keepme')
            os.utime(linked, (upstream.time.time() - 10 * 86400,) * 2)
            text = self.run_prune(root, keep=current)
            self.assertEqual(sorted(x.name for x in run_old.iterdir()), ['acceptance.json', 'build.log', 'dist'])
            self.assertEqual(sorted(x.name for x in up_old.iterdir()), ['b', 'candidate.json'])
            self.assertEqual(sorted(x.name for x in (up_old / 'b').iterdir()), ['dist'])
            for kept in (fresh, current, other, odd):
                self.assertTrue((kept / 'out/f').is_file(), kept.name)
            self.assertTrue((cache / 'aosp.git/f').is_file())
            self.assertTrue((outside / 'keepme/f').is_file())
            self.assertIn('pruned run-5-1: out work tmp pycache', text)
            self.assertIn('pruned upstream-6-2: b/out b/work b/tmp cfg src', text)
            self.assertIn('2 stage(s) older than 7 days pruned', text)

    def test_error_is_a_warning(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.make(root, 'run-5-1', ['out'], 10)
            with mock.patch.object(rmx_ci.shutil, 'rmtree', side_effect=PermissionError('denied')):
                text = self.run_prune(root)
            self.assertIn('WARN: prune-stages: run-5-1: denied; the build continues', text)

    def test_unexpected_error_is_a_warning(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.make(root, 'run-5-1', ['out'], 10)
            with mock.patch.object(rmx_ci, 'prune_stage', side_effect=ValueError('odd')):
                text = self.run_prune(root)
            self.assertIn('WARN: prune-stages: run-5-1: odd; the build continues', text)

    def test_missing_root(self):
        with tempfile.TemporaryDirectory() as d:
            text = self.run_prune(Path(d, 'absent'))
        self.assertIn('0 stage(s)', text)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run(['python3', '-I', str(CI / 'rmx_ci.py'), 'prune-stages', '--root', d],
                               capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class OtherChanges(unittest.TestCase):
    """plan-release lists hand-landed commits between the previous tag and the base."""
    ID = ['-c', 'user.name=Made Up', '-c', 'user.email=made-up@example.invalid']

    def commit(self, ws, path, text, subject):
        Path(ws, path).parent.mkdir(parents=True, exist_ok=True)
        Path(ws, path).write_text(text)
        upstream.git('add', path, cwd=ws)
        upstream.git(*self.ID, 'commit', '-q', '-m', subject, cwd=ws)
        return upstream.out('rev-parse', 'HEAD', cwd=ws)

    def repo(self, d):
        ws = Path(d, 'src')
        ws.mkdir(parents=True)
        upstream.git('init', '-q', cwd=ws)
        return ws

    def test_lists_hand_landed_commits_only(self):
        with tempfile.TemporaryDirectory() as d:
            ws = self.repo(d)
            prev = self.commit(ws, 'a', '1', 'README and release notes: rmx3997-v1')
            self.commit(ws, 'b', '2', 'upstream: nomount 1111..2222')
            base = self.commit(ws, 'c', '3 {braces}', 'net: fix {a} thing')
            self.commit(ws, 'd', '4', 'upstream: record pins (nomount)')
            with mock.patch('builtins.print'):
                got = upstream.other_changes(ws, prev, base)
        self.assertEqual(got, ['net: fix {a} thing', 'upstream: nomount 1111..2222'])

    def test_lists_only_commits_that_change_shipped_files(self):
        with tempfile.TemporaryDirectory() as d:
            ws = self.repo(d)
            prev = self.commit(ws, 'a', '1', 'README and release notes: rmx3997-v1')
            self.commit(ws, 'rmx3997/ci/x.py', '2', 'ci: script fix')
            self.commit(ws, '.forgejo/workflows/w.yml', '3', 'workflow: tweak')
            self.commit(ws, 'README.md', '4', 'README: wording')
            self.commit(ws, 'rmx3997/development/tool.py', '5', 'development: tool')
            self.commit(ws, 'rmx3997/development/wk-anykernel/i.sh', '6', 'installer: message')
            self.commit(ws, 'rmx3997/config/production.config', '7', 'config: option')
            base = self.commit(ws, 'net/x.c', '8', 'net: fix')
            with mock.patch('builtins.print'):
                got = upstream.other_changes(ws, prev, base)
        self.assertEqual(got, ['net: fix', 'config: option', 'installer: message'])

    def test_missing_history_is_silent(self):
        with tempfile.TemporaryDirectory() as d:
            ws = self.repo(d)
            base = self.commit(ws, 'a', '1', 'x')
            other = self.repo(Path(d, 'o'))
            foreign = self.commit(other, 'z', '9', 'unrelated')
            for prev in (None, 'f' * 40, foreign):
                with mock.patch('builtins.print') as p:
                    self.assertEqual(upstream.other_changes(ws, prev, base), [])
                self.assertEqual(len(p.call_args_list), 1)
                self.assertIn('no "Other changes" list', p.call_args[0][0])

    def test_log_failure_is_silent(self):
        with tempfile.TemporaryDirectory() as d:
            ws = self.repo(d)
            prev = self.commit(ws, 'a', '1', 'x')
            base = self.commit(ws, 'b', '2', 'y')
            real = upstream.git

            def git(*a, **kw):
                if a[0] == 'log':
                    return subprocess.CompletedProcess(a, 128, '', 'fatal')
                return real(*a, **kw)

            with mock.patch.object(upstream, 'git', git), mock.patch('builtins.print') as p:
                self.assertEqual(upstream.other_changes(ws, prev, base), [])
        self.assertIn('no "Other changes" list', p.call_args[0][0])

    def test_plan_release_writes_the_list(self):
        notes = ('Kernel {kernel} at {commit}\n\n## Changes in this release\n\n- old\n\n'
                 '## Kernel features\n\nLinux {version}\n'
                 '| Module mounting | NoMount, protocol 1 (metamodule versionCode 10) |\n')
        readme = ('# made-up kernel - Linux 5.15.1\n\n| Kernel | Linux 5.15.1, GKI |\n'
                  '| Metamodule support | NoMount protocol 1 (metamodule versionCode 10) |\n\n'
                  '- NoMount on the upstream track (example `dev`), protocol 1\n\n'
                  '| Release | Kernel | Change |\n| --- | --- | --- |\n| `rmx3997-v1` | 5.15.1 | first |\n')
        manifest = {'components': {'nomount': {'mode': 'subtree', 'ref': 'dev', 'pin': '2' * 40}}}
        with tempfile.TemporaryDirectory() as d:
            ws = self.repo(Path(d, 'stage'))
            stage = ws.parent
            self.commit(ws, 'Makefile', 'VERSION = 5\nPATCHLEVEL = 15\nSUBLEVEL = 1\n', 'init')
            self.commit(ws, 'fs/nomount/nomount.h', '#define NOMOUNT_BASE_VERSION "2"\n', 'nomount')
            self.commit(ws, 'README.md', readme, 'readme')
            self.commit(ws, 'rmx3997/ci/release-notes.md', notes, 'notes')
            prev = self.commit(ws, upstream.MANIFEST, json.dumps(manifest), 'README and release notes: rmx3997-v1')
            self.commit(ws, 'fs/y.c', 'int y;\n', 'upstream: nomount 1111..2222')
            base = self.commit(ws, 'fs/x.c', 'int x;\n', 'fs: hand-landed fix {1}')
            self.commit(ws, 'fs/z.c', 'int z;\n', 'upstream: record pins (nomount)')
            cand = {'base': base, 'changed': True, 'components': [
                {'name': 'nomount', 'status': 'applied', 'pin': '1' * 40, 'tip': '2' * 40, 'count': 1}]}
            (stage / 'candidate.json').write_text(json.dumps(cand))
            env = {k: v for k, v in os.environ.items() if k not in ('FORGEJO_ENV', 'GITHUB_ENV')}
            with mock.patch.object(upstream, 'next_tag', return_value=('rmx3997-v2', prev)), \
                    mock.patch.object(upstream, 'IDENT', self.ID), \
                    mock.patch.dict('os.environ', env, clear=True), mock.patch('builtins.print'), \
                    mock.patch.object(upstream, 'metamodule_code', return_value=42) as mc:
                upstream.cmd_plan_release(mock.Mock(stage=str(stage), repo_url='https://forge.example/o/r.git'))
            text = (ws / 'rmx3997/ci/release-notes.md').read_text()
            new_readme = (ws / 'README.md').read_text()
        mc.assert_called_once_with('2' * 40)
        self.assertIn('| Metamodule support | NoMount protocol 2 (metamodule versionCode 42) |', new_readme)
        self.assertIn('(example `dev`), protocol 2\n', new_readme)
        self.assertIn('| Module mounting | NoMount, protocol 2 (metamodule versionCode 42) |', text)
        self.assertIn('- Other changes on main since the previous release:\n'
                      '  - fs: hand-landed fix {{1}}\n  - upstream: nomount 1111..2222\n\n## Kernel', text)
        self.assertNotIn('record pins', text)
        self.assertIn('fs: hand-landed fix {1}', text.format(kernel='k', version='v', commit='c'))


    def test_plan_release_names_a_hand_landed_linux_update(self):
        notes = 'Kernel {kernel}\n\n## Changes in this release\n\n- old\n\n## Kernel features\n'
        readme = ('# made-up kernel - Linux 5.15.2\n\n| Kernel | Linux 5.15.2, GKI |\n\n'
                  '| Release | Kernel | Change |\n| --- | --- | --- |\n| `rmx3997-v1` | 5.15.1 | first |\n')
        manifest = {'components': {'bakasu': {'mode': 'subtree', 'ref': 'main', 'pin': '2' * 40}}}
        with tempfile.TemporaryDirectory() as d:
            ws = self.repo(Path(d, 'stage'))
            stage = ws.parent
            self.commit(ws, 'Makefile', 'VERSION = 5\nPATCHLEVEL = 15\nSUBLEVEL = 1\n', 'init')
            self.commit(ws, 'rmx3997/ci/release-notes.md', notes, 'notes')
            prev = self.commit(ws, upstream.MANIFEST, json.dumps(manifest), 'README and release notes: rmx3997-v1')
            self.commit(ws, 'Makefile', 'VERSION = 5\nPATCHLEVEL = 15\nSUBLEVEL = 2\n', 'Merge LTS (5.15.2)')
            base = self.commit(ws, 'README.md', readme, 'README: Linux 5.15.2')
            cand = {'base': base, 'changed': True, 'components': [
                {'name': 'bakasu', 'status': 'applied', 'pin': '1' * 40, 'tip': '2' * 40, 'count': 1}]}
            (stage / 'candidate.json').write_text(json.dumps(cand))
            env = {k: v for k, v in os.environ.items() if k not in ('FORGEJO_ENV', 'GITHUB_ENV')}
            with mock.patch.object(upstream, 'next_tag', return_value=('rmx3997-v2', prev)), \
                    mock.patch.object(upstream, 'IDENT', self.ID), \
                    mock.patch.dict('os.environ', env, clear=True), mock.patch('builtins.print'):
                upstream.cmd_plan_release(mock.Mock(stage=str(stage), repo_url='https://forge.example/o/r.git'))
            text = (ws / 'rmx3997/ci/release-notes.md').read_text()
            new_readme = (ws / 'README.md').read_text()
        self.assertIn('| `rmx3997-v2` | 5.15.2 | Upstream update: Linux 5.15.2 (from 5.15.1), BakaSU `22222222` |',
                      new_readme)
        self.assertIn('- Linux 5.15.1 to 5.15.2, merged on main before this job (see Other changes).', text)

class NextTagPrevious(unittest.TestCase):
    def test_peeled_commit_of_the_last_tag(self):
        refs = {'refs/tags/rmx3997-v1': '1' * 40, 'refs/tags/rmx3997-v2': 't' * 40,
                'refs/tags/rmx3997-v2^{}': 'c' * 40}
        with mock.patch.object(upstream, 'remote_refs', return_value=refs):
            self.assertEqual(upstream.next_tag('u', 't'), ('rmx3997-v3', 'c' * 40))

    def test_lightweight_tag(self):
        with mock.patch.object(upstream, 'remote_refs', return_value={'refs/tags/rmx3997-v1': 'a' * 40}):
            self.assertEqual(upstream.next_tag('u', 't'), ('rmx3997-v2', 'a' * 40))


class InstallerMessages(unittest.TestCase):
    """install-on-device.sh says why it stops; never runs past BASE on the host."""
    SCRIPT = CI.parent / 'development/wk-anykernel/install-on-device.sh'

    def run_sh(self, d, script, *args):
        stubs = Path(d, 'stubs')
        stubs.mkdir(exist_ok=True)
        Path(stubs, 'id').write_text('#!/bin/sh\necho 0\n')
        Path(stubs, 'id').chmod(0o755)
        # The installer refuses a RAM filesystem (tmpfs/ramfs) for its work
        # dir; report ext4 so the tests do not depend on where TMPDIR lives.
        Path(stubs, 'stat').write_text('#!/bin/sh\necho ef53\n')
        Path(stubs, 'stat').chmod(0o755)
        return subprocess.run(['sh', str(script), *args], capture_output=True, text=True, cwd=d,
                              env={'PATH': '%s:/usr/bin:/bin' % stubs})

    def copy_with_base(self, d):
        base = Path(d, 'base')
        text = self.SCRIPT.read_text()
        self.assertEqual(text.count('BASE=/data/adb/rmx3997-ak3\n'), 1)
        script = Path(d, 'install-on-device.sh')
        script.write_text(text.replace('BASE=/data/adb/rmx3997-ak3\n', 'BASE=%s\n' % base))
        return script, base

    def test_missing_package(self):
        with tempfile.TemporaryDirectory() as d:
            for arg in (str(Path(d, 'absent.zip')), str(Path(d, 'no/such/dir/x.zip'))):
                r = self.run_sh(d, self.SCRIPT, arg)
                self.assertEqual(r.returncode, 1)
                self.assertIn('Package not found: ' + arg, r.stderr)

    def test_symlinked_base(self):
        with tempfile.TemporaryDirectory() as d:
            script, base = self.copy_with_base(d)
            Path(d, 'pkg.zip').write_bytes(b'')
            Path(d, 'elsewhere').mkdir()
            base.symlink_to(Path(d, 'elsewhere'))
            r = self.run_sh(d, script, 'pkg.zip')
            self.assertEqual(r.returncode, 1)
            self.assertIn('is a symlink; refusing to install', r.stderr)
            self.assertEqual(list(Path(d, 'elsewhere').iterdir()), [])

    @unittest.skipUnless(shutil.which('unzip'), 'unzip not installed')
    def test_checksum_failure(self):
        with tempfile.TemporaryDirectory() as d:
            script, base = self.copy_with_base(d)
            with zipfile.ZipFile(Path(d, 'pkg.zip'), 'w') as z:
                z.writestr('tools/busybox', '#!/bin/sh\nexit 1\n')
                z.writestr('SHA256SUMS', '00  x\n')
            r = self.run_sh(d, script, 'pkg.zip')
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn('Package checksum verification failed', r.stderr)


class BackendMessages(unittest.TestCase):
    """update-binary says why it stops before any work (no getprop stub that passes)."""
    SCRIPT = CI.parent / 'development/wk-anykernel/META-INF/com/google/android/update-binary'

    def run_backend(self, d, env):
        stubs = Path(d, 'stubs')
        stubs.mkdir(exist_ok=True)
        Path(stubs, 'getprop').write_text('#!/bin/sh\necho 0\n')
        Path(stubs, 'getprop').chmod(0o755)
        return subprocess.run(['sh', str(self.SCRIPT), '3', '1', str(Path(d, 'pkg.zip'))],
                              capture_output=True, text=True, cwd=d,
                              env=dict(env, PATH='%s:/usr/bin:/bin' % stubs))

    def test_without_akhome(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.run_backend(d, {})
        self.assertEqual(r.returncode, 1)
        self.assertIn('Run install-on-device.sh: AKHOME is not set', r.stderr)

    def test_not_booted(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.run_backend(d, {'AKHOME': str(Path(d, 'work'))})
            self.assertFalse(Path(d, 'work').exists())
        self.assertEqual(r.returncode, 1)
        self.assertIn('A fully booted Android is required', r.stderr)


if __name__ == '__main__':
    unittest.main()
