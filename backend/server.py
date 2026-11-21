#!/usr/bin/env python3
"""hello-microduck local real-device service. Never served by Cloudflare Pages."""
import argparse
import json
import re
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from service import HostKeyRequired, RobotService

STATIC = Path(__file__).with_name('static')
GUIDE = STATIC.parent.parent / 'tool' / 'calibration.html'
API_CSP = "default-src 'none'; frame-ancestors 'none'"
JAVASCRIPT = 'text/javascript; charset=utf-8'
ASSETS = {'/' + name: STATIC / name for name in (
    'live.js', 'three/three.module.min.js', 'three/utils/BufferGeometryUtils.js',
    'three/environments/RoomEnvironment.js',
)}


def console_page():
    """Use the shared guide markup and load only bundled scripts on the SSH origin."""
    nonce = secrets.token_urlsafe(24)
    nonce_attr = ' nonce="%s"' % nonce
    source = GUIDE.read_text(encoding='utf-8')
    source = re.sub(r'^<link [^\n]*fonts\.googleapis\.com[^\n]*>\n', '', source, flags=re.MULTILINE)
    source = source.replace('https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js', '/three/three.module.min.js')
    source = source.replace('https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/', '/three/')
    source = source.replace('<script type="importmap">', '<script type="importmap"%s>' % nonce_attr)
    source = source.replace('<script>\n\'use strict\';', '<script src="/live.js"></script>\n<script%s>\n\'use strict\';' % nonce_attr, 1)
    source = source.replace('<title>MicroDuck 标定流程演示</title>', '<title>MicroDuck 本机标定</title>')
    source = source.replace('id="mode-brand">MicroDuck 标定 · 演示', 'id="mode-brand">MicroDuck 标定 · 实机')
    csp = (
        "default-src 'none'; script-src 'self' 'nonce-%s'; style-src 'unsafe-inline'; "
        "connect-src 'self'; img-src data: blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    ) % nonce
    return ('<!doctype html>\n<html lang="zh-CN">\n' + source).encode(), csp


def make_handler(service, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # Request bodies and passwords never enter logs.
            pass

        def allowed(self):
            host = '127.0.0.1:%s' % self.server.server_port
            return self.headers.get('Host') == host and self.headers.get('Sec-Fetch-Site') not in ('cross-site',)

        def reply(self, status, data, kind='application/json; charset=utf-8', csp=API_CSP):
            raw = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', csp)
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if not self.allowed():
                return self.reply(403, {'error': '仅允许本机同源访问'})
            path = urlsplit(self.path).path
            if path == '/api/session':
                return self.reply(200, {'token': token, 'mode': 'real', 'version': '1.0.0'})
            if path == '/':
                page, csp = console_page()
                return self.reply(200, page, 'text/html; charset=utf-8', csp)
            if path in ASSETS:
                return self.reply(200, ASSETS[path].read_bytes(), JAVASCRIPT)
            return self.reply(404, {'error': '不存在的路径'})

        def do_POST(self):
            origin = 'http://127.0.0.1:%s' % self.server.server_port
            if (not self.allowed() or self.headers.get('Origin') != origin
                    or not secrets.compare_digest(self.headers.get('X-Session-Token', ''), token)):
                return self.reply(403, {'error': '本机来源或会话校验失败'})
            try:
                if self.headers.get_content_type() != 'application/json':
                    raise ValueError('请求必须使用 JSON')
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 16384:
                    raise ValueError('请求大小无效')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError('请求格式无效')
                routes = {'/api/connect': service.connect, '/api/disconnect': lambda d: service.disconnect(),
                          '/api/status': lambda d: service.status(), '/api/command': service.command}
                if self.path not in routes:
                    return self.reply(404, {'error': '不支持的接口'})
                self.reply(200, {'result': routes[self.path](data)})
            except HostKeyRequired as error:
                self.reply(409, {'error': str(error), 'fingerprint': error.fingerprint})
            except ValueError as error:
                self.reply(400, {'error': str(error)})
            except Exception as error:
                self.reply(502, {'error': '%s: %s' % (type(error).__name__, error)})
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8098)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be 1..65535')
    try:
        import paramiko  # noqa: F401
    except ImportError:
        sys.exit('请先执行 python -m pip install -r backend/requirements.txt（使用后端虚拟环境）')
    service = RobotService()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(service, secrets.token_urlsafe(32)))
    url = 'http://127.0.0.1:%s/' % args.port
    print('hello-microduck 本机实机调试服务：' + url, flush=True)
    print('仅监听本机。需要机器人已运行支持 robot.busStatus / robot.busCommand 的 robotd。', flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.disconnect()


if __name__ == '__main__':
    main()
