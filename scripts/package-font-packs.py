#!/usr/bin/env python3
"""Build the AliasMode font packs: one zip of fonts per OS family.

The engine packages carry no fonts of other OSes. A profile whose identity is
another OS needs that OS's fonts, so the app downloads its pack once, checks it
against the SHA-256 it pins, unpacks it in its own data folder and passes the
folder to the engine (config key aliasmode:fontsDir, font-pack-dir.patch).

Each pack holds one OS's set of the 152.0.4-beta.30 r4 packages, which are the
fonts the app's font lists were made for: bundle/fonts/<os>/ at SOURCE_REF,
flattened, because DirectWrite and CoreText activate one flat directory. Names
are unique within a set (checked here). The zip is reproducible: entries are
sorted, with a fixed date and mode, so the same source gives the same pack.

    python3 scripts/package-font-packs.py --out dist
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import zipfile

# aliasmode-runtime-152.0.4-beta.30-r4: the last tree that kept the fonts in git.
SOURCE_REF = 'ab1519b7caef2c32c83c59f5028745ae71bb9478'
PACK_REVISION = '1'
OSES = ('windows', 'macos', 'linux')


def git(*args, **kwargs):
    return subprocess.run(['git', *args], check=True, **kwargs)


def ensure_commit(ref):
    """CI checks out one commit only; fetch the source commit when it is missing."""
    present = subprocess.run(['git', 'cat-file', '-e', f'{ref}^{{commit}}'],
                             capture_output=True).returncode == 0
    if not present:
        git('fetch', '--depth', '1', 'origin', ref)


def font_files(ref, os_name):
    """(basename, bytes) for every file under bundle/fonts/<os>/ at ref, sorted by name."""
    archive = subprocess.Popen(['git', 'archive', '--format=tar', ref, f'bundle/fonts/{os_name}'],
                               stdout=subprocess.PIPE)
    files = {}
    with tarfile.open(fileobj=archive.stdout, mode='r|') as tar:
        for member in tar:
            if not member.isfile():
                continue
            name = os.path.basename(member.name)
            if name in files:
                raise SystemExit(f'{os_name}: two files are named {name}; a flat pack needs unique names')
            files[name] = tar.extractfile(member).read()
    if archive.wait() != 0:
        raise SystemExit(f'git archive failed for bundle/fonts/{os_name} at {ref}')
    if not files:
        raise SystemExit(f'{os_name}: no fonts under bundle/fonts/{os_name} at {ref}')
    return sorted(files.items())


def write_pack(path, files):
    with zipfile.ZipFile(path, 'w') as pack:
        for name, data in files:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            pack.writestr(info, data, compresslevel=9)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--ref', default=SOURCE_REF, help='commit whose bundle/fonts/<os>/ is packed')
    parser.add_argument('--revision', default=PACK_REVISION, help='pack revision in the file name')
    parser.add_argument('--out', default='dist', help='output directory')
    args = parser.parse_args()

    ensure_commit(args.ref)
    os.makedirs(args.out, exist_ok=True)
    manifest = {'sourceRef': args.ref, 'revision': args.revision, 'packs': {}}
    for os_name in OSES:
        files = font_files(args.ref, os_name)
        name = f'aliasmode-fonts-{os_name}-{args.revision}.zip'
        path = os.path.join(args.out, name)
        write_pack(path, files)
        manifest['packs'][os_name] = {
            'asset': name,
            'size': os.path.getsize(path),
            'sha256': sha256(path),
            'files': len(files),
            'unpackedBytes': sum(len(data) for _, data in files),
        }
        print(f"{manifest['packs'][os_name]['sha256']}  {name}  "
              f"({len(files)} files, {manifest['packs'][os_name]['size']} bytes)")
        sys.stdout.flush()
    with open(os.path.join(args.out, f'aliasmode-fonts-{args.revision}.json'), 'w') as fh:
        json.dump(manifest, fh, indent=1)
        fh.write('\n')


if __name__ == '__main__':
    main()
