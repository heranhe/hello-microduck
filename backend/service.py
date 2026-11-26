"""Local SSH adapter for the Feetech robotd JSON-RPC commissioning API.

Written for hello-microduck; no code is copied from the community console.
The robot daemon remains the only owner of its servo UART.
"""
import base64
import errno
import hashlib
import json
import math
import re
import shlex
import socket
import threading
import time
from pathlib import Path


JOINTS = {
    20: 'left_hip_yaw', 21: 'left_hip_roll', 22: 'left_hip_pitch',
    23: 'left_knee', 24: 'left_ankle', 10: 'right_hip_yaw',
    11: 'right_hip_roll', 12: 'right_hip_pitch', 13: 'right_knee',
    14: 'right_ankle', 30: 'neck_pitch', 31: 'head_pitch',
    32: 'head_yaw', 33: 'head_roll', 34: 'mouth',
}
REMOTE = '''import json,socket,sys
r=json.load(sys.stdin)
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
 s.settimeout(12)
 s.connect(r['socket'])
 s.sendall((json.dumps(r['request'])+'\\n').encode())
 with s.makefile('rb') as f: line=f.readline(1048577)
 if len(line)>1048576 or not line.endswith(b'\\n'): raise RuntimeError('invalid robotd response')
 print(line.decode(),end='')
'''
BUS_MONITOR = '''import socket,sys
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
 s.settimeout(1)
 s.connect(sys.argv[1])
 with s.makefile('rb') as f:
  for _ in sys.stdin.buffer:
   s.sendall(b'{"jsonrpc":"2.0","id":1,"method":"robot.busStatus","params":{}}\\n')
   line=f.readline(1048577)
   if len(line)>1048576 or not line.endswith(b'\\n'): raise RuntimeError('invalid robotd response')
   sys.stdout.buffer.write(line)
   sys.stdout.buffer.flush()
'''


def rpc_result(raw):
    reply = json.loads(raw)
    if reply.get('id') != 1 or reply.get('jsonrpc') != '2.0':
        raise RuntimeError('robotd 响应格式不匹配')
    if reply.get('error'):
        raise RuntimeError(str(reply['error'].get('message', 'robotd 拒绝请求')))
    if 'result' not in reply:
        raise RuntimeError('robotd 响应缺少 result')
    return reply['result']


class BusTelemetry:
    """One read-only SSH channel per login, independent of command channels."""

    def __init__(self, client, path):
        self.client = client
        self.path = path
        self.lock = threading.Lock()
        self.stdin = self.stdout = None

    def read(self):
        with self.lock:
            try:
                if self.stdin is None:
                    command = 'python3 -u -c ' + shlex.quote(BUS_MONITOR) + ' ' + shlex.quote(self.path)
                    self.stdin, self.stdout, _ = self.client.exec_command(command, timeout=2)
                self.stdin.write(b'\n')
                self.stdin.flush()
                raw = self.stdout.readline(1048577)
                if len(raw) > 1048576 or not raw.endswith('\n'):
                    raise RuntimeError('robotd 实时反馈通道已中断或响应无效')
                bus = rpc_result(raw)
                if not isinstance(bus, dict):
                    raise RuntimeError('robotd 返回了无效总线状态')
                return bus
            except Exception:
                if self.stdin is not None:
                    self.stdin.channel.close()
                    self.stdin = self.stdout = None
                raise


class HostKeyRequired(Exception):
    def __init__(self, fingerprint):
        self.fingerprint = fingerprint
        super().__init__('请核对机器人 SSH 主机指纹后确认连接')


class RobotConnectionError(RuntimeError):
    """A connection-stage error with actionable text for the local console."""


def explain_ssh_failure(error, host, port):
    from paramiko import AuthenticationException, BadHostKeyException, SSHException
    from paramiko.ssh_exception import NoValidConnectionsError

    address = f'{host}:{port}'
    power_check = '先确认机器人主板已通电并完成启动，电脑和机器人在同一局域网，且地址填的是机器人当前的 IP。'
    if isinstance(error, BadHostKeyException):
        return f'SSH 主机指纹与保存的记录不一致（{address}）。请先核对 IP 和机器人的主机公钥指纹。'
    if isinstance(error, AuthenticationException):
        return f'已连到 {address}，但 SSH 认证失败。请核对 SSH 用户名、登录密码或密钥。'
    if isinstance(error, socket.gaierror):
        return f'找不到主机 {host}。{power_check} 如果填的是主机名，可改用机器人当前的 IP。'
    if isinstance(error, SSHException):
        return f'未能完成 SSH 协商（{address}）。请确认主板已启动，并核对该端口上运行的是 SSH 服务。\n{error}'

    failures = list(error.errors.values()) if isinstance(error, NoValidConnectionsError) else [error]
    if any(getattr(failure, 'winerror', None) == 10013 or failure.errno == 10013 for failure in failures):
        return (f'Windows 拒绝本机调试程序连接 {address}（WinError 10013）。\n{power_check}\n'
                f'在 PowerShell 中运行 Test-NetConnection {host} -Port {port}。\n'
                '如果系统 SSH 可以连接，请检查防火墙或安全软件对本机 Python 出站连接的规则。')
    if any(failure.errno in (errno.EACCES, errno.EPERM) for failure in failures):
        return f'系统拒绝本机调试程序连接 {address}。\n{power_check}\n请检查本机的网络访问规则。'
    if failures and all(failure.errno in (errno.ECONNREFUSED, 10061) for failure in failures):
        return f'SSH 端口 {address} 拒绝连接。\n{power_check}\n请确认机器人已启用 SSH，且端口填写正确。'
    return f'无法连接机器人 SSH（{address}）。\n{power_check}\n请再检查 SSH 服务和端口。'


def fingerprint(key):
    return 'SHA256:' + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')


def number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('%s 必须在 %s～%s 之间' % (name, low, high))
    return value


class RobotService:
    def __init__(self, known_hosts=None):
        self.known_hosts = Path(known_hosts or Path(__file__).parent / '.state' / 'known_hosts')
        self.client = None
        self.telemetry = None
        self.target = None
        self.socket_path = '/run/robotd.sock'
        self.lock = threading.RLock()
        self.command_lock = threading.Lock()

    def connect(self, data):
        if not self.command_lock.acquire(blocking=False):
            raise RuntimeError('操作进行中，不能更换连接目标')
        try:
            return self._connect(data)
        finally:
            self.command_lock.release()

    def _connect(self, data):
        import paramiko
        target = data.get('target', '')
        if not isinstance(target, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}@[A-Za-z0-9][A-Za-z0-9_.-]{0,252}', target):
            raise ValueError('地址格式应为 用户名@IP 或 用户名@主机名')
        user, host = target.split('@')
        port = data.get('port', 22)
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('SSH 端口无效')
        path = data.get('socket', '/run/robotd.sock')
        if not isinstance(path, str) or not re.fullmatch(r'/[A-Za-z0-9_./-]{1,200}', path):
            raise ValueError('robotd socket 必须是绝对路径')
        password = data.get('password', '')
        if not isinstance(password, str) or len(password) > 4096:
            raise ValueError('密码格式无效')
        accepted = data.get('fingerprint')
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        if self.known_hosts.exists():
            client.load_host_keys(str(self.known_hosts))
        new_keys = []

        class VerifyKey(paramiko.MissingHostKeyPolicy):
            def missing_host_key(policy, connection, hostname, key):
                actual = fingerprint(key)
                if accepted != actual:
                    raise HostKeyRequired(actual)
                new_keys.append((hostname, key))

        client.set_missing_host_key_policy(VerifyKey())
        try:
            try:
                client.connect(host, port=port, username=user, password=password or None,
                               allow_agent=not bool(password), look_for_keys=not bool(password),
                               timeout=8, auth_timeout=10, banner_timeout=8)
            except (OSError, paramiko.SSHException) as error:
                raise RobotConnectionError(explain_ssh_failure(error, host, port)) from error
            # Connection is reported only after a real robotd request succeeds.
            try:
                client.get_transport().set_keepalive(10)
                report = self._rpc(client, path, 'robot.busStatus', {})
                if not isinstance(report, dict):
                    raise RuntimeError('robotd 返回了无效总线状态')
            except (OSError, RuntimeError, ValueError, paramiko.SSHException) as error:
                raise RobotConnectionError(
                    f'SSH 已登录，但读取 robotd 失败。请检查机器人上的 robotd 服务和套接字 {path}。\n{error}'
                ) from error
            if new_keys:
                self.known_hosts.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                for hostname, key in new_keys:
                    client.get_host_keys().add(hostname, key.get_name(), key)
                client.save_host_keys(str(self.known_hosts))
                self.known_hosts.chmod(0o600)
            with self.lock:
                old, self.client = self.client, client
                self.telemetry = BusTelemetry(client, path)
                self.target, self.socket_path = target, path
            if old:
                old.close()
            return {'connected': True, 'target': target, 'bus': report}
        except Exception:
            client.close()
            raise

    def disconnect(self):
        if not self.command_lock.acquire(blocking=False):
            raise RuntimeError('连接或操作进行中；如需停止运动，请先点击卸力')
        try:
            return self._disconnect()
        finally:
            self.command_lock.release()

    def _disconnect(self, expected_telemetry=None):
        with self.lock:
            if expected_telemetry is not None and expected_telemetry is not self.telemetry:
                if self.telemetry is not None:
                    raise RuntimeError('SSH 连接已切换，请重新读取反馈')
                return {'connected': False}
            client, self.client = self.client, None
            self.telemetry = None
            self.target = None
        if client:
            client.close()
        return {'connected': False}

    @staticmethod
    def _rpc(client, path, method, params):
        command = 'python3 -c ' + shlex.quote(REMOTE)
        stdin, stdout, stderr = client.exec_command(command, timeout=18)
        try:
            request = {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}
            stdin.write(json.dumps({'socket': path, 'request': request}) + '\n')
            stdin.flush()
            stdin.channel.shutdown_write()
            raw = stdout.read(1048577)
            detail = stderr.read(4096).decode('utf-8', 'replace')
            if stdout.channel.recv_exit_status() != 0:
                raise RuntimeError('远端连接 robotd 失败：' + detail[-1000:])
            if len(raw) > 1048576:
                raise RuntimeError('robotd 响应过大')
            return rpc_result(raw)
        finally:
            stdin.close()
            stdout.close()
            stderr.close()

    def rpc(self, method, params):
        with self.lock:
            client, path = self.client, self.socket_path
        if not client or not client.get_transport() or not client.get_transport().is_active():
            raise RuntimeError('尚未连接机器人，或 SSH 已断开')
        return self._rpc(client, path, method, params)

    def status(self):
        with self.lock:
            telemetry, target = self.telemetry, self.target
            if telemetry is None:
                return {'connected': False}
        started = time.monotonic()
        transport = telemetry.client.get_transport()
        try:
            if transport is None or not transport.is_active():
                raise ConnectionError('SSH transport is inactive')
            bus = telemetry.read()
        except Exception as error:
            if (isinstance(error, (TimeoutError, EOFError, ConnectionError))
                    or transport is None or not transport.is_active()):
                result = self._disconnect(expected_telemetry=telemetry)
                return {**result, 'reason': 'SSH 已断开。请确认机器人已通电，然后重连。'}
            raise
        with self.lock:
            if telemetry is not self.telemetry:
                raise RuntimeError('SSH 连接已切换，请重新读取反馈')
        return {'connected': True, 'target': target, 'bus': bus,
                'request_ms': round((time.monotonic() - started) * 1000)}

    def calibration(self):
        return self.rpc('robot.busCommand', {'action': 'calibration-status'})

    def command(self, data):
        action = data.get('action')
        if action == 'relax':
            # Emergency torque-off does not wait for a previous capture/move.
            return self.rpc('robot.busCommand', {'action': 'relax'})
        if not self.command_lock.acquire(blocking=False):
            raise RuntimeError('已有操作进行中，请等待结果；卸力仍可用')
        try:
            if data.get('supported') is not True:
                raise ValueError('请先确认机器人已停止运动并可靠支撑')
            bus = self.rpc('robot.busStatus', {})
            if bus.get('mode') != 'commissioning':
                raise ValueError('robotd 必须已处于 commissioning 标定模式；本工具不会自动切换服务')
            if action == 'verify-imu':
                if data.get('confirmed') is not True:
                    raise ValueError('需确认 IMU 安装方向已按固件说明核验')
                params = {'action': action, 'confirmed': True, 'mount_wxyz': []}
            else:
                ident = data.get('id')
                if type(ident) is not int or ident not in JOINTS:
                    raise ValueError('请选择已配置的 MicroDuck 舵机 ID')
                if action == 'capture':
                    direction = data.get('direction')
                    if type(direction) is not int or direction not in (-1, 1):
                        raise ValueError('方向必须是 -1 或 +1，请按装配测量填写')
                    angle = number(data.get('angle_deg'), '已知物理角度', -360, 360)
                    low = number(data.get('min_deg'), '最小角度', -360, 360)
                    high = number(data.get('max_deg'), '最大角度', -360, 360)
                    if not low < high or not low <= angle <= high:
                        raise ValueError('角度范围需满足 最小值 < 最大值，且包含已知角度')
                    sample = bus.get('last_sample') or {}
                    now, at = bus.get('updated_at_us'), sample.get('at_us')
                    if (type(now) not in (int, float) or type(at) not in (int, float)
                            or not 0 <= now - at <= 500000):
                        raise ValueError('总线反馈过期，无法采集；请检查供电和通信')
                    rows = [r for r in sample.get('servos', []) if r.get('id') == ident]
                    if (len(rows) != 1 or type(rows[0].get('position_raw')) is not int
                            or not 0 <= rows[0]['position_raw'] <= 4095
                            or (rows[0].get('joint') or rows[0].get('name')) != JOINTS[ident]):
                        raise ValueError('选中舵机没有有效反馈，无法采集')
                    params = {'action': action, 'id': ident, 'angle_deg': angle,
                              'direction': direction, 'min_deg': low, 'max_deg': high}
                elif action == 'center-one':
                    if data.get('unassembled') is not True:
                        raise ValueError('转到中位前必须拆下舵盘并确认舵机未装入骨架')
                    params = {'action': 'move', 'id': ident, 'position': 2048, 'duration_ms': 2000}
                else:
                    raise ValueError('不支持的操作；本工具不提供直接行走或策略启用')
            return self.rpc('robot.busCommand', params)
        finally:
            self.command_lock.release()
