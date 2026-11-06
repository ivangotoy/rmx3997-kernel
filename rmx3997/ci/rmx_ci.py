#!/usr/bin/env python3
"""RMX3997 CI gates: host-input pins, config, acceptance, packaging, release.

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
import urllib.error
import urllib.parse
import urllib.request

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
    PINS.write_text(json.dumps(pins, indent=2) + '\n')
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
    (stage / 'acceptance.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in gate.items() if k not in ('crc_mismatches',)}, indent=2))
    if gate['status'] != 'PASS':
        print('CRC mismatches:', json.dumps(gate['crc_mismatches'][:50]))
        die('OEM module CRC gate')
    print('acceptance: PASS (%s)' % identity['release'])


# --------------------------------------------------------------- boot image
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
    orig = int(re.search(r'Original image size:\s+(\d+)', info).group(1))
    if orig != PAGE + pad(ks) + pad(rs) + pad(sig):
        die('template AVB original size does not match its header')
    if not (re.search(r'Algorithm:\s+NONE', info) and re.search(r'Partition Name:\s+boot\b', info)):
        die('template AVB descriptor is not boot/NONE')
    salt = re.search(r'Salt:\s+([0-9a-f]+)', info).group(1)
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
    orig = int(re.search(r'Original image size:\s+(\d+)', info).group(1))
    salt = bytes.fromhex(re.search(r'Salt:\s+([0-9a-f]+)', info).group(1))
    digest = re.search(r'Digest:\s+([0-9a-f]+)', info).group(1)
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
    base = 'RMX3997-%s-%s' % (identity['release'], a.label)
    zip_path = dist / (base + '.zip')
    ident = dict(identity, build_purpose='forgejo-ci', source_commit=a.commit,
                 ci_run=a.run_url, oem_crc_gate=acc['oem_crc']['status'])
    m.package(image, zip_path, ident)
    img_path = dist / (base + '-boot_b.img')
    template = expand(pins['files']['boot_b_layout_template']['path'])
    built = build_boot_image(template, image, img_path, work)
    checked = verify_boot_image(img_path, image, work)
    (dist / (img_path.name + '.sha256')).write_text(sha(img_path) + '  ' + img_path.name + '\n')
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
        'phone_boot': 'UNVERIFIED (CI cannot boot the phone; flash and test before publishing)',
    }
    (dist / (base + '.provenance.json')).write_text(json.dumps(prov, indent=2) + '\n')
    with open(stage / 'dist.env', 'w') as f:
        f.write('RMX_DIST=%s\nRMX_BASE=%s\n' % (dist, base))
    for p in sorted(dist.iterdir()):
        print('%s  %s  %d' % (sha(p), p.name, p.stat().st_size))


# ------------------------------------------------------------------ release
def api(method, url, token, data=None, ctype='application/json'):
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Authorization', 'token ' + token)
    if data is not None:
        req.add_header('Content-Type', ctype)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body = r.read()
            return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read()


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
               'body': ('CI build of %s from commit %s.\n\nDraft until the image is flashed and '
                        'boot-tested on the phone. Checksums and provenance are attached.\n\nRun: %s\n'
                        % (tag, a.commit, a.run_url))}
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
        st, data = api('GET', asset['browser_download_url'], token)
        if st != 200 or hashlib.sha256(data).hexdigest() != sha(p):
            die('asset %s did not round-trip (HTTP %d)' % (p.name, st))
        uploaded.append(p.name)
    print('draft release %s (id %d) with %d verified assets: %s'
          % (tag, rel['id'], len(uploaded), ', '.join(uploaded)))


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
    c = sub.add_parser('release')
    for flag in ('--api', '--repo', '--tag', '--commit', '--dist', '--run-url'):
        c.add_argument(flag, required=True)
    a = p.parse_args()
    {'preflight': cmd_preflight, 'record-pins': cmd_record_pins, 'config': cmd_config,
     'accept': cmd_accept, 'package': cmd_package, 'release': cmd_release}[a.cmd](a)


if __name__ == '__main__':
    main()
