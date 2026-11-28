#!/usr/bin/env python3
"""Install the Hello overlay into a mounted, checksum-pinned R1 image."""
import hashlib
import configparser
import importlib.util
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys

root, payload, source = map(Path, sys.argv[1:4])
here = Path(__file__).resolve().parent

def install(src, target, mode=0o644):
    target = root / target.lstrip('/')
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, target)
    target.chmod(mode)

portal = root/'usr/local/libexec/microduck-setup-portal.py'
original = portal.read_bytes()
assert hashlib.sha256(original).hexdigest() == '17aff218e0aaa4141a337b625c867d7dec3ef84935d65924ff6c8e8621cebf2f', 'Unexpected onboarding portal'
text = original.decode()
start = text.index('        # Update OS password via stdin,')
end = text.index('        existing = run(', start)
text = text[:start]+'        # Hello image installs the requested default password offline.\n'+text[end:]
start = text.index('                  <label for="linux-pass">')
end = text.index('                  <button type="submit"', start)
text = text[:start]+'''                  <p class="hint">radxa 已使用 Hello 固件统一默认密码；首次配网无需另设密码。</p>
'''+text[end:]
start = text.index('            # Do not accept newline/control chars in the password')
end = text.index('            # validate before accepting.', start)
text = text[:start]+text[end:]
compile(text, str(portal), 'exec')
portal.write_text(text)
os.chmod(portal, 0o755)

# Patch the actual boot-time writer before any boot of the new image.
repair_path = source/'scripts/repair-armbian-env.py'
spec = importlib.util.spec_from_file_location('repair', repair_path)
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)
result = repair.repair(target=root/'usr/lib/armbian/armbian-hardware-optimization',
                       boot_env=root/'boot/armbianEnv.txt',
                       backups=root/'var/backups/microduck-armbian-env', apply=True)
assert result['status'] in ('fixed', 'already-fixed'), result
if result['status'] == 'fixed':
    manifest_path = Path(result['backup'])/'manifest.json'
    metadata = json.loads(manifest_path.read_text())
    metadata['target'] = '/usr/lib/armbian/armbian-hardware-optimization'
    manifest_path.write_text(json.dumps(metadata, indent=2)+'\n')

install(repair_path, '/usr/local/lib/hello-microduck/repair-armbian-env.py', 0o755)
install(source/'scripts/licenses/GPL-2.0.txt', '/usr/local/lib/hello-microduck/licenses/GPL-2.0.txt')
install(source/'LICENSE', '/usr/local/lib/hello-microduck/licenses/Apache-2.0.txt')
for name in ('backend.py', 'index.html'):
    install(here/'runtime'/name, '/usr/local/lib/hello-microduck/'+name)
install(here/'runtime/camera-calibration.json', '/etc/robot/camera-calibration.json')
# Quarter-turn software transforms lose the board encoder's zero-copy fast path.
# Use the existing lower resolution preset instead of silently keeping 720p30.
params_path = root/'etc/robot/robotd.toml'
params = params_path.read_text()
media = re.search(r'^\[media\]\s*\n(?P<body>.*?)(?=^\[|\Z)', params, re.M | re.S)
if media:
    body = media.group('body')
    body = re.sub(r'^quality\s*=.*$', 'quality = "360p30"', body, flags=re.M) if re.search(r'^quality\s*=', body, re.M) else 'quality = "360p30"\n'+body
    params = params[:media.start('body')]+body+params[media.end('body'):]
else:
    params += '\n[media]\nquality = "360p30"\n'
params_path.write_text(params)
install(here/'runtime/hello-camera.service', '/etc/systemd/system/hello-camera.service')
install(payload/'mediad', '/usr/local/lib/hello-microduck/mediad', 0o755)
dropin = root/'etc/systemd/system/mediad.service.d/zzzzzz-hello-camera.conf'
dropin.write_text('[Service]\nExecStart=\nExecStart=/usr/local/lib/hello-microduck/mediad\n')
subprocess.run(['systemctl', '--root', str(root), 'enable', 'hello-camera.service'], check=True)

# chpasswd accepts only the salted hash here. No plaintext credential enters the source tree.
password_hash = os.environ['HELLO_DEFAULT_PASSWORD_HASH'].strip()
assert password_hash.startswith('$6$') and ':' not in password_hash
subprocess.run(['chroot', str(root), 'chpasswd', '-e'],
               input='radxa:'+password_hash+'\n', text=True, check=True)
subprocess.run(['chroot', str(root), 'chage', '-d', '20600', '-M', '99999', 'radxa'], check=True)
profile_path = root/'etc/NetworkManager/system-connections/Microduck-Setup.nmconnection'
profile = configparser.ConfigParser(interpolation=None)
profile.read(profile_path)
assert profile['wifi']['ssid'] == 'Microduck-kissqy'
psk = os.environ['HELLO_AP_PSK'].strip()
assert re.fullmatch(r'[0-9a-f]{64}', psk)
profile['wifi-security']['psk'] = psk
with profile_path.open('w') as out:
    profile.write(out, space_around_delimiters=False)
os.chmod(profile_path, 0o600)

# Snapshot the verified board-specific boot files without rewriting their contents.
backup = root/'var/lib/hello-microduck/boot-reference'
backup.mkdir(parents=True, exist_ok=True)
for name in ('armbianEnv.txt', 'boot.cmd', 'boot.scr'):
    shutil.copyfile(root/'boot'/name, backup/name)
links = {name: os.readlink(root/'boot'/name) for name in ('Image', 'dtb', 'uInitrd')}
(backup/'links.json').write_text(json.dumps(links, indent=2)+'\n')
manifest = {
    'name': 'Hello MicroDuck R1 preview',
    'upstream': 'kissqy/Microduck-kissqy',
    'upstream_commit': 'fc0cb40ad6c8da3628e0404abb45035b53bcbe16',
    'base_image_sha256': '75da978b5d56acd9e4146256431732381de84523bb683e4ab7ac9f0580a7bce5',
    'robot_firmware': 'R17 V164 control.40 (unchanged base motion firmware)',
    'camera': 'Hello mediad built from V167 source; calibration before tee',
    'boot_repair': result['status'],
    'hardware_tested': False,
}
(root/'etc/hello-microduck-release.json').write_text(json.dumps(manifest, indent=2)+'\n')
print(json.dumps(manifest, indent=2))
