"""Verify dataset hashes and seal stage-2 artifacts, without altering the dataset."""
from temporal_maintenance_dataset_v2_lib import ROOT,read,sha,write

data=ROOT/'data/generated/temporal_maintenance_dev_v2'
out=ROOT/'experiments/analyses/temporal_maintenance_dataset_v2'
m=read(data/'manifest.json')
assert all(sha(data/p)==h for p,h in m['output_hashes'].items())
assert all(sha(p)==h for p,h in m['input_hashes'].items())
tests=(out/'full_tests.log').read_text(encoding='utf-8-sig')
assert 'Ran 77 tests' in tests and '\nOK' in tests
assert read(out/'freeze_verify.log')['matched'] is True
files=[ROOT/'PROJECT_HANDOFF.md',ROOT/'plans/时序运维数据v2生成协议.md',ROOT/'configs/temporal_maintenance_dev_v2.json',ROOT/'tests/test_temporal_maintenance_dataset_v2.py']
files += [ROOT/'scripts'/name for name in ('temporal_maintenance_dataset_v2_lib.py','build_temporal_maintenance_dev_v2.py','analyze_temporal_maintenance_dev_v2.py','plot_temporal_maintenance_dev_v2.py','seal_temporal_maintenance_dev_v2.py')]
for folder in (data,out,ROOT/'paper/figures/temporal_maintenance_dataset_v2'):
    files.extend(p for p in folder.rglob('*') if p.is_file() and p.name!='completion_manifest.json')
write(out/'completion_manifest.json',dict(stage=2,status='complete',tests_passed=77,freeze_matched=True,plot_visually_checked=True,model_calls=0,hashes={str(p.relative_to(ROOT)):sha(p) for p in sorted(set(files))}))
print('Stage 2 sealed; dataset hashes matched; 77 tests passed; old freeze matched.')
