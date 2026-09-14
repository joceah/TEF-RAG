import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from scripts.temporal_maintenance_dataset_v2_lib import ROOT,read,generate,audit,build,visible,Transform,dt
import random

class TemporalMaintenanceV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=read(ROOT/'configs/temporal_maintenance_dev_v2.json')
        cls.prototypes=read(ROOT/cls.config['scenario_review_path'])
        cls.assets,cls.docs,cls.queries,cls.gold,cls.chains=generate(cls.config,cls.prototypes)
        cls.lookup={d['id']:d for d in cls.docs}; cls.qs={q['query_id']:q for q in cls.queries}

    def test_scale_and_unequal_asset_histories(self):
        s=audit(self.assets,self.docs,self.queries,self.gold,self.chains)
        self.assertEqual((s['chains'],s['queries'],s['intents']),(192,1152,576))
        self.assertEqual(s['persistent_unknown_chains'],24)
        self.assertGreater(len(set(s['target_chain_counts'].values())),1)
        self.assertEqual(s['task_query_counts']['ordinary'],384)

    def test_deterministic_generation(self):
        self.assertEqual(self.docs,generate(self.config,self.prototypes)[1])

    def test_persistent_unknown_does_not_reveal_late_evidence(self):
        affected=[g for g in self.gold if g['persistent_unknown'] and g['prototype_query']==2]
        self.assertEqual(len(affected),48)
        for g in affected:
            self.assertTrue(g['local_unavailable_evidence_ids'])
            q=self.qs[g['query_id']]
            self.assertNotIn('后续记录仍未补齐',q['text'])
            self.assertTrue(all(not visible(self.lookup[i],q['query_time']) for i in g['local_unavailable_evidence_ids']))

    def test_public_interfaces_have_no_answer_metadata(self):
        prohibited={'scenario','chain_id','fault_code','episode_id','reference_answer','required_evidence_groups','persistent_unknown','prototype_query'}
        for d in self.docs:
            self.assertFalse(set(d)&prohibited)
            self.assertNotIn('SIM-',d['text'])
        for q in self.queries: self.assertFalse(set(q)&prohibited)

    def test_equivalent_copies_are_visible(self):
        groups=[group for g in self.gold for group in g['required_evidence_groups'] if len(group)>1]
        self.assertTrue(groups)
        for group in groups:
            self.assertEqual(self.lookup[group[1]]['origin_record_id'],group[0])

    def test_ordinary_queries_use_global_latest_not_hidden_chain(self):
        for g in self.gold:
            if g['task']!='ordinary': continue
            q=self.qs[g['query_id']]
            pool=[d for d in self.docs if d['asset_id']==q['asset_id'] and d['kind']!='procedure' and not d.get('origin_record_id') and visible(d,q['query_time'])]
            latest=max(d['event_time'] for d in pool)
            self.assertEqual({group[0] for group in g['required_evidence_groups']},{d['id'] for d in pool if d['event_time']==latest})

    def test_procedure_publication_and_validity_are_separate(self):
        found=False
        for g in self.gold:
            q=self.qs[g['query_id']]
            for i in g['inapplicable_as_current']:
                d=self.lookup[i]
                self.assertTrue(visible(d,q['query_time']))
                if q['query_time']<d['valid_from']: found=True
        self.assertTrue(found)

    def test_date_transform_preserves_short_gaps_and_updates_prose(self):
        c=next(c for c in self.prototypes['cases'] if c['id']=='C11')
        tr=Transform(c,random.Random(4),{'asset_id':'TARGET'}, {'asset_id':'NEIGHBOR'})
        transformed=tr.text('LC02 2026-06-25，6月25日')
        day=tr.dates['2026-06-25']
        self.assertIn(day,transformed)
        self.assertIn(f'{int(day[5:7])}月{int(day[8:10])}日',transformed)
        self.assertNotIn('LC02',transformed)

    def test_sqlite_isolation_and_overwrite_guard(self):
        with tempfile.TemporaryDirectory() as t:
            out=Path(t)/'dataset'
            build(out,self.config,ROOT/'configs/temporal_maintenance_dev_v2.json')
            with sqlite3.connect(out/'store.sqlite') as db:
                names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertEqual(names,{'assets','evidence'})
                payload=json.loads(db.execute('SELECT payload FROM assets LIMIT 1').fetchone()[0])
                self.assertNotIn('split_group',payload)
            db.close()
            with self.assertRaises(FileExistsError): build(out,self.config)

if __name__=='__main__': unittest.main()
