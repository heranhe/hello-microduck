#!/usr/bin/env python3
"""hello-microduck local real-device service. Never served by Cloudflare Pages."""
import argparse
import json
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from service import HostKeyRequired, RobotService

STATIC = Path(__file__).with_name('static')


def make_handler(service, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # Request bodies and passwords never enter logs.
            pass

        def allowed(self):
            host = '127.0.0.1:%s' % self.server.server_port
            return self.headers.get('Host') == host and self.headers.get('Sec-Fetch-Site') not in ('cross-site',)

        def reply(self, status, data, kind='application/json; charset=utf-8'):
            raw = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if not self.allowed():
                return self.reply(403, {'error': '仅允许本机同源访问'})
            path = urlsplit(self.path).path
            if path == '/api/session':
                return self.reply(200, {'token': token, 'mode': 'real', 'version': '1.0.0'})
            files = {'/': ('index.html', 'text/html; charset=utf-8'),
                     '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                     '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if path not in files:
                return self.reply(404, {'error': '不存在的路径'})
            name, kind = files[path]
            self.reply(200, (STATIC / name).read_bytes(), kind)

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
