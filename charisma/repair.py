from __future__ import annotations

from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import tempfile
import time
import threading
import shutil
from collections import Counter
import uuid

from .core import (CharismaError, SOURCE_SUFFIXES, contains_secret, digest, git, head,
                   load_json, read_source, redact, require_clean_repo, safe_file, sensitive_path, write_json)
from .agents import audit, propose, platform_for_path, require_audit
from .scan import scan

BLOCKED_PARTS = {'.github', 'tests', 'test', '__tests__', 'migrations', '.git', '.charisma'}
BLOCKED_FILES = {'package.json', 'package-lock.json', 'pyproject.toml', 'setup.py', 'conftest.py'}


def editable(name: str) -> bool:
    path = Path(name)
    return not sensitive_path(name) and not BLOCKED_PARTS.intersection(path.parts) and path.name not in BLOCKED_FILES and path.suffix.lower() in SOURCE_SUFFIXES


def selection(root: Path, report: dict, ids: list[str] | None = None) -> tuple[str, list[dict], dict[str, str]]:
    commit = require_clean_repo(root)
    if report.get('schema_version') != 1 or report.get('base_commit') != commit or report.get('errors'):
        raise CharismaError('Use a complete scan of the current committed source.')
    if not isinstance(report.get('findings'), list) or any(not isinstance(f, dict) or not isinstance(f.get('path'), str) for f in report['findings']):
        raise CharismaError('Invalid scan findings.')
    eligible = [f for f in report.get('findings', []) if not f.get('external') and f.get('source') == 'charisma'
                and f.get('rule') != 'credential-pattern' and editable(f.get('path', ''))]
    if ids:
        eligible = [f for f in eligible if f.get('id') in ids]
        if set(ids) != {f['id'] for f in eligible}:
            raise CharismaError('Select supported, non-credential findings from this scan.')
    fresh = scan(root)
    valid_ids = {f['id'] for f in fresh['findings'] if f['source'] == 'charisma'}
    if fresh['errors'] or any(f.get('id') not in valid_ids for f in eligible):
        raise CharismaError('The selected findings do not match the current source.')
    files = {}
    selected = []
    for item in eligible:
        name = item['path']
        if name not in files and len(files) >= 3:
            continue
        text = read_source(root, name)
        if report.get('file_hashes', {}).get(name) != digest(text):
            raise CharismaError('The scan is stale; scan this commit again.')
        if contains_secret(text):
            raise CharismaError('A selected file may contain credentials. Review and remove the exposure locally first.')
        if len(text.encode()) > 30_000:
            continue
        files[name] = text
        selected.append(item)
    if not files:
        raise CharismaError('No supported findings can be prepared automatically from this report.')
    return commit, selected, files


def bundle(commit: str, findings: list[dict], files: dict[str, str], proposed: dict, strategy: str) -> dict:
    if set(proposed) != {'changes'} or not isinstance(proposed['changes'], list) or len(proposed['changes']) > 3:
        raise CharismaError('Invalid change set.')
    changes = []
    seen = set()
    for change in proposed['changes']:
        if not isinstance(change, dict) or set(change) != {'path', 'content', 'reason'}:
            raise CharismaError('Invalid change entry.')
        name, content, reason = change['path'], change['content'], change['reason']
        if not isinstance(name, str) or name not in files or name in seen or not editable(name):
            raise CharismaError('The plan attempted to change an unselected or protected file.')
        if not isinstance(content, str) or not content or len(content.encode()) > 60_000 or '\x00' in content:
            raise CharismaError('Replacement content is missing or exceeds the limit.')
        if not isinstance(reason, str) or len(reason) > 1000 or contains_secret(content) or contains_secret(reason):
            raise CharismaError('Proposed content failed the sensitive-data or size checks.')
        seen.add(name)
        if content == files[name]:
            continue
        changes.append({'path': name, 'before_sha256': digest(files[name]), 'after_sha256': digest(content),
                        'content': content, 'reason': reason})
    if not changes:
        raise CharismaError('No code change was proposed. The findings still need review.')
    selected = [{'rule': f['rule'], 'path': f['path']} for f in findings if f['path'] in seen]
    return {'schema_version': 1, 'base_commit': commit, 'strategy': strategy,
            'changes': changes, 'targets': selected, 'status': 'proposed'}


class LanguageTag(HTMLParser):
    def __init__(self):
        super().__init__()
        self.start = None
        self.language = None
    def handle_starttag(self, tag, attrs):
        if tag == 'html' and self.start is None:
            self.start = (self.getpos(), self.get_starttag_text())
            self.language = dict(attrs).get('lang')


def language_plan(root: Path, report: dict, language: str) -> dict:
    if not re.fullmatch(r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*', language):
        raise CharismaError('Supply a language tag such as en or en-GB that matches the page.')
    ids = [f['id'] for f in report.get('findings', []) if f.get('rule') == 'html-language' and not f.get('external')]
    if not ids:
        raise CharismaError('No missing document-language findings were found.')
    commit, findings, files = selection(root, report, ids[:3])
    proposed = []
    for name, text in files.items():
        parser = LanguageTag(); parser.feed(text)
        if parser.start is None:
            continue
        (line, column), tag = parser.start
        start = sum(len(s) for s in text.splitlines(keepends=True)[:line - 1]) + column
        replacement = None
        attributes = re.finditer(r'([^\s=/>]+)(?:\s*=\s*(?:"[^"]*"|\x27[^\x27]*\x27|[^\s>]+))?', tag[5:-1])
        for attribute in attributes:
            if attribute.group(1).lower() == 'lang':
                left, right = attribute.span()
                replacement = tag[:5 + left] + f'lang="{language}"' + tag[5 + right:]
                break
        if replacement is None:
            replacement = re.sub(r'^(<html)(?=\s|>)', rf'\1 lang="{language}"', tag, count=1, flags=re.I)
        proposed.append({'path': name, 'content': text[:start] + replacement + text[start + len(tag):],
                         'reason': f'Set the document language to the operator-selected value {language}.'})
    return bundle(commit, findings, files, {'changes': proposed}, 'document-language')


def model_plan(root: Path, report: dict, ids: list[str] | None, allow_model: bool, platform: str = 'auto') -> dict:
    if not allow_model:
        raise CharismaError('Use --allow-model to send selected source files and findings to the configured model provider.')
    candidates = [f for f in report.get('findings', []) if not f.get('external') and f.get('rule') != 'credential-pattern' and editable(f.get('path','')) and (not ids or f.get('id') in ids)]
    if not candidates:
        raise CharismaError('No supported findings are available for the specialist.')
    chosen = platform_for_path(candidates[0]['path']) if platform == 'auto' else platform
    selected_ids = [f['id'] for f in candidates if platform_for_path(f['path']) == chosen]
    if ids and set(ids) != set(selected_ids):
        raise CharismaError('Choose findings from one platform per plan. Other platforms get separate specialists.')
    if not selected_ids:
        raise CharismaError('No supported findings match this platform.')
    commit, findings, files = selection(root, report, selected_ids)
    context = {'findings': findings, 'files': [{'path': p, 'content': t} for p, t in files.items()]}
    plan = bundle(commit, findings, files, propose(context, chosen), 'model-proposal')
    plan['platform'] = chosen
    plan['audit'] = audit(plan, files, chosen)
    plan['agents'] = ['scout', chosen + '_specialist', 'independent_auditor']
    return plan


def validate_plan(root: Path, plan: dict) -> None:
    if plan.get('schema_version') != 1 or plan.get('base_commit') != require_clean_repo(root):
        raise CharismaError('The plan does not match the clean current commit.')
    require_audit(plan)
    changes = plan.get('changes')
    if not isinstance(changes, list) or not 1 <= len(changes) <= 3:
        raise CharismaError('A plan must contain one to three existing source-file changes.')
    seen = set()
    for change in changes:
        if not isinstance(change, dict):
            raise CharismaError('Invalid change entry.')
        name, content = change.get('path'), change.get('content')
        if not isinstance(name, str) or name in seen or not editable(name):
            raise CharismaError('Protected, duplicate or invalid change path.')
        seen.add(name)
        current = read_source(root, name)
        if sensitive_path(name) or contains_secret(current) or not isinstance(content, str) or contains_secret(content):
            raise CharismaError('A file failed sensitive-data checks.')
        if not content or content == current or len(content.encode()) > 60_000 or '\x00' in content:
            raise CharismaError('Invalid replacement content.')
        if digest(current) != change.get('before_sha256') or digest(content) != change.get('after_sha256'):
            raise CharismaError('The plan hashes do not match the source and proposed content.')
    targets = plan.get('targets')
    if not isinstance(targets, list) or not targets or any(not isinstance(t, dict) or t.get('path') not in seen or not isinstance(t.get('rule'), str) for t in targets):
        raise CharismaError('The plan must identify the findings it intends to resolve.')
    baseline = scan(root)
    valid = {(f['rule'], f['path']) for f in baseline['findings'] if f['rule'] != 'credential-pattern'}
    if baseline['errors'] or any((t['rule'], t['path']) not in valid for t in targets) or {t['path'] for t in targets} != seen:
        raise CharismaError('Repair targets must match actual supported findings in every changed file.')
    if plan.get('strategy') == 'document-language':
        for change in changes:
            parser = LanguageTag(); parser.feed(change['content'])
            if not isinstance(parser.language, str):
                raise CharismaError('Offline repairs may only set the document language.')
            expected = language_plan(root, baseline, parser.language)
            match = next((item for item in expected['changes'] if item['path'] == change['path']), None)
            if match is None or match['content'] != change['content']:
                raise CharismaError('The offline plan contains changes beyond its document-language rule.')


def receipt_path(worktree: Path) -> Path:
    value = Path(git(worktree, 'rev-parse', '--git-path', 'charisma-receipt.json'))
    return value if value.is_absolute() else worktree / value


def apply_plan(root: Path, plan: dict, destination: Path) -> dict:
    root, destination = root.resolve(), destination.absolute()
    validate_plan(root, plan)
    if destination.exists() or destination.is_symlink() or destination.resolve().is_relative_to(root):
        raise CharismaError('Choose a new worktree directory outside the source repository.')
    branch = 'charisma/fix-' + uuid.uuid4().hex[:12]
    git(root, 'worktree', 'add', '-b', branch, str(destination), plan['base_commit'])
    baseline = scan(root)
    files = []
    for change in plan['changes']:
        path = safe_file(destination, change['path'])
        mode = path.stat().st_mode & 0o777
        path.write_text(change['content'], encoding='utf-8')
        files.append({'path': change['path'], 'sha256': change['after_sha256'], 'mode': mode})
    receipt = {'schema_version': 1, 'branch': branch, 'base_commit': plan['base_commit'],
               'files': files, 'targets': plan['targets'], 'baseline': baseline['findings'],
               'audit': plan.get('audit'), 'agents': plan.get('agents', ['scout', 'language_rule']),
               'base_branch': git(root, 'branch', '--show-current'), 'verified': False, 'checks': []}
    write_json(receipt_path(destination), receipt)
    return {'branch': branch, 'worktree': str(destination), 'status': 'awaiting_verification'}


def unchanged_candidate(worktree: Path, receipt: dict) -> None:
    if git(worktree, 'branch', '--show-current') != receipt['branch'] or not receipt['branch'].startswith('charisma/fix-'):
        raise CharismaError('This is not the recorded Charisma branch.')
    if head(worktree) != receipt['base_commit']:
        raise CharismaError('The worktree commit changed; prepare a new plan.')
    expected = {item['path'] for item in receipt['files']}
    changed = set(git(worktree, 'diff', '--name-only', '-z', receipt['base_commit']).split('\x00'))
    changed.discard('')
    if changed != expected or git(worktree, 'ls-files', '--others', '--exclude-standard'):
        raise CharismaError('The worktree contains unexpected or missing changes.')
    for item in receipt['files']:
        path = safe_file(worktree, item['path'])
        if digest(read_source(worktree, item['path'])) != item['sha256'] or path.stat().st_mode & 0o777 != item['mode']:
            raise CharismaError('A proposed file changed after preparation.')


def run_check(worktree: Path, argv: list[str], timeout: int = 300, container_image: str | None = None) -> dict:
    if not argv or any(not isinstance(s, str) or '\x00' in s for s in argv):
        raise CharismaError('Supply a valid test command.')
    env = {k: v for k, v in os.environ.items() if k in {'PATH', 'LANG', 'LC_ALL', 'SYSTEMROOT', 'TMPDIR', 'TEMP', 'TMP'}}
    env['CI'] = 'true'
    command = list(argv)
    container_name = None
    if container_image:
        if not re.fullmatch(r'[A-Za-z0-9./:_-]+@sha256:[0-9a-f]{64}',container_image):
            raise CharismaError('Use a pre-pulled test image pinned by its sha256 digest.')
        if not shutil.which('docker'):
            raise CharismaError('Docker is required for the configured isolated tests.')
        container_name = 'charisma-test-' + uuid.uuid4().hex[:16]
        command = ['docker','run','--name',container_name,'--rm','--pull=never','--network=none','--read-only','--cap-drop=ALL',
                   '--security-opt=no-new-privileges','--pids-limit=128','--memory=2g','--cpus=2',
                   '--user',f'{os.getuid()}:{os.getgid()}','--tmpfs','/tmp:rw,nosuid,size=256m',
                   '--mount',f'type=bind,src={worktree.resolve()},dst=/work','--workdir','/work',container_image,*argv]
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=worktree, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=os.name != 'nt')
    tail = bytearray()
    def drain():
        try:
            while chunk := process.stdout.read(4096):
                tail.extend(chunk)
                if len(tail) > 16_000:
                    del tail[:-16_000]
        except (OSError, ValueError):
            pass
    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name != 'nt':
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait()
    if container_name:
        subprocess.run(['docker','rm','--force',container_name],capture_output=True,timeout=15,env=env)
    reader.join(timeout=2)
    if reader.is_alive() and os.name != 'nt':
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        reader.join(timeout=2)
    if not reader.is_alive():
        process.stdout.close()
    log = redact(bytes(tail).decode('utf-8', errors='replace'))
    return {'command': argv, 'passed': process.returncode == 0 and not timed_out,
            'returncode': process.returncode, 'timed_out': timed_out, 'seconds': round(time.monotonic() - started, 2), 'output_tail': log}


def verify(worktree: Path, commands: list[str], trust_tests: bool, container_image: str | None = None) -> dict:
    if not trust_tests or not commands:
        raise CharismaError('Choose project test commands and pass --trust-tests. Run only trusted code in a disposable environment.')
    receipt = load_json(receipt_path(worktree))
    receipt['verified'] = False
    receipt['checks'] = []
    write_json(receipt_path(worktree), receipt)
    unchanged_candidate(worktree, receipt)
    for command in commands:
        outcome = run_check(worktree, shlex.split(command), container_image=container_image)
        receipt['checks'].append(outcome)
        write_json(receipt_path(worktree), receipt)
        if not outcome['passed']:
            return receipt
    unchanged_candidate(worktree, receipt)
    result = scan(worktree)
    if result['errors'] or any(item['path'] not in result['file_hashes'] for item in receipt['files']):
        raise CharismaError('The verification rescan was incomplete.')
    remaining = {(f['rule'], f['path']) for f in result['findings']}
    before = Counter((f['rule'], f['path']) for f in receipt['baseline'])
    after = Counter((f['rule'], f['path']) for f in result['findings'])
    receipt['new_findings'] = [{'rule': key[0], 'path': key[1], 'count': count} for key, count in (after - before).items()]
    receipt['remaining_targets'] = [t for t in receipt['targets'] if (t['rule'], t['path']) in remaining]
    receipt['verified'] = not receipt['remaining_targets'] and not receipt['new_findings']
    write_json(receipt_path(worktree), receipt)
    return receipt


def publish(worktree: Path, repository: str, title: str) -> str:
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise CharismaError('Use a GitHub repository in owner/name form.')
    if not shutil.which('gh'):
        raise CharismaError('Install and authenticate the GitHub CLI before publishing. No commit or push was made.')
    receipt = load_json(receipt_path(worktree))
    if not receipt.get('base_branch'):
        raise CharismaError('The source was on a detached commit. Choose a base branch and prepare a new plan.')
    if receipt.get('verified') is not True or not receipt.get('checks') or not all(c.get('passed') is True for c in receipt['checks']):
        raise CharismaError('The candidate must pass its configured checks and target rescan before publishing.')
    unchanged_candidate(worktree, receipt)
    remote = git(worktree, 'remote', 'get-url', 'origin')
    expected = {f'https://github.com/{repository}', f'https://github.com/{repository}.git', f'git@github.com:{repository}.git'}
    if remote not in expected:
        raise CharismaError('The origin remote does not match the requested GitHub repository.')
    # Both commands use the operator's existing Git/GitHub identity. No identity is invented.
    git(worktree, 'add', '--', *(item['path'] for item in receipt['files']))
    git(worktree, 'commit', '-m', title)
    git(worktree, 'push', '--set-upstream', 'origin', receipt['branch'])
    body = 'Charisma prepared this change in a separate worktree.\n\nConfigured checks passed, and the selected built-in findings no longer appear. This is not a complete security assessment. Review the diff and normal CI before merging.\n\nChecks:\n'
    body += '\n'.join('- ' + redact(' '.join(c['command'])) for c in receipt['checks'])
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', encoding='utf-8') as file:
        file.write(body); file.flush()
        result = subprocess.run(['gh', 'pr', 'create', '--draft', '--repo', repository, '--head', receipt['branch'],
                                 '--base', receipt['base_branch'], '--title', title, '--body-file', file.name], cwd=worktree, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise CharismaError('The branch was pushed but the draft PR was not created. Check GitHub CLI authentication and open the PR from that branch.')
    return result.stdout.strip()
