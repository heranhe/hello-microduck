import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('backend', Path(__file__).resolve().parents[1]/'runtime/backend.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)

class CalibrationTests(unittest.TestCase):
    def test_invalid_values_never_reach_disk(self):
        for change in ({'rotation': True}, {'rotation': 45}, {'fine_degrees': float('nan')},
                       {'fine_degrees': 46}, {'mirror_horizontal': 'false'}, {'extra': 1}):
            with self.assertRaises(ValueError):
                b.validate({**b.DEFAULT, **change})

    def test_saved_pixels_survive_a_new_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'camera.json'
            path.write_text(json.dumps(b.DEFAULT))
            value = {**b.DEFAULT, 'rotation': 270, 'fine_degrees': -3.5, 'mirror_horizontal': True}
            calls = []
            b.save(value, path, restart=lambda: calls.append(b.read_config(path)))
            self.assertEqual(calls, [value])
            self.assertEqual(b.read_config(path), value)
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)

    def test_restart_failure_restores_previous_calibration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'camera.json'
            old = json.dumps(b.DEFAULT).encode()
            path.write_bytes(old)
            calls = []
            def restart():
                calls.append(b.read_config(path))
                if len(calls) == 1:
                    raise RuntimeError('pipeline failed')
            with self.assertRaises(RuntimeError):
                b.save({**b.DEFAULT, 'rotation': 180}, path, restart)
            self.assertEqual(path.read_bytes(), old)
            self.assertEqual(calls[-1], b.DEFAULT)

    def test_unchanged_calibration_does_not_restart_camera(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'camera.json'
            path.write_text(json.dumps(b.DEFAULT))
            b.save(b.DEFAULT, path, restart=lambda: self.fail('unexpected restart'))

if __name__ == '__main__':
    unittest.main()
