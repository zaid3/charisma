import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from charisma.core import git as actual_git, CharismaError, digest, load_json, read_source, safe_file, write_json, write_private
from charisma.scan import scan, scan_text, import_sarif, markdown
from charisma import provider
from charisma.repair import language_plan, bundle, apply_plan, validate_plan, verify, run_check, receipt_path, publish


def command(root, *args):
    return subprocess.run(args, cwd=root, check=True, capture_output=True, text=True).stdout.strip()


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_paths_reject_traversal_git_and_symlink(self):
        for name in ['../outside', '/etc/passwd', '.git/config', 'a/../../b', 'a\\b', 'a\x00b']:
            with self.subTest(name=name), self.assertRaises(CharismaError): safe_file(self.root, name)
        (self.root/'link').symlink_to(self.root/'target')
        with self.assertRaises(CharismaError): safe_file(self.root, 'link')

    def test_private_outputs_are_atomic_and_do_not_follow_links(self):
        output = self.root/'report.json'; output.write_text('old'); output.chmod(0o644)
        write_json(output, {'new': True})
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(load_json(output), {'new': True})
        link = self.root/'link'; link.symlink_to(output)
        with self.assertRaises(CharismaError): write_private(link, 'bad')
        self.assertEqual(load_json(output), {'new': True})

    def test_semantic_markup_and_patterns(self):
        text = '<html><head><title> </title><meta name="viewport" content="user-scalable=no"></head><body><img src="x"><input></body></html>'
        self.assertEqual({f['rule'] for f in scan_text('index.html', text)}, {'html-language','page-title','zoom-disabled','image-alt','input-label'})
        valid = '<html lang="en"><title>Search</title><img alt=""><label for="q">Query</label><input id="q"><label>Notes<textarea></textarea></label><input aria-label="Name"></html>'
        self.assertEqual(scan_text('index.html', valid), [])
        self.assertEqual(scan_text('fragment.html', '<!-- <img> --><p>Fine</p>'), [])
        self.assertEqual({f['rule'] for f in scan_text('app.js','eval(input); node.innerHTML = value;')}, {'dynamic-code','html-sink'})

    def test_boolean_html_attributes_do_not_crash(self):
        self.assertTrue(scan_text('index.html','<html lang><input type><meta name></html>'))

    def test_scan_excludes_sensitive_files_and_never_exposes_match(self):
        secret = 'ghp_' + 'a'*36
        (self.root/'.env').write_text(secret)
        (self.root/'app.js').write_text('const token = "' + secret + '";')
        report = scan(self.root)
        self.assertEqual(report['files_scanned'], 1)
        self.assertEqual(report['findings'][0]['rule'], 'credential-pattern')
        self.assertNotIn(secret, json.dumps(report))
        self.assertNotIn(secret, markdown(report))

    def test_file_limit_reports_incomplete(self):
        for i in range(3): (self.root/f'{i}.js').write_text('const ok = true;')
        with patch('charisma.scan.MAX_FILES', 1): report = scan(self.root)
        self.assertTrue(report['errors'])

    def test_sarif_is_imported_and_malformed_input_is_rejected(self):
        (self.root/'app.js').write_text('const x=1;')
        source = self.root/'report.sarif'
        finding = {'ruleId':'external-rule','message':{'text':'Review this'},'locations':[{'physicalLocation':{'artifactLocation':{'uri':'app.js'},'region':{'startLine':1}}}]}
        write_json(source, {'version':'2.1.0','runs':[{'results':[finding]}]})
        report = import_sarif(scan(self.root), source, self.root)
        self.assertTrue(report['findings'][-1]['external'])
        for uri in ['../other.js', '%2e%2e/other.js', 'https://example.com/a.js', '.env']:
            finding['locations'][0]['physicalLocation']['artifactLocation']['uri'] = uri
            write_json(source, {'version':'2.1.0','runs':[{'results':[finding]}]})
            with self.subTest(uri=uri), self.assertRaises(CharismaError): import_sarif(scan(self.root), source, self.root)
        for malformed in [{'results':[None]}, {'results':{}}, {'tool':[]}, {'results':[{'message': []}]}]:
            write_json(source, {'version':'2.1.0','runs':[malformed]})
            with self.subTest(malformed=malformed), self.assertRaises(CharismaError): import_sarif(scan(self.root), source, self.root)


class GitFixture:

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name); self.root = self.directory/'repo'; self.root.mkdir()
        command(self.root,'git','init','-b','main')
        command(self.root,'git','config','user.name','Charisma Test')
        command(self.root,'git','config','user.email','tests@example.invalid')
        self.original = '<!-- <html data-fake="true"> -->\n<!doctype html><html data-lang="fr" lang=""><head><title>Example</title></head><body><h1>Hello</h1></body></html>\n'
        (self.root/'index.html').write_text(self.original)
        (self.root/'.gitignore').write_text('.charisma/\n__pycache__/\n')
        (self.root/'check.py').write_text('from pathlib import Path\nassert \'lang="en-GB"\' in Path("index.html").read_text()\n')
        command(self.root,'git','add','.'); command(self.root,'git','commit','-m','Fixture')
        self.report = scan(self.root); self.plan = language_plan(self.root,self.report,'en-GB')
        self.work = self.directory/'candidate'

    def apply(self):
        return apply_plan(self.root,self.plan,self.work)


class RepairTests(GitFixture, unittest.TestCase):
    def test_complete_offline_repair_keeps_original_unchanged(self):
        result = self.apply()
        self.assertEqual(result['status'],'awaiting_verification')
        candidate = (self.work/'index.html').read_text()
        self.assertIn('data-lang="fr" lang="en-GB"', candidate)
        self.assertIn('<!-- <html data-fake="true"> -->', candidate)
        self.assertEqual((self.root/'index.html').read_text(), self.original)
        receipt = verify(self.work,[f'{sys.executable} check.py'],True)
        self.assertTrue(receipt['verified']); self.assertFalse(receipt['new_findings'])
        self.assertEqual(command(self.root,'git','status','--porcelain'),'')

    def test_missing_and_boolean_lang_attributes(self):
        for attr in ['', 'lang', 'data-note=" lang=foo"']:
            (self.root/'index.html').write_text(f'<html {attr}><title>Example</title></html>')
            command(self.root,'git','add','.'); command(self.root,'git','commit','-m','Markup variant')
            proposal = language_plan(self.root,scan(self.root),'en')
            self.assertNotIn('html-language', {f['rule'] for f in scan_text('index.html',proposal['changes'][0]['content'])})

    def test_language_value_cannot_inject_markup(self):
        with self.assertRaises(CharismaError): language_plan(self.root,self.report,'en" onload="alert(1)')

    def test_stale_plan_dirty_repo_and_unknown_targets_fail(self):
        bad = copy.deepcopy(self.plan); bad['changes'][0]['before_sha256'] = 'wrong'
        with self.assertRaises(CharismaError): validate_plan(self.root,bad)
        bad = copy.deepcopy(self.plan); bad['targets'][0]['rule'] = 'not-a-real-rule'
        with self.assertRaises(CharismaError): validate_plan(self.root,bad)
        (self.root/'extra.txt').write_text('unsaved')
        with self.assertRaises(CharismaError): validate_plan(self.root,self.plan)

    def test_plan_cannot_edit_tests_or_workflows_or_extra_files(self):
        for path in ['tests/test.py','.github/workflows/ci.yml','../../escape.js','other.js']:
            proposal = {'changes':[{'path':path,'content':'x','reason':'test'}]}
            with self.subTest(path=path), self.assertRaises(CharismaError):
                bundle(self.plan['base_commit'],self.report['findings'],{'index.html':self.original},proposal,'model-proposal')
        bad = copy.deepcopy(self.plan); bad['changes'] = [None]
        with self.assertRaises(CharismaError): validate_plan(self.root,bad)

    def test_proposal_secret_is_rejected(self):
        proposal={'changes':[{'path':'index.html','content':'ghp_'+'a'*36,'reason':'test'}]}
        with self.assertRaises(CharismaError): bundle(self.plan['base_commit'],self.report['findings'],{'index.html':self.original},proposal,'model')

    def test_failures_and_later_edits_block_verification(self):
        self.apply()
        result = verify(self.work,[f'{sys.executable} -c "raise SystemExit(1)"'],True)
        self.assertFalse(result['verified'])
        with self.assertRaises(CharismaError): verify(self.work,[f'{sys.executable} check.py'],False)
        (self.work/'extra.txt').write_text('unexpected')
        with self.assertRaises(CharismaError): verify(self.work,[f'{sys.executable} check.py'],True)
        self.assertFalse(load_json(receipt_path(self.work))['verified'])

    def test_new_builtin_finding_blocks_verification(self):
        self.plan['changes'][0]['content'] += '<img src="new.png">'
        self.plan['changes'][0]['after_sha256'] = digest(self.plan['changes'][0]['content'])
        self.apply()
        result = verify(self.work,[f'{sys.executable} check.py'],True)
        self.assertFalse(result['verified']); self.assertEqual(result['new_findings'][0]['rule'],'image-alt')

    def test_incomplete_rescan_cannot_pass(self):
        self.apply()
        with patch('charisma.repair.scan',return_value={'errors':['incomplete'],'file_hashes':{},'findings':[]}):
            with self.assertRaises(CharismaError): verify(self.work,[f'{sys.executable} check.py'],True)
        self.assertFalse(load_json(receipt_path(self.work))['verified'])

    def test_unverified_publish_does_not_commit_or_push(self):
        self.apply()
        with patch('charisma.repair.shutil.which',return_value='/usr/bin/gh'), patch('charisma.repair.git', wraps=actual_git) as git:
            with self.assertRaises(CharismaError): publish(self.work,'zaid3/example','Fix')
            # receipt_path is the only permitted Git read before the verification gate.
            self.assertFalse(any(c.args[1:2] in [('commit',),('push',)] for c in git.call_args_list))

    def test_trusted_checks_have_bounded_output_timeout_and_no_provider_key(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'not-for-subprocesses'}):
            check=run_check(self.root,[sys.executable,'-c','import os; assert "OPENAI_API_KEY" not in os.environ; print("x"*30000)'])
        self.assertTrue(check['passed']); self.assertLessEqual(len(check['output_tail']),16000)
        check=run_check(self.root,[sys.executable,'-c','import time;time.sleep(30)'],timeout=.05)
        self.assertFalse(check['passed']); self.assertTrue(check['timed_out'])


class ProviderTests(unittest.TestCase):
    def test_missing_configuration_makes_no_request(self):
        with patch.dict(os.environ,{},clear=True),patch('urllib.request.build_opener') as opener:
            with self.assertRaises(CharismaError): provider.request_changes({})
            opener.assert_not_called()

    def test_refusal_incomplete_and_invalid_response(self):
        for value in [{'status':'incomplete'}, {'status':'completed','output':[{'type':'message','content':[{'type':'refusal'}]}]}, {'status':'completed','output':[]}]:
            with self.subTest(value=value),self.assertRaises(CharismaError): provider.parse_response(value)

    def test_request_is_bounded_structured_and_not_stored(self):
        response={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'{"changes":[]}'}]}]}
        opener=MagicMock(); opener.open.return_value.__enter__.return_value.read.return_value=json.dumps(response).encode()
        with patch.dict(os.environ,{'OPENAI_API_KEY':'fixture','CHARISMA_MODEL':'operator-selected-model'}),patch('urllib.request.build_opener',return_value=opener):
            self.assertEqual(provider.request_changes({'files':[]}),{'changes':[]})
        request=opener.open.call_args.args[0]; payload=json.loads(request.data)
        self.assertEqual(request.full_url,'https://api.openai.com/v1/responses')
        self.assertFalse(payload['store']); self.assertTrue(payload['text']['format']['strict'])
        self.assertEqual(opener.open.call_args.kwargs['timeout'],60)
        self.assertIsNone(provider.NoRedirect().redirect_request(None,None,302,'',{},'https://untrusted.invalid'))


if __name__ == '__main__': unittest.main()
