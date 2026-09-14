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
        cls.runmod=load(HERE/'run_ril_rank_live_002.py','runmod002'); cls.val=load(HERE/'protected'/'live_agent_driver.py','valmod002')

    def contract(self):
        x=json.loads((HERE/'RUNPOD_GPU_CONTRACT_TEMPLATE.json').read_text())
        x.update({'gpu_sku':'TEST-GPU','quoted_hourly_rate_usd':'0.60','quote_source':'test quote','quote_observed_utc':'2026-09-14T00:00:00Z'})
        return self.runmod.validate_gpu_contract(x)

    def packet(self):
        pool=[{'candidate_id':x} for x in 'abcdefghijkl']
        return {'gpu_contract':self.contract(),'tasks':[{'task_id':'t','candidate_pool_in_presented_order':pool}]}

    def response(self,runtime=0,used=False):
        tools=['Muse conversational reasoning','Muse Linux VM shell/filesystem']
        if used: tools.append('RunPod GPU')
        return {'experiment':'RIL-RANK-LIVE-002','orders':[{'task_id':'t','evaluation_order':['l','k','j','i']}],'tools_used':tools,'gpu_usage':{'used':used,'provider':'RunPod','gpu_sku':'TEST-GPU','pod_id':'p' if used else None,'quoted_hourly_rate_usd':'0.60','runtime_seconds':runtime,'session_wall_seconds':max(runtime,10),'start_utc':'a' if used else None,'stop_utc':'b' if used else None,'provider_reported_spend_usd':None}}

    def test_prince_identity_threshold_and_cost_scope_frozen(self):
        p=json.loads((HERE/'RIL_RANK_LIVE_002_PREREGISTRATION.json').read_text())
        self.assertEqual(p['design']['researcher_name'],'Prince'); self.assertEqual(p['design']['researcher_model'],'Muse Spark 1.3'); self.assertEqual(p['design']['tasks_total'],16); self.assertEqual(p['design']['required_success_count_advantage'],2); self.assertEqual(p['design']['min_rate_advantage'],0.125)
        self.assertEqual(p['resource_accounting']['hard_gpu_spend_ceiling_usd'],'2.56'); self.assertEqual(p['resource_accounting']['session_gpu_authorization_usd'],'1.28'); self.assertEqual(p['resource_accounting']['runtime_target_usd'],'1.20')
        self.assertEqual(p['resource_accounting']['muse_subscription_dollar_status'],'FIXED_SHARED_SUBSTRATE_DOLLAR_ALLOCATION_NOT_OBSERVABLE_NOT_ALLOCATED')

    def test_gpu_contract_computes_conservative_runtime(self):
        c=self.contract(); self.assertEqual(c['max_gpu_runtime_seconds_per_session'],7200); self.assertEqual(c['shutdown_margin_usd'],'0.08')

    def test_validator_allows_any_four_and_unused_gpu(self):
        ok,orders,issues,tools,gpu=self.val.validate_response(self.packet(),self.response())
        self.assertTrue(ok); self.assertEqual(issues,[]); self.assertEqual(orders['t'],['l','k','j','i']); self.assertFalse(gpu['used']); self.assertNotIn('RunPod GPU',tools)

    def test_validator_rejects_gpu_over_runtime_limit(self):
        r=self.response(runtime=7201,used=True); ok,_,issues,_,_=self.val.validate_response(self.packet(),r)
        self.assertFalse(ok); self.assertTrue(any('runtime' in x for x in issues))

    def test_gpu_accounting_uses_frozen_rate_not_invented_muse_cost(self):
        c=self.contract(); a=self.runmod.gpu_accounting(c,self.response(runtime=3600,used=True)['gpu_usage'])
        self.assertEqual(a['computed_gpu_spend_usd'],'0.600000'); self.assertLessEqual(Decimal(a['computed_gpu_spend_usd']),Decimal('1.28'))

    def test_claim_boundary_stays_below_recursive(self):
        p=json.loads((HERE/'RIL_RANK_LIVE_002_PREREGISTRATION.json').read_text()); text=' '.join(p['claim_boundary']).lower(); self.assertIn('single-run live selection transfer',text); self.assertIn('recursive improvement remains unearned',text)

if __name__=='__main__': unittest.main()
