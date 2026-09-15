import subprocess, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class SemanticBenchmarkV1Test(unittest.TestCase):
    def test_public_semantic_benchmark_validator(self):
        r=subprocess.run([sys.executable,str(ROOT/"scripts/validate_tef_v6_semantic_benchmark_v1.py")],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
if __name__=="__main__": unittest.main()
