import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from charisma.core import CharismaError, load_json
from charisma.history import recent_runs, pause_project, undo_candidate
from charisma.incidents import triage, incident_markdown
from charisma.repair import receipt_path
from charisma.runner import run_cycle, cycle_lock
from test_agent import GitFixture


class HistoryTests(GitFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.state=self.directory/'state'
        self.config={'state_directory':str(self.state),'projects':[{'name':'website','path':str(self.root),'platform':'web','mode':'repair','tests':['python3 check.py']}]}
        proposed={'changes':[{'path':'index.html','content':self.plan['changes'][0]['content'],'reason':'Set the known page language.'}]}
        with patch('charisma.agents.request_structured',side_effect=[proposed,{'verdict':'approve','summary':'Focused language change.','concerns':[]}]):
            result=run_cycle(self.config,True,True)
        self.assertEqual(result[0]['status'],'awaiting_human_review')
        self.run_id=result[0]['run_id'];self.candidate=Path(result[0]['worktree'])

    def test_real_workflow_records_role_history_and_pause_blocks_further_work(self):
        history=recent_runs(self.state);run=history['runs'][0]
        self.assertEqual(run['status'],'awaiting_human_review')
        self.assertTrue(run['can_undo'])
        self.assertIn('independent_auditor',[step['role'] for step in run['timeline']])
        pause_project(self.state,self.run_id,True)
        self.assertTrue(recent_runs(self.state)['runs'][0]['paused'])
        with patch('charisma.runner.model_plan') as model:
            result=run_cycle(self.config,True,True)
        self.assertEqual(result[0]['status'],'blocked');model.assert_not_called()
        pause_project(self.state,self.run_id,False)
        self.assertEqual(run_cycle(self.config,True,True)[0]['status'],'unchanged')

    def test_undo_restores_only_recorded_unpublished_candidate(self):
        self.assertNotEqual((self.candidate/'index.html').read_text(),self.original)
        undo_candidate(self.state,self.run_id)
        self.assertEqual((self.candidate/'index.html').read_text(),self.original)
        self.assertEqual((self.root/'index.html').read_text(),self.original)
        self.assertFalse(load_json(receipt_path(self.candidate))['verified'])
        self.assertEqual(recent_runs(self.state)['runs'][0]['status'],'candidate_undone')

    def test_undo_refuses_human_edits_and_active_worker(self):
        with cycle_lock(self.state):
            with self.assertRaises(CharismaError): undo_candidate(self.state,self.run_id)
        (self.candidate/'index.html').write_text('A newer human edit')
        with self.assertRaises(CharismaError): undo_candidate(self.state,self.run_id)
        self.assertEqual((self.candidate/'index.html').read_text(),'A newer human edit')
        with self.assertRaises(CharismaError): undo_candidate(self.state,'../../outside')


class IncidentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'server.ndjson'

    def test_log_triage_reports_evidence_and_uncertainty_without_network_access(self):
        record={'source_ip':'192.0.2.10','status':401,'timestamp':'2026-10-26T12:00:00Z','path':'/account?token=private','email':'private@example.test'}
        self.path.write_text('\n'.join(json.dumps(record) for _ in range(12)))
        with patch('socket.socket',side_effect=AssertionError('No network allowed')):
            report=triage(self.path)
        self.assertEqual(report['records_reviewed'],12);self.assertEqual(report['network_requests_made'],0)
        self.assertEqual(len(report['signals']),1)
        self.assertIn('Unconfirmed',report['signals'][0]['cause'])
        self.assertNotIn('private',json.dumps(report));self.assertNotIn('private',incident_markdown(report))
        self.assertEqual(len(report['evidence_sha256']),64)

    def test_invalid_and_low_signal_logs(self):
        self.path.write_text('{"source_ip":"not-an-ip","status":401,"timestamp":"bad"}')
        with self.assertRaises(CharismaError): triage(self.path)
        self.path.write_text(json.dumps({'source_ip':'2001:db8::1','status':200,'timestamp':'2026-10-26T12:00:00+00:00'}))
        self.assertEqual(triage(self.path)['signals'],[])
