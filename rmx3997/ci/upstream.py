#!/usr/bin/env python3
"""RMX3997 upstream watcher and automatic release.

check         compare every pinned upstream in upstreams.json with its live branch
candidate     build the candidate on top of main in the stage (local only): merge
              the new AOSP LTS, cherry-pick new android13-5.15 security commits,
              3-way apply component updates
refresh-commit  commit production.config when olddefconfig only added symbols
plan-release  pick the next rmx3997-vN tag, add the README and release notes
              commit and create the annotated tag locally
promote       after every gate passed: fast-forward main to the candidate and
              push the tag, in one atomic push
report        post the result to the tracking issue
verify        prove the vendored files equal the pinned upstream blobs

No branch other than main is ever pushed. Nothing is pushed unless the build,
every acceptance gate and packaging passed.
"""
import argparse
import base64
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

REPO = Path(__file__).resolve().parents[2]
MANIFEST = 'rmx3997/ci/upstreams.json'
CACHE = Path.home() / '.cache/rmx3997-ci/upstream'
ISSUE_TITLE = 'Upstream updates'
GIT_ENV = dict(os.environ, GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1',
               GIT_TERMINAL_PROMPT='0', LC_ALL='C')
IDENT = ['-c', 'user.name=Ivan Angelov', '-c', 'user.email=ivangotoy@gmail.com']


def die(msg):
    print('FAIL: ' + msg, flush=True)
    raise SystemExit(1)


def git(*args, cwd=None, check=True, inp=None):
    r = subprocess.run(['git', *args], cwd=cwd, env=GIT_ENV, input=inp,
                       capture_output=True, text=inp is None or isinstance(inp, str))
    if check and r.returncode:
        die('git %s: %s' % (' '.join(args[:3]), (r.stderr or '').strip()[-600:]))
    return r


def out(*args, cwd=None):
    return git(*args, cwd=cwd).stdout.strip()


def load(src=REPO):
    return json.loads((Path(src) / MANIFEST).read_text())


def remote_head(url, ref):
    lines = out('ls-remote', url, 'refs/heads/' + ref).splitlines()
    if len(lines) != 1:
        die('ls-remote %s %s returned %d refs' % (url, ref, len(lines)))
    return lines[0].split()[0]


def latest_release(repo):
    req = urllib.request.Request('https://api.github.com/repos/%s/releases/latest' % repo,
                                 headers={'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)['tag_name']


# ------------------------------------------------------------------- check
def cmd_check(a):
    m = load()
    rows, updates = [], 0
    for name, c in m['components'].items():
        tip = latest_release(c['github']) if c['mode'] == 'release' else remote_head(c['url'], c['ref'])
        new = tip != c['pin']
        updates += new
        rows.append({'name': name, 'mode': c['mode'], 'pin': c['pin'], 'tip': tip, 'new': new})
        print('%-15s %-9s %s %s' % (name, c['mode'], 'NEW' if new else 'current',
                                    tip[:12] if new else c['pin'][:12]))
    stage = Path(a.stage)
    stage.mkdir(parents=True, exist_ok=True)
    (stage / 'check.json').write_text(json.dumps(rows, indent=2) + '\n')
    auto = sum(r['new'] and m['components'][r['name']]['mode'] not in ('report', 'release') for r in rows)
    print('updates: %d (%d auto-applicable)' % (updates, auto))
    env = os.environ.get('FORGEJO_ENV') or os.environ.get('GITHUB_ENV')
    if env:
        with open(env, 'a') as f:
            f.write('RMX_UPDATES=%d\nRMX_AUTO_UPDATES=%d\n' % (updates > 0, auto > 0))


# ------------------------------------------------------------------ caches
def cache(name, url, refs, shallow_since=None):
    d = CACHE / (name + '.git')
    if not d.is_dir():
        d.parent.mkdir(parents=True, exist_ok=True)
        git('init', '-q', '--bare', str(d))
    args = ['-C', str(d), 'fetch', '-q', '--no-tags']
    if shallow_since:
        args.append('--shallow-since=' + shallow_since)
    specs = ['+refs/heads/%s:refs/heads/%s' % (r, r) for r in refs]
    if name == 'bakasu':
        # bakasu_identity() needs the release tags for git describe
        specs.append('+refs/tags/*:refs/tags/*')
    git(*args, url, *specs)
    return d


def tip_of(d, ref):
    return out('-C', str(d), 'rev-parse', 'refs/heads/' + ref)


# --------------------------------------------------------------- candidate
def apply_subtree(ws, cdir, c, pin, tip):
    """3-way apply upstream pin..tip of the mapped paths. Returns (status, detail)."""
    touched = out('-C', str(cdir), 'diff', '--name-only', pin, tip).splitlines()
    manual = [p for p in touched if any(p.startswith(x) for x in c.get('manual_paths', []))]
    if manual:
        return 'manual', 'changed upstream files need a manual port: ' + ', '.join(manual)
    for up, local in c['paths'].items():
        filt = [p for p in c['files'] if p.startswith(up)] if c.get('files') else [up or '.']
        args = ['-C', str(cdir), 'diff', '--full-index', '--binary', pin, tip]
        if up:
            args.insert(4, '--relative=' + up)
        patch = git(*args, '--', *filt).stdout
        if not patch:
            continue
        r = git('apply', '-3', '--index', *(['--directory=' + local] if local else []), cwd=ws,
                check=False, inp=patch)
        if r.returncode:
            conflicts = out('diff', '--name-only', '--diff-filter=U', cwd=ws).splitlines()
            git('reset', '-q', '--hard', 'HEAD', cwd=ws)
            return 'conflict', 'conflicts: ' + ', '.join(conflicts or [r.stderr.strip()[-300:]])
    return 'applied', None


def bakasu_identity(ws, cdir, tip):
    count = int(out('-C', str(cdir), 'rev-list', '--count', tip))
    tag = out('-C', str(cdir), 'describe', '--tags', '--abbrev=0', tip)
    (ws / 'drivers/kernelsu/UPSTREAM_COMMIT').write_text(tip + '\n')
    kb = ws / 'drivers/kernelsu/Kbuild'
    t = kb.read_text()
    subs = [(r'(ifneq \(\$\(BAKASU_UPSTREAM\),)[0-9a-f]{40}\)', r'\g<1>%s)' % tip),
            (r'(BakaSU )[0-9a-f]{40}\.', r'\g<1>%s.' % tip),
            (r'KSU_LOCAL_VERSION := \d+', 'KSU_LOCAL_VERSION := %d' % count),
            (r'KSU_VERSION := \d+', 'KSU_VERSION := %d' % (30700 + count)),
            (r'KSU_TAG_NAME := \S+', 'KSU_TAG_NAME := ' + tag),
            (r'KSU_COMMIT_SHA := [0-9a-f]+', 'KSU_COMMIT_SHA := ' + tip[:8])]
    for pat, rep in subs:
        t, n = re.subn(pat, rep, t)
        if n != 1:
            return 'conflict: Kbuild identity line not found: ' + pat
    kb.write_text(t)
    git('add', 'drivers/kernelsu/UPSTREAM_COMMIT', 'drivers/kernelsu/Kbuild', cwd=ws)
    return None


def subjects(cdir, rng, limit=40):
    s = out('-C', str(cdir), 'log', '--no-merges', '--format=- %h %s', rng).splitlines()
    return s[:limit] + (['- ... %d more' % (len(s) - limit)] if len(s) > limit else [])


def commit(ws, msg):
    git(*IDENT, 'commit', '-q', '--no-verify', '-m', msg, cwd=ws)


def cmd_candidate(a):
    stage = Path(a.stage)
    rows = {r['name']: r for r in json.loads((stage / 'check.json').read_text())}
    m = load()
    ws = stage / 'src'
    if ws.exists():
        die('candidate workspace exists: ' + str(ws))
    rmx = cache('rmx', a.repo_url, ['main'])
    since = (datetime.date.today() - datetime.timedelta(days=240)).isoformat()
    caches = {}
    for name, c in m['components'].items():
        if rows[name]['new'] and c['mode'] in ('lts-merge', 'security-backports', 'subtree'):
            key = 'aosp' if c['mode'] != 'subtree' else name
            if key not in caches:
                caches[key] = cache(key, c['url'], sorted({x['ref'] for x in m['components'].values()
                                                          if x.get('url') == c['url']}),
                                    since if key == 'aosp' else None)
    ws.mkdir(parents=True)
    git('init', '-q', cwd=ws)
    alt = [str(rmx / 'objects')] + [str(d / 'objects') for d in caches.values()]
    (ws / '.git/objects/info/alternates').write_text('\n'.join(alt) + '\n')
    git('fetch', '-q', '--no-tags', str(rmx), '+refs/heads/main:refs/remotes/origin/main', cwd=ws)
    base = out('rev-parse', 'refs/remotes/origin/main', cwd=ws)
    if base != a.expect_main:
        die('main moved: cache has %s, run started at %s' % (base, a.expect_main))
    git('checkout', '-q', '--detach', base, cwd=ws)
    results = []
    for name, c in m['components'].items():
        r = rows[name]
        res = {'name': name, 'mode': c['mode'], 'pin': c['pin'], 'tip': r['tip']}
        results.append(res)
        if not r['new']:
            res['status'] = 'current'
            continue
        if c['mode'] in ('report', 'release'):
            res['status'] = 'report'
            res['detail'] = c.get('note', 'manual update')
            continue
        cdir = caches['aosp' if c['mode'] != 'subtree' else name]
        tip = tip_of(cdir, c['ref'])
        if tip != r['tip']:
            res.update(status='skipped', detail='branch moved during the run')
            continue
        head0 = out('rev-parse', 'HEAD', cwd=ws)
        if c['mode'] == 'lts-merge':
            mk = git('-C', str(cdir), 'show', tip + ':Makefile').stdout
            ver = '5.%s.%s' % tuple(re.search(r'^%s = (\d+)' % k, mk, re.M).group(1)
                                    for k in ('PATCHLEVEL', 'SUBLEVEL'))
            snap = out(*IDENT, 'commit-tree', tip + '^{tree}', '-p', c['snapshot'], '-m',
                       'AOSP %s at %s (%s)\n\nTree of %s %s %s; the parentless snapshot keeps\n'
                       'the AOSP history out of this repository.' %
                       (c['ref'], tip[:12], ver, c['url'], c['ref'], tip), cwd=ws)
            mr = git(*IDENT, 'merge', '--no-ff', '-q', '-m', 'Merge AOSP %s %s (%s)' %
                     (c['ref'], tip[:12], ver), snap, cwd=ws, check=False)
            if mr.returncode:
                conflicts = out('diff', '--name-only', '--diff-filter=U', cwd=ws).splitlines()
                git('merge', '--abort', cwd=ws, check=False)
                res.update(status='conflict', detail='conflicts: ' + ', '.join(conflicts))
                continue
            c['snapshot'] = snap
            res['version'] = ver
        elif c['mode'] == 'security-backports':
            lts_tip = tip_of(cdir, m['components']['aosp-lts']['ref'])
            todo = out('-C', str(cdir), 'rev-list', '--reverse', '--no-merges',
                       '%s..%s' % (c['pin'], tip), '^' + lts_tip).splitlines()
            done, skipped = 0, 0
            for sha in todo:
                cp = git(*IDENT, 'cherry-pick', '-x', sha, cwd=ws, check=False)
                if cp.returncode:
                    if not out('status', '--porcelain', '--untracked-files=no', cwd=ws):
                        git('cherry-pick', '--skip', cwd=ws, check=False)
                        skipped += 1
                        continue
                    git('cherry-pick', '--abort', cwd=ws, check=False)
                    git('reset', '-q', '--hard', head0, cwd=ws)
                    res.update(status='conflict', detail='%s does not apply: %s' % (
                        sha[:12], out('-C', str(cdir), 'log', '-1', '--format=%s', sha)))
                    break
                done += 1
            if res.get('status'):
                continue
            res['detail'] = '%d applied, %d already present' % (done, skipped)
        else:
            st, detail = apply_subtree(ws, cdir, c, c['pin'], tip)
            if st == 'applied' and name == 'bakasu':
                detail = bakasu_identity(ws, cdir, tip)
                st = 'conflict' if detail else st
                if detail:
                    git('reset', '-q', '--hard', head0, cwd=ws)
            if st != 'applied':
                res.update(status=st, detail=detail)
                continue
            if not out('diff', '--cached', '--name-only', cwd=ws):
                detail = 'upstream changes already present in the tree'
            else:
                commit(ws, 'upstream: %s %s..%s\n\n%s %s\n\n%s' % (
                    name, c['pin'][:12], tip[:12], c['url'], c['ref'],
                    '\n'.join(subjects(cdir, '%s..%s' % (c['pin'], tip)))))
            res['detail'] = detail or c.get('note')
        res['status'] = 'applied'
        res['commits'] = subjects(cdir, '%s..%s' % (c['pin'], tip))
        res['count'] = int(out('-C', str(cdir), 'rev-list', '--count', '--no-merges',
                               '%s..%s' % (c['pin'], tip)))
        c['pin'] = tip
    (ws / MANIFEST).write_text(json.dumps(m, indent=2) + '\n')
    git('add', MANIFEST, cwd=ws)
    applied = [r['name'] for r in results if r['status'] == 'applied']
    if applied:
        commit(ws, 'upstream: record pins (%s)' % ', '.join(applied))
    state = {'base': base, 'components': results, 'changed': bool(applied)}
    (stage / 'candidate.json').write_text(json.dumps(state, indent=2) + '\n')
    env = os.environ.get('FORGEJO_ENV') or os.environ.get('GITHUB_ENV')
    if env:
        with open(env, 'a') as f:
            f.write('RMX_CAND_SRC=%s\nRMX_CAND_CHANGED=%d\n' % (ws, bool(applied)))
    for r in results:
        print('%-15s %-10s %s' % (r['name'], r['status'], r.get('detail') or ''))


def cmd_refresh_commit(a):
    """Commit production.config if build.sh RMX_REFRESH_CONFIG changed it."""
    ws = Path(a.src)
    if out('status', '--porcelain', '--', 'rmx3997/config/production.config', cwd=ws):
        git('add', 'rmx3997/config/production.config', cwd=ws)
        commit(ws, 'config: olddefconfig after upstream update\n\nOnly new symbols were added; '
               'no existing option changed.')
        print('production.config refreshed and committed')
    else:
        print('production.config unchanged')


# ----------------------------------------------------------------- release
TRIES = 6
DISPLAY = {'aosp-lts': 'AOSP `android13-5.15-lts`', 'aosp-security': '`android13-5.15` security branch',
           'bakasu': 'BakaSU', 'susfs': 'SUSFS', 'nomount': 'NoMount',
           'baseband-guard': 'Baseband Guard'}


def backoff(retry_after, attempt):
    try:
        wait = max(0, min(int(retry_after), 300))
    except (TypeError, ValueError):
        wait = 10 * attempt
    print('HTTP 429, retrying in %d s' % wait, flush=True)
    time.sleep(wait)


def api(method, url, token, data=None):
    body = json.dumps(data).encode() if data is not None else None
    for attempt in range(1, TRIES + 1):
        req = urllib.request.Request(url, method=method, data=body,
                                     headers={'Authorization': 'token ' + token,
                                              'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read()
                return r.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < TRIES:
                backoff(e.headers.get('Retry-After'), attempt)
                continue
            return e.code, None


def auth(token):
    basic = base64.b64encode(('x-access-token:' + token).encode()).decode()
    return ['-c', 'http.extraHeader=Authorization: basic ' + basic]


def remote_refs(url, token, *patterns):
    """ls-remote with bounded retry; {refname: sha}, peeled tags as <name>^{}."""
    for attempt in range(1, TRIES + 1):
        r = git(*auth(token), 'ls-remote', url, *patterns, check=False)
        if not r.returncode:
            return {l.split('\t', 1)[1]: l.split('\t', 1)[0] for l in r.stdout.splitlines() if l}
        print('ls-remote attempt %d failed: %s' % (attempt, r.stderr.strip()[-300:]), flush=True)
        if attempt < TRIES:
            time.sleep(5 * attempt)
    die('ls-remote %s failed %d times' % (url, TRIES))


def next_tag(url, token):
    nums = set()
    for name in remote_refs(url, token, 'refs/tags/rmx3997-v*'):
        if name.endswith('^{}'):
            continue
        m = re.fullmatch(r'refs/tags/rmx3997-v([1-9][0-9]*)', name)
        if not m:
            die('unexpected tag on the server: ' + name)
        nums.add(int(m.group(1)))
    if not nums or nums != set(range(1, max(nums) + 1)):
        die('rmx3997-v tags on the server are not v1..vN without gaps: %s' % sorted(nums))
    return 'rmx3997-v%d' % (max(nums) + 1)


def sub_once(text, pat, rep, what):
    new, n = re.subn(pat, rep, text, flags=re.M)
    if n != 1:
        die('%s: expected exactly one line matching %r, found %d' % (what, pat, n))
    return new


def save_candidate(stage, cand):
    (stage / 'candidate.json').write_text(json.dumps(cand, indent=2) + '\n')


def cmd_plan_release(a):
    """Next tag, README and release notes commit, annotated tag (all local)."""
    stage = Path(a.stage)
    cand = json.loads((stage / 'candidate.json').read_text())
    if not cand['changed'] or cand.get('release'):
        die('candidate has nothing to release or is already planned')
    ws = stage / 'src'
    if out('status', '--porcelain', cwd=ws):
        die('candidate tree is not clean')
    tag = next_tag(a.repo_url, os.environ.get('TOKEN', ''))
    mk = (ws / 'Makefile').read_text()
    version = '.'.join(re.search(r'^%s = (\d+)$' % k, mk, re.M).group(1)
                       for k in ('VERSION', 'PATCHLEVEL', 'SUBLEVEL'))
    d = git('diff', '--quiet', cand['base'], 'HEAD', '--', 'rmx3997/config/production.config',
            cwd=ws, check=False).returncode
    if d not in (0, 1):
        die('git diff of production.config failed')
    config_changed = d == 1
    m = load(ws)
    readme = (ws / 'README.md').read_text()
    phrases, bullets = [], []
    for r in cand['components']:
        if r['status'] != 'applied':
            continue
        name, old, new = r['name'], r['pin'], r['tip']
        c = m['components'][name]
        phrase = '%s `%s`' % (DISPLAY.get(name, name), new[:8])
        extra = ''
        if name == 'aosp-lts':
            phrase = 'Merge of %s %s' % (DISPLAY[name], r['version'])
            extra = ', now Linux %s' % r['version']
            readme = sub_once(readme, r'^(# .* kernel - Linux )\d+\.\d+\.\d+$',
                              lambda x: x.group(1) + r['version'], 'README title')
            readme = sub_once(readme, r'^(\| Kernel \| Linux )\d+\.\d+\.\d+(, )',
                              lambda x: x.group(1) + r['version'] + x.group(2), 'README status')
        elif name == 'aosp-security':
            phrase = '%s update' % DISPLAY[name]
        elif name == 'susfs':
            sv = re.search(r'^#define SUSFS_VERSION "(v[^"]+)"$',
                           (ws / 'include/linux/susfs.h').read_text(), re.M)
            if not sv:
                die('SUSFS_VERSION not found in include/linux/susfs.h')
            phrase += ' (%s)' % sv.group(1)
            extra = ', now SUSFS %s' % sv.group(1)
            readme = sub_once(readme, r'SUSFS `[0-9a-f]{8}` \(v[^)`\n]+\)',
                              'SUSFS `%s` (%s)' % (new[:8], sv.group(1)), 'README SUSFS pin')
        phrases.append(phrase)
        detail = ('; ' + r['detail']) if r.get('detail') else ''
        bullets.append('- `%s` (`%s`): `%s`..`%s`, %d upstream commit%s%s%s.' % (
            name, c['ref'], old[:8], new[:8], r['count'], '' if r['count'] == 1 else 's',
            extra, detail))
    if not bullets:
        die('no applied component to describe')
    if config_changed:
        phrases.append('config refresh')
        bullets.append('- `production.config` refreshed with `olddefconfig` for the new upstream '
                       'code: only new symbols were added, no existing option changed.')
    summary = 'Upstream update: ' + ', '.join(phrases)
    rows = list(re.finditer(r'^\| `rmx3997-v(\d+)` \|.*\n', readme, re.M))
    if not rows or 'rmx3997-v%d' % (int(rows[-1].group(1)) + 1) != tag:
        die('README History does not end with the release before %s' % tag)
    end = rows[-1].end()
    readme = readme[:end] + '| `%s` | %s | %s |\n' % (tag, version, summary) + readme[end:]
    notes_path = ws / 'rmx3997/ci/release-notes.md'
    text = '\n'.join(bullets).replace('{', '{{').replace('}', '}}')
    notes, n = re.subn(r'(^## Changes in this release\n\n).*?(?=^## )',
                       lambda x: x.group(1) + text + '\n\n', notes_path.read_text(),
                       flags=re.M | re.S)
    if n != 1:
        die('release-notes.md: "## Changes in this release" section not found exactly once')
    notes.format(kernel='k', version='v', commit='c')
    (ws / 'README.md').write_text(readme)
    notes_path.write_text(notes)
    git('add', 'README.md', 'rmx3997/ci/release-notes.md', cwd=ws)
    commit(ws, 'README and release notes: %s upstream update\n\n%s' % (tag, summary))
    git(*IDENT, 'tag', '-a', '-m', '%s\n\n%s\n\nReleased by the weekly upstream job.' % (tag, summary),
        tag, 'HEAD', cwd=ws)
    head = out('rev-parse', 'HEAD', cwd=ws)
    cand['release'] = {'tag': tag, 'commit': head, 'summary': summary}
    save_candidate(stage, cand)
    env = os.environ.get('FORGEJO_ENV') or os.environ.get('GITHUB_ENV')
    if env:
        with open(env, 'a') as f:
            f.write('RMX_TAG=%s\n' % tag)
    print('%s on %s: %s' % (tag, head[:12], summary))


def cmd_promote(a):
    """Fast-forward main and push the tag atomically; bounded retry, ls-remote verified."""
    stage = Path(a.stage)
    cand = json.loads((stage / 'candidate.json').read_text())
    rel = cand.get('release') or die('no planned release')
    tag, base = rel['tag'], cand['base']
    ws = stage / 'src'
    head = out('rev-parse', 'HEAD', cwd=ws)
    if head != rel['commit'] or out('rev-parse', tag + '^{commit}', cwd=ws) != head:
        die('candidate HEAD or tag differs from the planned release commit')
    if not (stage / 'b/acceptance.json').exists() or not (stage / 'b/dist.env').exists():
        die('build, acceptance or packaging did not complete')
    if git('merge-base', '--is-ancestor', base, head, cwd=ws, check=False).returncode:
        die('candidate is not a fast-forward of main')
    tag_obj = out('rev-parse', 'refs/tags/' + tag, cwd=ws)
    token = os.environ.get('TOKEN', '')
    pushes = 0
    while True:
        refs = remote_refs(a.repo_url, token, 'refs/heads/main', 'refs/tags/' + tag)
        main, srv_tag = refs.get('refs/heads/main'), refs.get('refs/tags/' + tag)
        if main == head and srv_tag == tag_obj:
            break
        if main != base:
            die('main moved: server main is %s, the candidate is on %s; nothing pushed by this step'
                % ((main or 'missing')[:12], base[:12]))
        if srv_tag is not None:
            die('%s already exists on the server' % tag)
        if pushes == TRIES:
            die('main and %s not on the server after %d push attempts' % (tag, TRIES))
        if pushes:
            time.sleep(5 * pushes)
        pushes += 1
        r = git(*auth(token), 'push', '-q', '--atomic', '--force-with-lease=refs/heads/main:' + base,
                '--force-with-lease=refs/tags/%s:' % tag, a.repo_url, 'HEAD:refs/heads/main',
                'refs/tags/%s:refs/tags/%s' % (tag, tag), cwd=ws, check=False)
        if r.returncode:
            print('push attempt %d failed: %s' % (pushes, r.stderr.strip()[-300:]), flush=True)
    (stage / 'promote.ok').write_text(head + '\n')
    print('main fast-forwarded %s..%s, %s pushed (verified by ls-remote)' % (base[:12], head[:12], tag))


def outcome(stage):
    b = stage / 'b'
    if not (stage / 'candidate.json').exists():
        return 'FAIL: candidate could not be prepared (see run log)'
    cand = json.loads((stage / 'candidate.json').read_text())
    if not cand['changed']:
        return 'no automatic update applied; nothing was built'
    if not (stage / 'config-refresh.ok').exists():
        return 'FAIL: config refresh (an existing option changed; see run log)'
    if not cand.get('release'):
        return 'FAIL: release planning (next tag, README and release notes; see run log)'
    tag = cand['release']['tag']
    ex = b / 'build-execution.json'
    if not ex.exists():
        return 'FAIL: build did not start (host inputs or config gate)'
    if json.loads(ex.read_text()).get('exit_code') != 0:
        return 'FAIL: build'
    if not (b / 'acceptance.json').exists():
        return 'FAIL: acceptance gates (OEM CRC or struct layout; see run log)'
    if not (b / 'dist.env').exists():
        return 'FAIL: packaging'
    if not (stage / 'promote.ok').exists():
        return 'FAIL: fast-forward of main and push of %s (see run log)' % tag
    if not (stage / 'release.ok').exists():
        return 'FAIL: Forgejo release of %s (main and the tag are pushed; see run log)' % tag
    if not (stage / 'github.ok').exists():
        return 'FAIL: GitHub release copy of %s (the Forgejo release is published)' % tag
    return 'PASS: built, all acceptance gates passed, released %s' % tag


def cmd_report(a):
    stage = Path(a.stage)
    token = os.environ['TOKEN']
    res = outcome(stage)
    lines = ['Upstream check %s, run %s' % (datetime.date.today().isoformat(), a.run_url), '']
    cand = json.loads((stage / 'candidate.json').read_text()) if (stage / 'candidate.json').exists() else None
    rows = cand['components'] if cand else json.loads((stage / 'check.json').read_text())
    lines += ['| Component | Pinned | Upstream | Result |', '| --- | --- | --- | --- |']
    for r in rows:
        st = r.get('status', 'new' if r.get('new') else 'current')
        detail = (' - ' + r['detail']) if r.get('detail') else ''
        lines.append('| %s | `%s` | `%s` | %s%s |' % (r['name'], r['pin'][:12], r['tip'][:12], st, detail))
    lines += ['', '**Result:** ' + res]
    rel = cand.get('release') if cand else None
    if res.startswith('PASS'):
        lines.append('Released `%s`: %s/releases/tag/%s (main fast-forwarded `%s`..`%s`).' % (
            rel['tag'], re.sub(r'\.git$', '', a.repo_url), rel['tag'], cand['base'][:12],
            rel['commit'][:12]))
    elif not (stage / 'promote.ok').exists():
        lines.append('Nothing was pushed; main and the tags are unchanged.')
    if cand:
        for c in rows:
            if c.get('commits'):
                lines += ['', '<details><summary>%s commits</summary>' % c['name'], ''] + c['commits'] + ['', '</details>']
    body = '\n'.join(lines)
    print(body)
    apiurl, repo = a.api.rstrip('/'), a.repo
    st, issues = api('GET', '%s/repos/%s/issues?state=open&type=issues&limit=50' % (apiurl, repo), token)
    if st != 200:
        die('listing issues returned HTTP %d' % st)
    mine = [i for i in issues if i['title'] == ISSUE_TITLE]
    if mine:
        st, _ = api('POST', '%s/repos/%s/issues/%d/comments' % (apiurl, repo, mine[0]['number']), token, {'body': body})
    else:
        st, _ = api('POST', '%s/repos/%s/issues' % (apiurl, repo), token, {'title': ISSUE_TITLE, 'body': body})
    if st != 201:
        die('posting the report returned HTTP %d' % st)
    print('report posted')
    if res.startswith('FAIL'):
        raise SystemExit(1)
    manual = [r['name'] for r in rows if r.get('status') in ('conflict', 'manual')]
    if manual:
        die('needs a manual port: ' + ', '.join(manual))


# ------------------------------------------------------------------ verify
def cmd_verify(a):
    m = load()
    bad = 0
    for name, c in m['components'].items():
        if c['mode'] != 'subtree':
            continue
        d = cache(name, c['url'], [c['ref']])
        for up, local in c['paths'].items():
            entries = [l.split(None, 3) for l in out('-C', str(d), 'ls-tree', '-r', c['pin'], '--', up or '.').splitlines()]
            files = [e[3] for e in entries if e[0] != '120000' and
                     (not c.get('files') or any(e[3].startswith(f) for f in c['files']))]
            for p in files:
                lp = local + p[len(up):]
                want = out('-C', str(d), 'rev-parse', '%s:%s' % (c['pin'], p))
                have = out('hash-object', str(REPO / lp)) if (REPO / lp).exists() else 'missing'
                if have != want and lp not in c.get('local_modified', []):
                    bad += 1
                    print('%s: %s differs from %s@%s' % (name, lp, p, c['pin'][:12]))
        print('%s: pin %s verified' % (name, c['pin'][:12]))
    if bad:
        die('%d vendored files differ from their pins' % bad)


class _Scrub:
    """Keep host paths out of the public job log (tracebacks included)."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, text):
        for old, new in ((str(REPO), '.'), (os.path.expanduser('~'), '~')):
            text = text.replace(old, new)
        return self._stream.write(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('check')
    c.add_argument('--stage', required=True)
    c = sub.add_parser('candidate')
    for f in ('--stage', '--repo-url', '--expect-main'):
        c.add_argument(f, required=True)
    c = sub.add_parser('refresh-commit')
    c.add_argument('--src', required=True)
    for name in ('plan-release', 'promote'):
        c = sub.add_parser(name)
        for f in ('--stage', '--repo-url'):
            c.add_argument(f, required=True)
    c = sub.add_parser('report')
    for f in ('--stage', '--api', '--repo', '--repo-url', '--run-url'):
        c.add_argument(f, required=True)
    sub.add_parser('verify')
    a = p.parse_args()
    {'check': cmd_check, 'candidate': cmd_candidate, 'refresh-commit': cmd_refresh_commit,
     'plan-release': cmd_plan_release, 'promote': cmd_promote, 'report': cmd_report,
     'verify': cmd_verify}[a.cmd](a)


if __name__ == '__main__':
    sys.stdout, sys.stderr = _Scrub(sys.stdout), _Scrub(sys.stderr)
    main()
