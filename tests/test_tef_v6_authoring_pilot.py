import subprocess, sys, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
class AuthoringPilotTest(unittest.TestCase):
    def test_authoring_pilot_validator(self):
        result=subprocess.run([sys.executable,str(ROOT/"scripts/validate_tef_v6_authoring_pilot.py")],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
