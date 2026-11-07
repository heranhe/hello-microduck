#!/usr/bin/env python3
import hashlib
import configparser
import importlib.util
import json
import os
from pathlib import Path
import sys
import tomllib

root = Path(sys.argv[1])
env = (root/'boot/armbianEnv.txt').read_text()
for field in ('rootdev=UUID=', 'fdtfile=rockchip/rk3566-radxa-zero3.dtb', 'overlays=', 'rootfstype=ext4'):
    assert field in env, field
for name in ('Image', 'dtb', 'uInitrd', 'boot.scr'):
    path = root/'boot'/name
    assert path.exists(), f'Broken boot path: {path}'
assert 'Local fix: do not rewrite boot configuration unless its contents change.' in (root/'usr/lib/armbian/armbian-hardware-optimization').read_text()
portal = (root/'usr/local/libexec/microduck-setup-portal.py').read_text()
assert "change = run('chpasswd'" not in portal
assert 'id="linux-pass"' not in portal
assert (root/'etc/systemd/system/multi-user.target.wants/hello-camera.service').is_symlink()
dropin = (root/'etc/systemd/system/mediad.service.d/zzzzzz-hello-camera.conf').read_text()
assert '/usr/local/lib/hello-microduck/mediad' in dropin
spec = importlib.util.spec_from_file_location('backend', root/'usr/local/lib/hello-microduck/backend.py')
b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
b.validate(json.loads((root/'etc/robot/camera-calibration.json').read_text()))
assert tomllib.loads((root/'etc/robot/robotd.toml').read_text())['media']['quality'] == '360p30'
expected = os.environ['HELLO_DEFAULT_PASSWORD_HASH'].strip()
users = dict(line.split(':', 1) for line in (root/'etc/shadow').read_text().splitlines())
assert users['radxa'].split(':')[0] == expected
profile_path = root/'etc/NetworkManager/system-connections/Microduck-Setup.nmconnection'
profile = configparser.ConfigParser(interpolation=None)
profile.read(profile_path)
assert profile['wifi-security']['psk'] == os.environ['HELLO_AP_PSK'].strip()
assert profile_path.stat().st_mode & 0o777 == 0o600
print('Image verified: boot references, repair, onboarding, password hash, camera and service enablement')
