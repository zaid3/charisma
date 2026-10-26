import json
from pathlib import Path
import tempfile
import unittest

from charisma.assessments import import_zap, assessment_markdown
from charisma.core import CharismaError


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'zap.json'

    def report(self, sites):
        self.path.write_text(json.dumps({'@version':'fixture', 'site':sites}))
        return import_zap(self.path, 'https://fixture.example')

    def test_report_preserves_scope_severity_and_uncertainty(self):
        report = self.report([{'@name':'https://fixture.example','alerts':[
            {'pluginid':'1','name':'Review <script> | header','riskcode':'2','confidence':'1'}]}])
        self.assertEqual(report['findings'][0]['severity'], 'medium')
        self.assertFalse(report['full_manual_pentest_completed'])
        self.assertEqual(len(report['source_sha256']), 64)
        self.assertNotIn('<script>', assessment_markdown(report))

    def test_out_of_scope_empty_and_invalid_reports_are_rejected(self):
        for sites in [[], [{'@name':'https://other.example','alerts':[]}],
                      [{'@name':'https://fixture.example','alerts':None}]]:
            with self.assertRaises(CharismaError): self.report(sites)
        with self.assertRaises(CharismaError):
            import_zap(self.path, 'https://fixture.example/private')

    def test_scan_quality_is_retained_even_without_alerts(self):
        self.path.write_text(json.dumps({'site':[{'@name':'https://fixture.example','alerts':[]}],
            'insights':[{'site':'https://fixture.example','key':'insight.endpoint.total','statistic':'5'},
                        {'key':'insight.network.failure','statistic':'50','description':'Network failure percentage'}]}))
        report = import_zap(self.path,'https://fixture.example')
        self.assertEqual(report['reported_endpoint_count'],5)
        self.assertIn('Network failure percentage: 50', assessment_markdown(report))
        self.assertIn('does not establish complete coverage', assessment_markdown(report))
