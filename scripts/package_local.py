#!/usr/bin/env python3
"""Build the downloadable local service bundle without credentials or venvs."""
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'site' / 'downloads'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    archive = OUT / 'hello-microduck-local.zip'
    files = []
    for directory in ['backend', 'tools/feetech', 'scripts', 'src', 'tool', 'docs']:
        for path in (ROOT / directory).rglob('*'):
            relative = path.relative_to(ROOT)
            if path.is_file() and not any(part.startswith('.') or part == '__pycache__' for part in relative.parts):
                files.append(path)
    for name in ['start.command', 'start.cmd', 'build.py', 'README.md', '.gitignore']:
        files.append(ROOT / name)
    # Include prebuilt tutorial assets for the local preview, never its downloads.
    files += [p for p in (ROOT / 'site').rglob('*') if p.is_file() and OUT not in p.parents and not any(x.startswith('.') for x in p.relative_to(ROOT).parts)]
    with ZipFile(archive, 'w', compression=ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(set(files)):
            info = ZipInfo('hello-microduck/' + path.relative_to(ROOT).as_posix(), (2026, 11, 6, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = (path.stat().st_mode & 0xffff) << 16
            bundle.writestr(info, path.read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=9)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (OUT / 'SHA256SUMS.txt').write_text('%s  %s\n' % (digest, archive.name), encoding='utf-8')
    license_path = ROOT / 'tools/feetech/LICENSE'
    software_path = ROOT / 'tools/feetech/FD1.9.8.5(250729).7z'
    for path in [license_path, software_path]:
        (OUT / path.name).write_bytes(path.read_bytes())
    manifest = {'file': archive.name, 'sha256': digest, 'bytes': archive.stat().st_size,
                'fd_sha256': hashlib.sha256(software_path.read_bytes()).hexdigest()}
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print('本机部署包：%s（%s bytes）' % (archive.relative_to(ROOT), archive.stat().st_size))
    print('SHA256: ' + digest)


if __name__ == '__main__':
    main()
