#!/usr/bin/env python3
"""Board-side calibration. Access through the authenticated SSH tunnel only."""
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import threading
import time

CONFIG = Path('/etc/robot/camera-calibration.json')
DEFAULT = dict(rotation=90, fine_degrees=0.0, mirror_horizontal=False, mirror_vertical=False)
LOCK = threading.Lock()
TOKEN = secrets.token_urlsafe(32)


def validate(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT):
        raise ValueError('标定字段不完整或包含未知字段')
    if type(value['rotation']) is not int or value['rotation'] not in (0, 90, 180, 270):
        raise ValueError('方向只能是 0、90、180、270 度')
    angle = value['fine_degrees']
    if type(angle) not in (int, float) or not math.isfinite(angle) or abs(angle) > 45:
        raise ValueError('细调角度必须在 -45 到 45 度之间')
    if any(type(value[k]) is not bool for k in ('mirror_horizontal', 'mirror_vertical')):
        raise ValueError('镜像设置必须是布尔值')
    return value


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.'+path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(data)
            out.flush()
            os.fchmod(out.fileno(), 0o644)
            os.fsync(out.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def read_config(path=CONFIG):
    return validate(json.loads(path.read_text()))


def restart_media():
    subprocess.run(['/usr/local/lib/hello-microduck/mediad', '--check-calibration'],
                   check=True, timeout=10, capture_output=True, text=True)
    subprocess.run(['systemctl', 'restart', 'mediad.service'], check=True, timeout=30,
                   capture_output=True, text=True)
    # Type=exec completes before GStreamer discovery, which can fail after process startup.
    time.sleep(3)
    subprocess.run(['systemctl', 'is-active', '--quiet', 'mediad.service'], check=True,
                   timeout=5, capture_output=True)


def save(value, path=CONFIG, restart=restart_media):
    validate(value)
    with LOCK, path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = path.read_bytes()
        data = (json.dumps(value, indent=2, allow_nan=False)+'\n').encode()
        if json.loads(previous) == value:
            return value
        try:
            atomic_write(path, data)
            restart()
        except Exception:
            atomic_write(path, previous)
            restart()
            raise
        return read_config(path)


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, value, mime='application/json; charset=utf-8'):
        data = value.encode() if isinstance(value, str) else json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(data)

    def allowed(self):
        # Prevent DNS rebinding to this root-owned loopback service.
        return self.headers.get('Host') in ('127.0.0.1:8091', 'localhost:8091')

    def do_GET(self):
        if not self.allowed():
            return self.reply(403, {'error': 'Invalid host'})
        if self.path == '/':
            html = Path(__file__).with_name('index.html').read_text().replace('__TOKEN__', TOKEN)
            return self.reply(200, html, 'text/html; charset=utf-8')
        if self.path == '/api/calibration':
            try:
                return self.reply(200, read_config())
            except Exception as error:
                return self.reply(500, {'error': str(error)})
        self.reply(404, {'error': 'Not found'})

    def do_POST(self):
        if (not self.allowed() or self.path != '/api/calibration'
                or not secrets.compare_digest(self.headers.get('X-Hello-Token', ''), TOKEN)):
            return self.reply(403, {'error': 'Invalid request'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 1024:
                raise ValueError('请求大小无效')
            self.connection.settimeout(5)
            value = validate(json.loads(self.rfile.read(length)))
            self.reply(200, save(value))
        except (ValueError, json.JSONDecodeError) as error:
            self.reply(400, {'error': str(error)})
        except Exception as error:
            self.reply(500, {'error': '保存或启动失败；请检查 mediad 日志：'+str(error)})


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 8091), Handler).serve_forever()
