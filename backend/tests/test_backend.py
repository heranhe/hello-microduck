import io
import json
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import HostKeyRequired, JOINTS, REMOTE, RobotService, fingerprint
from server import make_handler
from http.server import ThreadingHTTPServer


def report():
    return {'mode': 'commissioning', 'updated_at_us': 1000000,
            'last_sample': {'at_us': 900000, 'servos': [
                {'id': 20, 'joint': JOINTS[20], 'position_raw': 2050}]}}


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.service = RobotService()
        self.calls = []
        self.bus = report()
        def rpc(method, params):
            self.calls.append((method, params))
            return self.bus if method == 'robot.busStatus' else {'saved': True}
        self.service.rpc = rpc
        self.data = {'action': 'capture', 'supported': True, 'id': 20,
                     'angle_deg': 0, 'direction': -1, 'min_deg': -20, 'max_deg': 25}

    def test_capture_sends_verified_parameters_to_real_firmware_api(self):
        self.assertEqual(self.service.command(self.data), {'saved': True})
        self.assertEqual(self.calls[-1], ('robot.busCommand', {
            'action':'capture','id':20,'angle_deg':0,'direction':-1,'min_deg':-20,'max_deg':25}))

    def test_bad_input_never_reaches_write(self):
        for overrides in [{'supported':False}, {'id':1}, {'id':True}, {'direction':True},
                          {'angle_deg':float('nan')}, {'min_deg':30}, {'action':'run-shell'}, {'direction':0}]:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.service.command({**self.data, **overrides})
        self.assertFalse(any(m == 'robot.busCommand' for m, _ in self.calls))

    def test_wrong_mode_stale_and_mismatched_sample_refuse_capture(self):
        for mutate in [lambda b:b.update(mode='motion'),
                       lambda b:b['last_sample'].update(at_us=1),
                       lambda b:b['last_sample']['servos'][0].update(joint='right_knee'),
                       lambda b:b['last_sample']['servos'][0].update(position_raw=-1),
                       lambda b:b['last_sample']['servos'].clear()]:
            self.bus=report(); mutate(self.bus)
            with self.assertRaises(ValueError): self.service.command(self.data)
        self.assertFalse(any(m == 'robot.busCommand' for m, _ in self.calls))

    def test_move_requires_unassembled_and_only_single_joint(self):
        data={'action':'center-one','id':20,'supported':True}
        with self.assertRaises(ValueError): self.service.command(data)
        self.service.command({**data,'unassembled':True})
        self.assertEqual(self.calls[-1][1], {'action':'move','id':20,'position':2048,'duration_ms':2000})

    def test_relax_bypasses_busy_lock_but_other_commands_do_not(self):
        self.service.command_lock.acquire()
        try:
            with self.assertRaises(RuntimeError): self.service.command(self.data)
            self.assertEqual(self.service.command({'action':'relax'}), {'saved':True})
            self.assertEqual(self.calls[-1][1], {'action':'relax'})
            with self.assertRaises(RuntimeError): self.service.disconnect()
            with self.assertRaises(RuntimeError): self.service.connect({})
        finally:self.service.command_lock.release()

    def test_failed_write_is_not_retried(self):
        self.service.rpc=Mock(side_effect=[report(),TimeoutError('unknown result')])
        with self.assertRaises(TimeoutError):self.service.command(self.data)
        self.assertEqual(self.service.rpc.call_count,2)
        self.assertFalse(self.service.command_lock.locked())

    def test_imu_confirmation_is_explicit(self):
        data={'action':'verify-imu','supported':True}
        with self.assertRaises(ValueError):self.service.command(data)
        self.service.command({**data,'confirmed':True})
        self.assertEqual(self.calls[-1][1],{'action':'verify-imu','confirmed':True,'mount_wxyz':[]})


class RelayTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(socket, 'AF_UNIX'), 'Unix robot socket relay')
    def test_remote_agent_round_trip_with_unix_robotd_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=str(Path(tmp)/'robotd.sock')
            listener=socket.socket(socket.AF_UNIX);listener.bind(path);listener.listen(1)
            requests=[]
            def robot():
                with listener.accept()[0] as conn:
                    request=json.loads(conn.makefile('rb').readline());requests.append(request)
                    conn.sendall((json.dumps({'jsonrpc':'2.0','id':request['id'],'result':report()})+'\n').encode())
                listener.close()
            worker=threading.Thread(target=robot);worker.start()
            request={'jsonrpc':'2.0','id':1,'method':'robot.busStatus','params':{}}
            process=subprocess.run([sys.executable,'-c',REMOTE],input=json.dumps({'socket':path,'request':request}),capture_output=True,text=True,timeout=5)
            worker.join(2)
            self.assertEqual(process.returncode,0,process.stderr)
            self.assertEqual(json.loads(process.stdout)['result'],report())
            self.assertEqual(requests,[request])

    def test_rpc_error_and_wrong_id_cannot_look_successful(self):
        for reply in [{'jsonrpc':'2.0','id':1,'error':{'message':'commissioning required'}},
                      {'jsonrpc':'2.0','id':2,'result':{}}, {'jsonrpc':'2.0','id':1}]:
            client=Mock();stdin=Mock();stdout=Mock();stderr=Mock()
            stdout.read.return_value=json.dumps(reply).encode();stdout.channel.recv_exit_status.return_value=0
            stderr.read.return_value=b'';client.exec_command.return_value=(stdin,stdout,stderr)
            with self.assertRaises(RuntimeError):RobotService._rpc(client,'/run/robotd.sock','robot.busStatus',{})
            self.assertEqual(client.exec_command.call_count,1)
            self.assertIn('robot.busStatus',stdin.write.call_args.args[0])


class HostKeyTests(unittest.TestCase):
    def test_unknown_key_requires_explicit_fingerprint_and_persists_after_login(self):
        import paramiko
        key=paramiko.RSAKey.generate(1024)
        client=Mock();host_keys=paramiko.HostKeys()
        client.get_host_keys.return_value=host_keys
        def save(path):host_keys.save(path)
        client.save_host_keys.side_effect=save
        def connect(host,**kwargs):client.set_missing_host_key_policy.call_args.args[0].missing_host_key(client,host,key)
        client.connect.side_effect=connect
        with tempfile.TemporaryDirectory() as tmp, patch('paramiko.SSHClient',return_value=client):
            path=Path(tmp)/'known_hosts';service=RobotService(path);service._rpc=Mock(return_value=report())
            with self.assertRaises(HostKeyRequired):service.connect({'target':'radxa@duck.local','password':'secret'})
            self.assertFalse(path.exists());self.assertIsNone(service.client)
            service.connect({'target':'radxa@duck.local','password':'secret','fingerprint':fingerprint(key)})
            self.assertTrue(path.exists());self.assertIn('duck.local',path.read_text())
            self.assertNotIn('secret',path.read_text())
            self.assertTrue(client.connect.call_args.kwargs['password']=='secret')

    def test_failed_robotd_probe_does_not_save_new_key(self):
        import paramiko
        key=paramiko.RSAKey.generate(1024);client=Mock()
        client.connect.side_effect=lambda host,**kw:client.set_missing_host_key_policy.call_args.args[0].missing_host_key(client,host,key)
        with tempfile.TemporaryDirectory() as tmp, patch('paramiko.SSHClient',return_value=client):
            path=Path(tmp)/'known_hosts';service=RobotService(path);service._rpc=Mock(side_effect=RuntimeError('no socket'))
            with self.assertRaises(RuntimeError):service.connect({'target':'radxa@duck.local','fingerprint':fingerprint(key)})
            self.assertFalse(path.exists());self.assertIsNone(service.client);client.close.assert_called()


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.service=Mock();self.service.status.return_value={'connected':False}
        self.service.command.return_value={'torque':'off'}
        self.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.service,'test-token'))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.origin='http://127.0.0.1:%s'%self.server.server_port

    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join()

    def request(self,path,body=None,headers=None):
        conn=HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        conn.request('GET' if body is None else 'POST',path,body=None if body is None else json.dumps(body),headers=headers or {})
        response=conn.getresponse();data=response.read();status=response.status;head=dict(response.getheaders());conn.close()
        return status,data,head

    def valid_headers(self):return {'Origin':self.origin,'X-Session-Token':'test-token','Content-Type':'application/json'}

    def test_static_session_and_real_disconnected_status(self):
        status,body,headers=self.request('/')
        self.assertEqual(status,200);self.assertIn('本机实机调试'.encode(),body)
        self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
        status,body,_=self.request('/api/session');self.assertEqual(json.loads(body)['mode'],'real')
        status,body,_=self.request('/api/status',{},self.valid_headers())
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['result'],{'connected':False})

    def test_cross_origin_missing_token_and_rebinding_are_rejected(self):
        for headers in [{}, {**self.valid_headers(),'Origin':'https://attacker.example'},
                        {**self.valid_headers(),'X-Session-Token':'wrong'},
                        {**self.valid_headers(),'Host':'attacker.example'},
                        {**self.valid_headers(),'Sec-Fetch-Site':'cross-site'}]:
            self.assertEqual(self.request('/api/command',{'action':'relax'},headers)[0],403)
        self.service.command.assert_not_called()
        self.assertEqual(self.request('/api/session',headers={'Host':'attacker.example'})[0],403)

    def test_invalid_payload_and_unknown_routes_never_execute(self):
        self.assertEqual(self.request('/api/command',[],self.valid_headers())[0],400)
        self.assertEqual(self.request('/api/command',{}, {**self.valid_headers(),'Content-Type':'text/plain'})[0],400)
        self.assertEqual(self.request('/api/shell',{},self.valid_headers())[0],404)
        self.assertEqual(self.request('/../../service.py')[0],404)
        self.service.command.assert_not_called()

    def test_backend_error_is_visible_and_only_sent_once(self):
        self.service.command.side_effect=RuntimeError('firmware method unavailable')
        status,body,_=self.request('/api/command',{'action':'relax'},self.valid_headers())
        self.assertEqual(status,502);self.assertIn('firmware method unavailable',json.loads(body)['error'])
        self.service.command.assert_called_once()


if __name__=='__main__':unittest.main()
