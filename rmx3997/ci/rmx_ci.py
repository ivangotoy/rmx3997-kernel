#!/usr/bin/env python3
"""RMX3997 CI gates: host-input pins, config, acceptance, packaging, release,
GitHub release copy.

Every gate fails closed. Host-local inputs (toolchains, the stock OEM module
corpus and the boot_b layout template) never enter the repository; they are
identified by the SHA-256 pins in host-inputs.json and verified before use.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPO = Path(__file__).resolve().parents[2]
CI = REPO / 'rmx3997/ci'
PINS = CI / 'host-inputs.json'
PART_SIZE = 67108864
PAGE = 4096


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def expand(p):
    return Path(os.path.expanduser(p))


def die(msg):
    print('FAIL: ' + msg, flush=True)
    raise SystemExit(1)


def host_markers():
    home = os.path.expanduser('~').encode()
    # Paths of this build host only. Third-party binaries legitimately carry
    # their own upstream build paths (e.g. /home/runner/.cargo in avbroot).
    return sorted({home + b'/', b'forgejo-runners', REPO.as_posix().encode()})


def write_atomic(path, text):
    """Replace path with text in one rename: an interrupted write leaves the
    old file intact and no partial or temporary file behind."""
    path = Path(path)
    tmp = path.with_name('.%s.%d.tmp' % (path.name, os.getpid()))
    try:
        with open(tmp, 'x') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o7777)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def load_pins():
    return json.loads(PINS.read_text())


def oem_manifest(dirs):
    """Sorted (relative path, sha256) list over every .ko in the OEM corpus."""
    rows = []
    for d in dirs:
        root = expand(d)
        if not root.is_dir():
            die('OEM module directory missing: ' + d)
        for ko in sorted(root.rglob('*.ko')):
            rows.append([d + '/' + str(ko.relative_to(root)), sha(ko)])
    return rows


def manifest_digest(rows):
    return hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()


# ---------------------------------------------------------------- preflight
def cmd_preflight(a):
    pins = load_pins()
    bad = []
    for name, entry in pins['files'].items():
        p = expand(entry['path'])
        if not p.is_file():
            bad.append(name + ': missing')
        elif sha(p.resolve()) != entry['sha256']:
            bad.append(name + ': sha256 differs')
    oem = pins['oem_modules']
    rows = oem_manifest(oem['dirs'])
    if len(rows) != oem['count'] or manifest_digest(rows) != oem['manifest_sha256']:
        bad.append('oem_modules: corpus differs (%d files)' % len(rows))
    import shutil
    if not shutil.which('bpftool'):
        bad.append('bpftool: not installed (struct layout gate)')
    for tool in ('avbtool', 'lz4'):
        if not shutil.which(tool):
            bad.append(tool + ': not installed (boot image packaging)')
    if bad:
        die('host inputs: ' + '; '.join(bad))
    print('host inputs: %d pinned files and %d OEM modules verified' % (len(pins['files']), len(rows)))


def cmd_record_pins(a):
    """Maintainer helper: rewrite the sha256 values from the current host."""
    pins = load_pins()
    for entry in pins['files'].values():
        entry['sha256'] = sha(expand(entry['path']).resolve())
    rows = oem_manifest(pins['oem_modules']['dirs'])
    pins['oem_modules'].update(count=len(rows), manifest_sha256=manifest_digest(rows))
    write_atomic(PINS, json.dumps(pins, indent=2) + '\n')
    print(json.dumps(pins, indent=2))


# ------------------------------------------------------------------- config
def cmd_config(a):
    want = (REPO / 'rmx3997/config/production.config').read_bytes()
    got = (Path(a.out) / '.config').read_bytes()
    if got != want:
        die('olddefconfig output differs from rmx3997/config/production.config')
    print('config: olddefconfig output equals production.config (%s)' % hashlib.sha256(got).hexdigest())


# --------------------------------------------------------------- acceptance
def read_versions(ko):
    from elftools.elf.elffile import ELFFile
    with open(ko, 'rb') as f:
        elf = ELFFile(f)
        sec = elf.get_section_by_name('__versions')
        imports = {}
        if sec is not None:
            data = sec.data()
            for off in range(0, len(data), 64):
                crc = struct.unpack_from('<Q', data, off)[0] & 0xffffffff
                name = data[off + 8:off + 64].split(b'\0', 1)[0].decode()
                imports[name] = crc
        exports = set()
        symtab = elf.get_section_by_name('.symtab')
        if symtab is not None:
            for s in symtab.iter_symbols():
                if s.name.startswith('__ksymtab_'):
                    exports.add(s.name[len('__ksymtab_'):])
    return imports, exports


def oem_crc_gate(out, pins):
    symvers = {}
    for line in (out / 'Module.symvers').read_text().splitlines():
        crc, name, module = line.split('\t')[:3]
        symvers[name] = (int(crc, 16), module)
    files = []
    for d in pins['oem_modules']['dirs']:
        files += sorted(expand(d).rglob('*.ko'))
    parsed = {ko: read_versions(ko) for ko in files}
    oem_exports = set().union(*(e for _, e in parsed.values()))
    mismatched, unresolved, checked = [], [], 0
    for ko, (imports, _) in parsed.items():
        for name, crc in imports.items():
            checked += 1
            if name in symvers and symvers[name][1] == 'vmlinux':
                if symvers[name][0] != crc:
                    mismatched.append([ko.name, name])
            elif name in oem_exports:
                continue
            elif name in symvers:
                if symvers[name][0] != crc:
                    mismatched.append([ko.name, name])
            else:
                unresolved.append([ko.name, name])
    known = sorted(map(list, {tuple(x) for x in pins['oem_modules']['known_unresolved']}))
    unresolved = sorted(map(list, {tuple(x) for x in unresolved}))
    return {
        'files': len(files),
        'unique_modules': len({k.name for k in files}),
        'imports_checked': checked,
        'crc_mismatches': sorted(mismatched),
        'unresolved': unresolved,
        'unresolved_expected': known,
        'status': 'PASS' if not mismatched and unresolved == known else 'FAIL',
    }


def load_packager():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'pack', REPO / 'rmx3997/development/package-oem-candidate.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def cmd_accept(a):
    stage = Path(a.stage)
    out = stage / 'out'
    pins = load_pins()
    result = {'stage_schema': 1}
    identity = load_packager().inspect(stage)  # raises on any contract break
    result['identity'] = identity
    config = (out / '.config').read_text().splitlines()
    for line in pins['required_config']:
        if line not in config:
            die('required config line missing: ' + line)
    for line in pins['forbidden_config']:
        if line in config:
            die('forbidden config line present: ' + line)
    result['config_invariants'] = 'PASS'
    image = (out / 'arch/arm64/boot/Image').read_bytes()
    leaks = {m.decode(): image.count(m) for m in host_markers() if image.count(m)}
    if leaks:
        die('Image contains host paths: %r' % leaks)
    result['host_paths_in_Image'] = 0
    symbols = set()
    for line in (out / 'System.map').read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3:
            symbols.add(parts[2])
    missing = [s for s in pins['required_symbols'] if s not in symbols]
    if missing:
        die('required symbols missing from System.map: ' + ', '.join(missing))
    result['required_symbols'] = 'PASS (%d)' % len(pins['required_symbols'])
    gate = oem_crc_gate(out, pins)
    result['oem_crc'] = gate
    print(json.dumps({k: v for k, v in gate.items() if k not in ('crc_mismatches',)}, indent=2))
    if gate['status'] != 'PASS':
        print('CRC mismatches:', json.dumps(gate['crc_mismatches'][:50]))
        die('OEM module CRC gate')
    lay = layout_gate(out / 'arch/arm64/boot/Image', stage / 'tmp', pins)
    result['struct_layout'] = lay
    print(json.dumps({k: v for k, v in lay.items() if k != 'failures'}, indent=2))
    if lay['status'] != 'PASS':
        print('\n'.join(lay['failures'][:40]))
        die('struct layout gate')
    (stage / 'acceptance.json').write_text(json.dumps(result, indent=2) + '\n')
    print('acceptance: PASS (%s)' % identity['release'])


# ------------------------------------------------------------- struct layout
# Every named struct/union of the stock kernel's BTF is compared, member by
# member (anonymous unions/structs flattened), with the built kernel. A
# difference passes only if the exact layout is recorded in
# layout-approved.json, which holds the layouts of the phone-proven kernel.
# CRC checks cannot see a change that genksyms hides (__GENKSYMS__, KABI
# reserve reuse); this gate can.
LAYOUT_APPROVED = CI / 'layout-approved.json'
GUARD_SLOTS = ['android_kabi_reserved%d' % i for i in range(4, 9)]
_SKIP = ('TYPEDEF', 'CONST', 'VOLATILE', 'RESTRICT', 'TYPE_TAG')


def btf_from_image(data):
    """Return the .BTF blob embedded in an arm64 kernel Image."""
    i = 0
    while True:
        i = data.find(b'\x9f\xeb\x01\x00\x18\x00\x00\x00', i)
        if i < 0:
            die('no BTF found in kernel Image')
        _m, _v, _f, hl, to, tl, so, sl = struct.unpack_from('<HBBIIIII', data, i)
        if to == 0 and so == tl and sl > 1000000 and hl + so + sl <= len(data) - i:
            return data[i:i + hl + so + sl]
        i += 1


def btf_layouts(path):
    raw = subprocess.run(['bpftool', '-j', 'btf', 'dump', 'file', str(path), 'format', 'raw'],
                         capture_output=True, check=True).stdout
    ts = json.loads(raw)['types']
    ids = {t['id']: t for t in ts}
    ids[0] = {'kind': 'VOID', 'name': 'void'}

    def tname(i, depth=0):
        t = ids[i]
        k = t['kind']
        if k in _SKIP:
            return tname(t['type_id'], depth)
        if k == 'PTR':
            return '*' if depth > 2 else tname(t['type_id'], depth + 1) + '*'
        if k == 'ARRAY':
            return '%s[%d]' % (tname(t['type_id'], depth), t['nr_elems'])
        if k in ('STRUCT', 'FWD'):
            return 'struct ' + t['name']
        if k == 'UNION':
            return 'union ' + t['name']
        if k in ('ENUM', 'ENUM64'):
            return 'enum ' + t['name']
        return 'fn' if k == 'FUNC_PROTO' else t.get('name', k)

    def size(i):
        t = ids[i]
        while t['kind'] in _SKIP:
            t = ids[t['type_id']]
        if t['kind'] == 'ARRAY':
            return size(t['type_id']) * t['nr_elems']
        return 8 if t['kind'] == 'PTR' else t.get('size', 0)

    def flat(t, base=0):
        res = []
        for m in t.get('members', []):
            off = base + m['bits_offset']
            tgt = ids[m['type_id']]
            while tgt['kind'] in _SKIP:
                tgt = ids[tgt['type_id']]
            if m['name'] == '(anon)' and tgt['kind'] in ('STRUCT', 'UNION'):
                res += flat(tgt, off)
            else:
                bits = m.get('bitfield_size', 0)
                res.append([m['name'], off, bits, 0 if bits else size(m['type_id']), tname(m['type_id'])])
        return res

    lay = {}
    for t in ts:
        if t['kind'] in ('STRUCT', 'UNION') and t['name'] != '(anon)':
            lay.setdefault(t['name'], []).append({'size': t['size'], 'members': flat(t)})
    return {k: sorted(v, key=lambda x: json.dumps(x)) for k, v in lay.items()}


def layout_digest(variants):
    return hashlib.sha256(json.dumps(variants, separators=(',', ':')).encode()).hexdigest()


def member_changes(old, new):
    a = {m[0]: m for v in old for m in v['members']}
    b = {m[0]: m for v in new for m in v['members']}
    rows = []
    for n in sorted(a.keys() | b.keys(), key=lambda n: (b.get(n) or a.get(n))[1]):
        if a.get(n) != b.get(n):
            fmt = lambda m: 'absent' if m is None else '@%d+%s %s' % (
                m[1] // 8, ('%db' % m[2]) if m[2] else m[3], m[4])
            rows.append('%s: %s -> %s' % (n, fmt(a.get(n)), fmt(b.get(n))))
    return rows


def guard_slot_overlaps(variants):
    """Members sharing bytes with the KABI slots the OEM security guard writes."""
    hits = []
    for v in variants:
        ms = v['members']
        for slot in (m for m in ms if m[0] in GUARD_SLOTS):
            s, e = slot[1], slot[1] + 64
            for m in ms:
                ms_, me = m[1], m[1] + (m[2] or m[3] * 8)
                if m[0] != slot[0] and ms_ < e and me > s:
                    hits.append('%s overlaps %s' % (m[0], slot[0]))
    return sorted(set(hits))


def built_btf(image, work):
    p = Path(work) / 'kernel.btf'
    p.write_bytes(btf_from_image(Path(image).read_bytes()))
    return p


def layout_gate(image, work, pins):
    stock = btf_layouts(expand(pins['files']['stock_btf']['path']))
    built = btf_layouts(built_btf(image, work))
    approved = json.loads(LAYOUT_APPROVED.read_text())
    fails = []
    overlaps = guard_slot_overlaps(built.get('task_struct', []))
    if overlaps or not built.get('task_struct'):
        fails.append('task_struct: ' + ('; '.join(overlaps) or 'missing'))
    same = changed = 0
    for name in sorted(stock):
        if name not in built:
            if name not in approved['removed']:
                fails.append('%s: present in the stock kernel, missing here' % name)
            continue
        if built[name] == stock[name]:
            same += 1
            continue
        changed += 1
        if approved['changed'].get(name, {}).get('sha256') != layout_digest(built[name]):
            fails.append('%s: unapproved layout change: %s' % (
                name, '; '.join(member_changes(stock[name], built[name])[:12]) or 'variant set differs'))
    return {'stock_structs': len(stock), 'identical': same, 'approved_changes': changed - len(
        [f for f in fails if 'unapproved' in f]), 'guard_slot_overlaps': overlaps,
        'failures': fails, 'status': 'PASS' if not fails else 'FAIL'}


def cmd_layout(a):
    pins = load_pins()
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    if a.approve:
        stock = btf_layouts(expand(pins['files']['stock_btf']['path']))
        built = btf_layouts(built_btf(a.image, work))
        rec = {'description': 'Struct layouts of the phone-proven kernel that differ from the stock '
                              'RMX3997 kernel. Regenerate only from a kernel that booted on the phone: '
                              'rmx_ci.py layout --approve --image <Image>.',
               'approved_from': a.approve, 'changed': {}, 'removed': sorted(set(stock) - set(built))}
        for name in sorted(stock.keys() & built.keys()):
            if stock[name] != built[name]:
                rec['changed'][name] = {'sha256': layout_digest(built[name]),
                                        'members': member_changes(stock[name], built[name])[:40]}
        write_atomic(LAYOUT_APPROVED, json.dumps(rec, indent=1) + '\n')
        print('approved %d changed and %d removed structs from %s' % (
            len(rec['changed']), len(rec['removed']), a.approve))
        return
    g = layout_gate(a.image, work, pins)
    print(json.dumps(g, indent=1))
    if g['status'] != 'PASS':
        die('struct layout gate')
    print('layout: PASS')


# ------------------------------------------------------------ config refresh
def cmd_refresh_config(a):
    """Accept olddefconfig output when it only adds new symbols (upstream update)."""
    path = REPO / 'rmx3997/config/production.config'
    old = path.read_text().splitlines()
    new = (Path(a.out) / '.config').read_text().splitlines()
    sym = lambda l: (re.match(r'(?:# )?(CONFIG_[A-Za-z0-9_]+)[= ]', l) or [None, None])[1]
    oldmap = {sym(l): l for l in old if sym(l)}
    newmap = {sym(l): l for l in new if sym(l)}
    changed = sorted(s for s in oldmap if oldmap[s] != newmap.get(s))
    if changed:
        die('olddefconfig changes existing options: ' + '; '.join(
            '%s -> %s' % (oldmap[s], newmap.get(s, 'removed')) for s in changed[:20]))
    added = sorted(set(newmap) - set(oldmap))
    write_atomic(path, '\n'.join(new) + '\n')
    print('config: %d new symbols accepted: %s' % (len(added), ', '.join(added) or 'none'))


# --------------------------------------------------------------- boot image
def avb_field(pattern, info, what):
    """One avbtool info_image field; a missing field fails the gate cleanly."""
    m = re.search(pattern, info)
    if not m:
        die('avbtool info_image output has no %s' % what)
    return m.group(1)


def avb_info(path):
    return subprocess.run(['avbtool', 'info_image', '--image', str(path)],
                          capture_output=True, text=True, check=True).stdout


def build_boot_image(template, image, out_img, work):
    b = Path(template).read_bytes()
    if len(b) != PART_SIZE or b[:8] != b'ANDROID!':
        die('boot template is not a 64 MiB Android boot image')
    ks, rs, _osv, hs = struct.unpack_from('<IIII', b, 8)
    hv = struct.unpack_from('<I', b, 40)[0]
    sig = struct.unpack_from('<I', b, 1580)[0]
    if (hv, rs, hs) != (4, 0, 1584):
        die('unexpected boot header layout %r' % ((hv, rs, hs),))
    pad = lambda n: (n + PAGE - 1) // PAGE * PAGE
    info = avb_info(template)
    orig = int(avb_field(r'Original image size:\s+(\d+)', info, 'original image size'))
    if orig != PAGE + pad(ks) + pad(rs) + pad(sig):
        die('template AVB original size does not match its header')
    if not (re.search(r'Algorithm:\s+NONE', info) and re.search(r'Partition Name:\s+boot\b', info)):
        die('template AVB descriptor is not boot/NONE')
    salt = avb_field(r'Salt:\s+([0-9a-f]+)', info, 'salt')
    props = re.findall(r"Prop: (\S+) -> '([^']*)'", info)
    sigblob = b[PAGE + pad(ks) + pad(rs):PAGE + pad(ks) + pad(rs) + sig]
    lz = work / 'Image.lz4'
    subprocess.run(['lz4', '-f', '-l', '-12', '-q', str(image), str(lz)], check=True)
    k = lz.read_bytes()
    hdr = bytearray(b[:PAGE])
    struct.pack_into('<I', hdr, 8, len(k))
    payload = bytes(hdr) + k + b'\0' * (pad(len(k)) - len(k)) + sigblob + b'\0' * (pad(sig) - sig)
    raw = work / 'payload.img'
    raw.write_bytes(payload)
    cmd = ['avbtool', 'add_hash_footer', '--image', str(raw), '--partition_size', str(PART_SIZE),
           '--partition_name', 'boot', '--algorithm', 'NONE', '--salt', salt]
    for key, value in props:
        cmd += ['--prop', '%s:%s' % (key, value)]
    subprocess.run(cmd, check=True)
    os.replace(raw, out_img)
    return {'kernel_lz4_bytes': len(k), 'payload_bytes': len(payload), 'salt': salt,
            'props': [k_ for k_, _ in props]}


def verify_boot_image(img, image, work):
    data = Path(img).read_bytes()
    if len(data) != PART_SIZE or data[:8] != b'ANDROID!':
        die('boot image size/magic')
    info = avb_info(img)
    orig = int(avb_field(r'Original image size:\s+(\d+)', info, 'original image size'))
    salt = bytes.fromhex(avb_field(r'Salt:\s+([0-9a-f]+)', info, 'salt'))
    digest = avb_field(r'Digest:\s+([0-9a-f]+)', info, 'digest')
    if hashlib.sha256(salt + data[:orig]).hexdigest() != digest:
        die('AVB hash descriptor digest does not cover the payload')
    ks = struct.unpack_from('<I', data, 8)[0]
    lz = work / 'verify.lz4'
    lz.write_bytes(data[PAGE:PAGE + ks])
    dec = subprocess.run(['lz4', '-dc', str(lz)], capture_output=True, check=True).stdout
    if hashlib.sha256(dec).hexdigest() != sha(image):
        die('kernel inside boot image differs from built Image')
    return {'avb_digest_verified': True, 'kernel_matches_Image': True, 'avb_original_size': orig}


# ---------------------------------------------------------------- packaging
def cmd_package(a):
    stage = Path(a.stage)
    out = stage / 'out'
    dist = stage / 'dist'
    work = stage / 'work'
    dist.mkdir()
    work.mkdir(exist_ok=True)
    pins = load_pins()
    acc = json.loads((stage / 'acceptance.json').read_text())
    m = load_packager()
    identity = m.inspect(stage)
    if identity != acc['identity']:
        die('Image changed after acceptance')
    image = out / 'arch/arm64/boot/Image'
    base = 'RMX3997-kernel-%s-%s' % (identity['release'].split('-')[0], short_label(a.label))
    zip_path = dist / (base + '.zip')
    ident = dict(identity, build_purpose='forgejo-ci', source_commit=a.commit,
                 ci_run=a.run_url, oem_crc_gate=acc['oem_crc']['status'])
    m.package(image, zip_path, ident)
    private = expand(a.private_dir) / base
    private.mkdir(parents=True, exist_ok=True)
    img_path = private / (base + '-boot_b.img')
    template = expand(pins['files']['boot_b_layout_template']['path'])
    built = build_boot_image(template, image, img_path, work)
    checked = verify_boot_image(img_path, image, work)
    (private / (img_path.name + '.sha256')).write_text(sha(img_path) + '  ' + img_path.name + '\n')
    (dist / (zip_path.name + '.sha256')).write_text(sha(zip_path) + '  ' + zip_path.name + '\n')
    with zipfile.ZipFile(zip_path) as z:
        zleaks = sorted(n for n in z.namelist() if any(m in z.read(n) for m in host_markers()))
    if zleaks:
        die('ZIP members contain host paths: %s' % ', '.join(zleaks))
    tools = {}
    for line in (stage / 'toolchain.txt').read_text().splitlines():
        if ': ' in line:
            key, value = line.split(': ', 1)
            tools[key] = value
    prov = {
        'source_commit': a.commit,
        'ci_run': a.run_url,
        'release': identity['release'],
        'Image_sha256': identity['Image_sha256'],
        'vmlinux_sha256': identity['vmlinux_sha256'],
        'config_sha256': identity['config_sha256'],
        'zip': {'name': zip_path.name, 'sha256': sha(zip_path), 'size': zip_path.stat().st_size},
        'boot_b_image': {'name': img_path.name, 'sha256': sha(img_path), 'size': PART_SIZE,
                         **built, **checked},
        'toolchain': tools,
        'host_input_pins_sha256': sha(PINS),
        'acceptance': acc,
        'phone_boot': 'UNVERIFIED (CI cannot boot the phone)',
    }
    (private / (base + '.provenance.json')).write_text(json.dumps(prov, indent=2) + '\n')
    with open(stage / 'dist.env', 'w') as f:
        f.write('RMX_DIST=%s\nRMX_BASE=%s\n' % (dist, base))
    for p in sorted(dist.iterdir()):
        print('%s  %s  %d' % (sha(p), p.name, p.stat().st_size))
    allowed = {zip_path.name, zip_path.name + '.sha256'}
    if {p.name for p in dist.iterdir()} != allowed:
        die('dist must contain only the ZIP and its checksum')
    print('host-only (not uploaded): %s' % img_path.name)


# ------------------------------------------------------------------ release
TRIES = 6


def open_url(req):
    """urlopen with bounded retry on HTTP 429 (Forgejo rate-limits bursts).
    A 429 is returned before the request is processed, so a POST is safe to repeat."""
    for attempt in range(1, TRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == TRIES:
                return e.code, e.read()
            try:
                wait = max(0, min(int(e.headers.get('Retry-After')), 300))
            except (TypeError, ValueError):
                wait = 10 * attempt
            print('HTTP 429 from %s, retrying in %d s' % (req.full_url.split('?', 1)[0], wait),
                  flush=True)
            time.sleep(wait)


def api(method, url, token, data=None, ctype='application/json'):
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Authorization', 'token ' + token)
    if data is not None:
        req.add_header('Content-Type', ctype)
    return open_url(req)


def short_label(label):
    """rmx3997-v10 -> v10: the file name already starts with the device."""
    return label[len('rmx3997-'):] if label.startswith('rmx3997-') else label


def release_body(tag, commit, dist):
    zips = [p.name for p in dist.iterdir() if p.name.endswith('-%s.zip' % short_label(tag))]
    if len(zips) != 1:
        die('expected one release ZIP in dist')
    kernel = json.loads((dist.parent / 'acceptance.json').read_text())['identity']['release']
    text = (REPO / 'rmx3997/ci/release-notes.md').read_text()
    return text.format(kernel=kernel, version=kernel.split('-')[0], commit=commit[:12])


def cmd_release(a):
    token = os.environ.get('RELEASE_TOKEN', '')
    if not token:
        die('no release token in step environment')
    base = '%s/repos/%s' % (a.api.rstrip('/'), a.repo)
    tag = a.tag
    st, body = api('GET', '%s/releases/tags/%s' % (base, urllib.parse.quote(tag)), token)
    if st == 200:
        die('a release for %s already exists; refusing to modify it' % tag)
    if st != 404:
        die('release lookup returned HTTP %d' % st)
    payload = {'tag_name': tag, 'target_commitish': a.commit, 'name': tag, 'draft': True,
               'prerelease': False,
               'body': release_body(tag, a.commit, Path(a.dist))}
    st, body = api('POST', base + '/releases', token, json.dumps(payload).encode())
    if st not in (200, 201):
        die('draft release creation returned HTTP %d: %s' % (st, body[:300]))
    rel = json.loads(body)
    dist = Path(a.dist)
    uploaded = []
    for p in sorted(dist.iterdir()):
        url = '%s/releases/%d/assets?name=%s' % (base, rel['id'], urllib.parse.quote(p.name))
        st, body = api('POST', url, token, p.read_bytes(), 'application/octet-stream')
        if st not in (200, 201):
            die('asset upload %s returned HTTP %d' % (p.name, st))
        asset = json.loads(body)
        # The job token cannot download draft-release files (web route, 404),
        # so verify the stored size through the API here. Byte-level checks
        # are done by the owner before publishing (sha256 files are attached).
        st, body = api('GET', '%s/releases/%d/assets/%d' % (base, rel['id'], asset['id']), token)
        if st != 200 or json.loads(body).get('size') != p.stat().st_size:
            die('asset %s: stored size does not match (HTTP %d)' % (p.name, st))
        uploaded.append(p.name)
    st, body = api('GET', '%s/releases/%d/assets' % (base, rel['id']), token)
    names = sorted(a['name'] for a in json.loads(body)) if st == 200 else []
    if names != sorted(uploaded):
        die('release asset list differs from uploaded files')
    # All gates passed and the assets are complete: publish.
    st, body = api('PATCH', '%s/releases/%d' % (base, rel['id']), token,
                   json.dumps({'draft': False}).encode())
    if st != 200 or json.loads(body).get('draft'):
        die('publishing release returned HTTP %d' % st)
    for p in sorted(dist.iterdir()):
        url = '%s/%s/releases/download/%s/%s' % (a.api.rstrip('/').rsplit('/api/', 1)[0], a.repo,
                                                urllib.parse.quote(tag), urllib.parse.quote(p.name))
        st, data = api('GET', url, token)
        if st != 200 or hashlib.sha256(data).hexdigest() != sha(p):
            die('published asset %s did not round-trip (HTTP %d)' % (p.name, st))
    print('published release %s (id %d), %d assets byte-verified: %s'
          % (tag, rel['id'], len(uploaded), ', '.join(uploaded)))


# ------------------------------------------------------------ GitHub copy
# The GitHub mirror receives git refs from the Forgejo push mirror; this copies
# the published Forgejo release (ZIP and checksum, the same bytes) on top of
# the mirrored tag. It never creates or moves a tag, never edits an existing
# release and never deletes anything.
GH_API = 'https://api.github.com'


def fetch(url):
    """Anonymous GET (redirects followed); no credential can leave the host."""
    req = urllib.request.Request(url, headers={'User-Agent': 'rmx3997-ci'})
    try:
        return open_url(req)
    except urllib.error.URLError as e:
        die('GET %s failed: %s' % (url.split('?', 1)[0], e.reason))


def gh(method, url, token, payload=None, raw=None, ctype='application/json'):
    data = raw if raw is not None else (None if payload is None else json.dumps(payload).encode())
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('User-Agent', 'rmx3997-ci')
    req.add_header('Accept', 'application/vnd.github+json')
    req.add_header('X-GitHub-Api-Version', '2022-11-28')
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    if data is not None:
        req.add_header('Content-Type', ctype)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError as e:
        die('%s %s failed: %s' % (method, url.split('?', 1)[0], e.reason))


def gh_json(method, url, token, want=(200,), what='GitHub request', **kw):
    st, body = gh(method, url, token, **kw)
    if st not in want:
        die('%s returned HTTP %d' % (what, st))
    return json.loads(body)


def gh_peeled(base, tag, token):
    """Peeled commit of refs/tags/<tag> on GitHub, or None if the tag is absent."""
    st, body = gh('GET', '%s/git/ref/tags/%s' % (base, urllib.parse.quote(tag)), token)
    if st == 404:
        return None
    if st != 200:
        die('GitHub tag lookup returned HTTP %d' % st)
    ref = json.loads(body)
    if not isinstance(ref, dict) or ref.get('ref') != 'refs/tags/' + tag:
        die('GitHub tag lookup did not return exactly refs/tags/%s' % tag)
    obj = ref['object']
    for _ in range(8):
        if obj['type'] == 'commit':
            return obj['sha']
        if obj['type'] != 'tag':
            die('GitHub tag %s points to a %s' % (tag, obj['type']))
        obj = gh_json('GET', '%s/git/tags/%s' % (base, obj['sha']), token,
                      what='GitHub tag object lookup')['object']
    die('GitHub tag %s: tag chain too deep' % tag)


def gh_releases_for(base, tag, token):
    """Every GitHub release (drafts included when authenticated) for the tag."""
    found, page = [], 1
    while True:
        rows = gh_json('GET', '%s/releases?per_page=100&page=%d' % (base, page), token,
                       what='GitHub release list')
        found += [r for r in rows if r.get('tag_name') == tag]
        if len(rows) < 100:
            return found
        page += 1


def cmd_github_release(a):
    import time
    token = os.environ.get('GH_RELEASE_TOKEN', '')
    if not token and not a.dry_run:
        die('no GitHub release token in step environment')
    tag = a.tag
    if not re.fullmatch(r'rmx3997-[A-Za-z0-9._-]+', tag):
        die('unexpected tag name')
    fapi = a.forgejo_api.rstrip('/')
    fbase = '%s/repos/%s' % (fapi, a.repo)
    gbase = '%s/repos/%s' % (GH_API, a.github_repo)

    # Forgejo release, read anonymously: exactly the ZIP and its checksum.
    st, body = fetch('%s/releases/tags/%s' % (fbase, urllib.parse.quote(tag)))
    if st != 200:
        die('Forgejo release lookup returned HTTP %d' % st)
    frel = json.loads(body)
    if frel.get('draft') or frel.get('tag_name') != tag:
        die('Forgejo release for %s is not a published release of that tag' % tag)
    assets = {x['name']: x for x in frel.get('assets', [])}
    zips = [n for n in assets if re.fullmatch(r'RMX3997-.+-%s\.zip' % re.escape(short_label(tag)), n)]
    if len(zips) != 1 or set(assets) != {zips[0], zips[0] + '.sha256'}:
        die('Forgejo release must hold exactly the ZIP and its .sha256 (has: %s)'
            % ', '.join(sorted(assets)))
    zname = zips[0]
    files = {}
    for name in sorted(assets):
        st, data = fetch(assets[name]['browser_download_url'])
        if st != 200 or len(data) != assets[name]['size']:
            die('Forgejo asset %s download failed (HTTP %d)' % (name, st))
        files[name] = data
    zsum = hashlib.sha256(files[zname]).hexdigest()
    if files[zname + '.sha256'] != ('%s  %s\n' % (zsum, zname)).encode():
        die('Forgejo %s.sha256 does not match the ZIP' % zname)
    sums = {n: hashlib.sha256(d).hexdigest() for n, d in files.items()}
    st, body = fetch('%s/releases/latest' % fbase)
    if st != 200:
        die('Forgejo latest release lookup returned HTTP %d' % st)
    latest = json.loads(body).get('tag_name') == tag

    # The mirrored tag must exist on GitHub and peel to the Forgejo commit.
    st, body = fetch('%s/tags/%s' % (fbase, urllib.parse.quote(tag)))
    if st != 200:
        die('Forgejo tag lookup returned HTTP %d' % st)
    commit = json.loads(body)['commit']['sha']
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        die('Forgejo tag %s has no commit' % tag)
    deadline = time.monotonic() + a.wait_tag
    while True:
        peeled = gh_peeled(gbase, tag, token)
        if peeled is not None and peeled != commit:
            die('GitHub tag %s is at %s, Forgejo tag is at %s' % (tag, peeled[:12], commit[:12]))
        if peeled == commit:
            break
        if time.monotonic() >= deadline:
            die('GitHub tag %s did not appear within %d s' % (tag, a.wait_tag))
        time.sleep(15)
    print('%s: Forgejo pair verified (%s), GitHub tag peels to %s'
          % (tag, zname, commit[:12]), flush=True)

    def check_published(rel, names):
        for x in rel['assets']:
            st, data = fetch(x['browser_download_url'])
            if st != 200 or hashlib.sha256(data).hexdigest() != sums[x['name']]:
                die('GitHub asset %s does not match the Forgejo file (HTTP %d)' % (x['name'], st))
        if sorted(x['name'] for x in rel['assets']) != sorted(names):
            die('GitHub release asset list differs from the Forgejo pair')

    def upload(rel, name):
        url = rel['upload_url'].split('{', 1)[0] + '?name=' + urllib.parse.quote(name)
        if not url.startswith('https://uploads.github.com/'):
            die('unexpected GitHub upload host')
        x = gh_json('POST', url, token, want=(201,), what='asset upload ' + name,
                    raw=files[name], ctype='application/octet-stream')
        if x.get('name') != name or x.get('size') != len(files[name]) or x.get('state') != 'uploaded':
            die('GitHub asset %s: stored name/size/state differs' % name)

    existing = gh_releases_for(gbase, tag, token)
    if len(existing) > 1:
        die('GitHub has %d releases for %s' % (len(existing), tag))
    if existing:
        rel = existing[0]
        if rel.get('draft'):
            die('GitHub has an unpublished draft for %s; inspect it by hand' % tag)
        have = {x['name']: x for x in rel['assets']}
        extra = sorted(set(have) - set(files))
        if extra:
            die('GitHub release %s has extra assets: %s' % (tag, ', '.join(extra)))
        for x in have.values():
            if x.get('state') != 'uploaded' or x.get('size') != len(files[x['name']]):
                die('GitHub asset %s is incomplete or differs in size' % x['name'])
        missing = sorted(set(files) - set(have))
        check_published(rel, have)
        if a.dry_run:
            print('dry run: release %s exists on GitHub (id %d); would upload %s'
                  % (tag, rel['id'], ', '.join(missing) or 'nothing'))
            return
        for name in missing:
            upload(rel, name)
        rel = gh_json('GET', '%s/releases/%d' % (gbase, rel['id']), token, what='GitHub release read')
        check_published(rel, files)
        print('GitHub release %s (id %d) verified, %d assets byte-equal to Forgejo, uploaded: %s'
              % (tag, rel['id'], len(files), ', '.join(missing) or 'none'))
        return

    body = (frel.get('body') or '').rstrip() + '\n\n---\nCopied from the original release: %s\n' % (
        frel['html_url'])
    if a.dry_run:
        print('dry run: would create release %s (name %r, prerelease %s, make_latest %s) '
              'with %s' % (tag, frel['name'], bool(frel.get('prerelease')),
                           'true' if latest else 'false', ', '.join(sorted(files))))
        return
    # No target_commitish: the release attaches to the verified existing tag.
    rel = gh_json('POST', gbase + '/releases', token, want=(201,), what='GitHub draft creation',
                  payload={'tag_name': tag, 'name': frel['name'], 'body': body, 'draft': True,
                           'prerelease': bool(frel.get('prerelease'))})
    for name in sorted(files):
        upload(rel, name)
    rows = gh_json('GET', '%s/releases/%d/assets' % (gbase, rel['id']), token,
                   what='GitHub asset list')
    if sorted(x['name'] for x in rows) != sorted(files):
        die('GitHub draft asset list differs from the Forgejo pair')
    if gh_peeled(gbase, tag, token) != commit:
        die('GitHub tag %s moved before publishing' % tag)
    rel = gh_json('PATCH', '%s/releases/%d' % (gbase, rel['id']), token, what='GitHub publish',
                  payload={'draft': False, 'make_latest': 'true' if latest else 'false'})
    if rel.get('draft') or rel.get('tag_name') != tag:
        die('GitHub release %s did not publish' % tag)
    check_published(rel, files)
    print('published GitHub release %s (id %d), %d assets byte-verified: %s'
          % (tag, rel['id'], len(files), ', '.join(sorted(files))))


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
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('preflight')
    sub.add_parser('record-pins')
    c = sub.add_parser('config')
    c.add_argument('--out', required=True)
    c = sub.add_parser('accept')
    c.add_argument('--stage', required=True)
    c = sub.add_parser('package')
    c.add_argument('--stage', required=True)
    c.add_argument('--label', required=True)
    c.add_argument('--commit', required=True)
    c.add_argument('--run-url', required=True)
    c.add_argument('--private-dir', default='~/Downloads/rmx3997-images')
    c = sub.add_parser('layout')
    c.add_argument('--image', required=True)
    c.add_argument('--work', required=True)
    c.add_argument('--approve', metavar='WHAT', help='record this Image as approved')
    c = sub.add_parser('refresh-config')
    c.add_argument('--out', required=True)
    c = sub.add_parser('release')
    for flag in ('--api', '--repo', '--tag', '--commit', '--dist', '--run-url'):
        c.add_argument(flag, required=True)
    c = sub.add_parser('github-release')
    for flag in ('--forgejo-api', '--repo', '--github-repo', '--tag'):
        c.add_argument(flag, required=True)
    c.add_argument('--wait-tag', type=int, default=900, metavar='SECONDS')
    c.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    {'preflight': cmd_preflight, 'record-pins': cmd_record_pins, 'config': cmd_config,
     'accept': cmd_accept, 'package': cmd_package, 'release': cmd_release,
     'github-release': cmd_github_release,
     'layout': cmd_layout, 'refresh-config': cmd_refresh_config}[a.cmd](a)


if __name__ == '__main__':
    sys.stdout, sys.stderr = _Scrub(sys.stdout), _Scrub(sys.stderr)
    main()
