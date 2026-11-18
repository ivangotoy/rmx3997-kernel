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


if __name__ == '__main__':
    unittest.main()
