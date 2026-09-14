"""Static publication-format descriptive plots, with explicit synthetic scope."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]
s=json.loads((ROOT/'experiments/analyses/temporal_maintenance_dataset_v2/statistics.json').read_text(encoding='utf-8'))
out=ROOT/'paper/figures/temporal_maintenance_dataset_v2'; out.mkdir(parents=True,exist_ok=True)
fig,axes=plt.subplots(2,3,figsize=(14,8),layout='constrained')
ax=axes[0,0]; ax.bar(s['scenario_counts'].keys(),s['scenario_counts'].values(),color='#36719d'); ax.tick_params(axis='x',rotation=60); ax.set(title='Scenario allocation (design quota)',ylabel='Chains')
ax=axes[0,1]; ax.bar(['Temporal','Ordinary'],[s['task_query_counts']['temporal'],s['task_query_counts']['ordinary']],color=['#36719d','#69a992']); ax.set(title='Query allocation',ylabel='Queries (2 per intent)')
ax=axes[0,2]; ax.hist(list(s['target_chain_counts'].values()),bins=range(1,max(s['target_chain_counts'].values())+2),align='left',rwidth=.85,color='#36719d'); ax.set(title='Unequal target histories',xlabel='Chains per target',ylabel='Targets')
ax=axes[1,0]; ax.hist(s['evidence_per_chain'],bins=range(min(s['evidence_per_chain']),max(s['evidence_per_chain'])+2),align='left',rwidth=.85,color='#69a992'); ax.set(title='Records per chain',xlabel='Records (including background)',ylabel='Chains')
ax=axes[1,1]; ax.hist(s['ingestion_delay_minutes'],bins=[0,1,10,60,360,1440,10080,43200,200000],color='#36719d'); ax.set_xscale('symlog',linthresh=1); ax.set(title='Record ingestion delay',xlabel='Minutes (symmetric log scale)',ylabel='Records')
ax=axes[1,2]; ax.bar(['Unchanged prototype\nevidence timing','Persistent missing\nevidence variant'],[s['chains']-s['persistent_unknown_chains'],s['persistent_unknown_chains']],color=['#36719d','#cf9056']); ax.set(title='Later-query evidence design',ylabel='Chains')
fig.suptitle('Temporal maintenance dev v2 | Source-grounded synthetic data\nDesign distributions, not observed field prevalence',fontsize=16)
fig.savefig(out/'dataset_distributions.png',dpi=160); fig.savefig(out/'dataset_distributions.svg'); plt.close(fig)
print(out)
