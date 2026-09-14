"""Build the approved stage-2 dataset once, into a new directory."""
import argparse
from pathlib import Path
from temporal_maintenance_dataset_v2_lib import ROOT,read,build

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--config',type=Path,default=ROOT/'configs/temporal_maintenance_dev_v2.json')
    p.add_argument('--output',type=Path,default=ROOT/'data/generated/temporal_maintenance_dev_v2')
    a=p.parse_args(); s=build(a.output,read(a.config),a.config)
    print({k:s[k] for k in ('chains','evidence','queries','intents','persistent_unknown_chains')})
