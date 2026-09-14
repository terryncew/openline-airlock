from __future__ import annotations
import importlib.util,json,unittest
from pathlib import Path
from decimal import Decimal

HERE=Path(__file__).resolve().parents[1]
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runmod=load(HERE/'run_ril_rank_live_001.py','runmod'); cls.val=load(HERE/'protected'/'live_agent_driver.py','valmod')
    def test_prince_identity_and_threshold_frozen(self):
        p=json.loads((HERE/'RIL_RANK_LIVE_001_PREREGISTRATION.json').read_text())
        self.assertEqual(p['design']['researcher_name'],'Prince'); self.assertEqual(p['design']['researcher_model'],'Muse Spark 1.3'); self.assertEqual(p['design']['researcher_product'],'Muse'); self.assertEqual(p['design']['tasks_total'],16); self.assertEqual(p['design']['required_success_count_advantage'],2); self.assertEqual(p['design']['min_rate_advantage'],0.125)
    def test_validator_allows_any_four_from_full_pool(self):
        pool=[{'candidate_id':x} for x in 'abcdefghijkl']; packet={'tasks':[{'task_id':'t','candidate_pool_in_presented_order':pool}]}; response={'experiment':'RIL-RANK-LIVE-001','orders':[{'task_id':'t','evaluation_order':['l','k','j','i']}],'tools_used':[]}
        ok,orders,issues,_=self.val.validate_response(packet,response); self.assertTrue(ok); self.assertEqual(issues,[]); self.assertEqual(orders['t'],['l','k','j','i'])
    def test_validator_rejects_candidate_outside_pool(self):
        pool=[{'candidate_id':x} for x in 'abcdefghijkl']; packet={'tasks':[{'task_id':'t','candidate_pool_in_presented_order':pool}]}; response={'experiment':'RIL-RANK-LIVE-001','orders':[{'task_id':'t','evaluation_order':['a','b','c','z']}],'tools_used':[]}
        ok,_,issues,_=self.val.validate_response(packet,response); self.assertFalse(ok); self.assertTrue(issues)
    def test_budget_ceiling_is_exact_and_overflow_rejected(self):
        r=self.runmod.cost_template()
        for slot in ('session-1','session-2'): r['sessions'][slot]={'incremental_paid_usd':'1.28','billing_basis':'test','source':'test','complete':True}
        r['receiver_incremental_paid_usd']='0.00'; r['receiver_cost_basis']='test'; r['receiver_cost_source']='test'; r['other_incremental_paid_usd']='0.00'; r['other_cost_basis']='test'; r['other_cost_source']='test'
        self.assertEqual(self.runmod.validate_cost_record(r)['total'],Decimal('2.56')); r['sessions']['session-2']['incremental_paid_usd']='1.29'
        with self.assertRaises(RuntimeError): self.runmod.validate_cost_record(r)
    def test_claim_boundary_stays_below_recursive(self):
        p=json.loads((HERE/'RIL_RANK_LIVE_001_PREREGISTRATION.json').read_text()); text=' '.join(p['claim_boundary']).lower(); self.assertIn('single-run live selection transfer',text); self.assertIn('recursive improvement remains unearned',text)

if __name__=='__main__': unittest.main()
