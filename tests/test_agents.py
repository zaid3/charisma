import copy
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

from charisma.agents import audit, platform_for_path, require_audit
from charisma.core import CharismaError
from charisma.repair import model_plan, apply_plan
from charisma.runner import read_config, run_cycle, runner_lock
from charisma.scan import scan_text
from test_agent import GitFixture


class AgentTests(GitFixture, unittest.TestCase):
    def test_specialist_is_reviewed_in_a_separate_call(self):
        proposed={'changes':[{'path':'index.html','content':self.original.replace('lang=""','lang="en"'),'reason':'Restore the page language.'}]}
        with patch('charisma.agents.request_structured',side_effect=[proposed,{'verdict':'approve','summary':'Focused change. Run page tests.','concerns':[]}]) as api:
            plan=model_plan(self.root,self.report,None,True,'web')
        self.assertEqual(api.call_count,2)
        self.assertNotEqual(api.call_args_list[0].args[1],api.call_args_list[1].args[1])
        self.assertNotIn('reason',api.call_args_list[1].args[0]['files'][0])
        self.assertEqual(plan['agents'],['scout','web_specialist','independent_auditor'])
        require_audit(plan)
        apply_plan(self.root,plan,self.work)

    def test_audit_rejection_and_tampering_block_apply(self):
        with patch('charisma.agents.request_structured',return_value={'verdict':'request_changes','summary':'Insufficient context.','concerns':['Needs a browser test']}):
            with self.assertRaises(CharismaError): audit(self.plan,{'index.html':self.original},'web')
        plan=copy.deepcopy(self.plan);plan['strategy']='model-proposal'
        with self.assertRaises(CharismaError): require_audit(plan)
        with patch('charisma.agents.request_structured',return_value={'verdict':'approve','summary':'Focused change.','concerns':[]}):
            plan['audit']=audit(plan,{'index.html':self.original},'web')
        plan['changes'][0]['content']+='changed'
        with self.assertRaises(CharismaError): require_audit(plan)

    def test_platform_separation_and_native_rules(self):
        self.assertEqual(platform_for_path('View.swift'),'ios')
        self.assertEqual(platform_for_path('WebView.kt'),'android')
        self.assertEqual(platform_for_path('App.tsx'),'web')
        plist=plistlib.dumps({'NSAppTransportSecurity':{'NSAllowsArbitraryLoads':True}}).decode()
        self.assertEqual(scan_text('Info.plist',plist)[0]['rule'],'ios-arbitrary-loads')
        self.assertEqual(scan_text('WebView.kt','settings.allowUniversalAccessFromFileURLs = true')[0]['rule'],'android-webview-file-access')
        manifest='<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application android:usesCleartextTraffic="true" /></manifest>'
        self.assertEqual(scan_text('AndroidManifest.xml',manifest)[0]['rule'],'android-cleartext')
        self.assertEqual(scan_text('WebView.kt','settings.allowUniversalAccessFromFileURLs = false'),[])

    def test_background_runner_deduplicates_unchanged_commits(self):
        state=self.directory/'state'
        config={'state_directory':str(state),'projects':[{'name':'web','path':str(self.root),'mode':'scan'}]}
        with runner_lock(state):
            first=run_cycle(config); second=run_cycle(config)
        self.assertEqual(first[0]['status'],'reported')
        self.assertEqual(second[0]['status'],'unchanged')
        self.assertEqual(first[0]['run_id'],second[0]['run_id'])
        report=state/first[0]['run_id']/'scan.json'
        self.assertTrue(report.exists())

    def test_runner_repairs_require_both_explicit_switches(self):
        config={'state_directory':str(self.directory/'state'),'projects':[{'name':'web','path':str(self.root),'mode':'repair','tests':['python check.py']}]}
        with patch('charisma.runner.model_plan') as model:
            result=run_cycle(config)
        self.assertEqual(result[0]['status'],'blocked');model.assert_not_called()

    def test_runner_config_and_single_process_lock(self):
        config=self.directory/'runner.toml'
        config.write_text(f'state_directory = {json.dumps(str(self.directory/"state"))}\ninterval_seconds = 60\n[[projects]]\nname="web"\npath={json.dumps(str(self.root))}\nmode="scan"\n')
        self.assertEqual(read_config(config)['interval_seconds'],60)
        with runner_lock(self.directory/'state'):
            with self.assertRaises(CharismaError):
                with runner_lock(self.directory/'state'): pass

    def test_offline_plan_cannot_smuggle_an_unreviewed_source_change(self):
        forged=copy.deepcopy(self.plan)
        forged['changes'][0]['content'] += '<script>unexpected()</script>'
        with self.assertRaises(CharismaError): apply_plan(self.root,forged,self.work)
        self.assertFalse(self.work.exists())

    def test_production_worker_rejects_missing_or_unpinned_isolation(self):
        config=self.directory/'production.toml'
        base=f'production=true\nstate_directory={json.dumps(str(self.directory/"state"))}\n[[projects]]\nname="web"\npath={json.dumps(str(self.root))}\nmode="repair"\nplatform="web"\ntests=["python check.py"]\n'
        for suffix in ['', 'test_image="python:latest"\n']:
            config.write_text(base+suffix)
            with self.assertRaises(CharismaError): read_config(config)
        config.write_text(base+'test_image="python@sha256:'+'a'*64+'"\n')
        self.assertTrue(read_config(config)['production'])
