from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from . import __version__
from .core import CharismaError, load_json, write_json
from .monitor import make_server
from .repair import apply_plan, language_plan, model_plan, publish, verify
from .scan import import_sarif, markdown, scan


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(prog='charisma', description='Observe website issues and prepare tested source changes.')
    cli.add_argument('--version', action='version', version=__version__)
    commands = cli.add_subparsers(dest='command', required=True)
    check = commands.add_parser('scan', help='Run the built-in local source checks')
    check.add_argument('project', type=Path)
    check.add_argument('--out', required=True, type=Path)
    check.add_argument('--markdown', type=Path)
    check.add_argument('--sarif', type=Path, help='Import an existing SARIF report; does not run its scanner')
    check.add_argument('--fail-on-findings', action='store_true')
    plan = commands.add_parser('plan', help='Prepare a reviewable change plan')
    plan.add_argument('project', type=Path)
    plan.add_argument('--report', required=True, type=Path)
    plan.add_argument('--out', required=True, type=Path)
    mode = plan.add_mutually_exclusive_group(required=True)
    mode.add_argument('--language', help='Offline language fix using your chosen page language')
    mode.add_argument('--allow-model', action='store_true', help='Send selected files to the configured OpenAI model')
    plan.add_argument('--platform', choices=['auto','web','ios','android'], default='auto')
    plan.add_argument('--finding', action='append', help='Select a finding ID; repeat for related findings')
    apply = commands.add_parser('apply', help='Write the plan to a new Git worktree')
    apply.add_argument('project', type=Path)
    apply.add_argument('--plan', required=True, type=Path)
    apply.add_argument('--worktree', required=True, type=Path)
    test = commands.add_parser('verify', help='Run trusted project tests and rescan the repair targets')
    test.add_argument('worktree', type=Path)
    test.add_argument('--test', action='append', required=True, help='Trusted command; repeat for multiple checks')
    test.add_argument('--trust-tests', action='store_true')
    pr = commands.add_parser('publish', help='Commit, push and open a draft PR using your existing GitHub CLI login')
    pr.add_argument('worktree', type=Path)
    pr.add_argument('--repo', required=True)
    pr.add_argument('--title', default='Resolve reviewed website findings')
    serve = commands.add_parser('serve', help='Start the pilot monitor and dashboard')
    serve.add_argument('--origin', action='append', required=True, help='Exact allowed website origin; repeat as needed')
    serve.add_argument('--site-key', required=True, help='Public installation identifier, not the dashboard secret')
    serve.add_argument('--database', type=Path, default=Path('.charisma/events.sqlite3'))
    serve.add_argument('--runner-state', type=Path, help='Connect an existing worker state directory for history and controls')
    serve.add_argument('--host', default='127.0.0.1')
    serve.add_argument('--port', type=int, default=8787)
    runner = commands.add_parser('watch', help='Poll configured checkouts with separate specialist and auditor roles')
    runner.add_argument('--config', required=True, type=Path)
    runner.add_argument('--once', action='store_true')
    runner.add_argument('--allow-model', action='store_true')
    runner.add_argument('--trust-tests', action='store_true')
    runner.add_argument('--allow-publish', action='store_true', help='Permit configured draft PR publication; never merges')
    incident = commands.add_parser('triage', help='Analyse an authorised local server log without contacting source addresses')
    incident.add_argument('--log', required=True, type=Path)
    incident.add_argument('--out', required=True, type=Path)
    incident.add_argument('--markdown', type=Path)
    return cli


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == 'triage':
            from .incidents import triage, incident_markdown
            from .core import write_private
            report = triage(args.log)
            write_json(args.out, report)
            if args.markdown:
                write_private(args.markdown, incident_markdown(report))
            print(f"Reviewed {report['records_reviewed']} local log records; {len(report['signals'])} source groups need review. No network requests were made.")
            return 0
        if args.command == 'watch':
            from .runner import watch
            return watch(args.config, args.once, args.allow_model, args.trust_tests, args.allow_publish)
        if args.command == 'scan':
            result = scan(args.project)
            if args.sarif:
                result = import_sarif(result, args.sarif, args.project)
            write_json(args.out, result)
            if args.markdown:
                from .core import write_private
                write_private(args.markdown, markdown(result))
            print(f"Scanned {result['files_scanned']} files; {len(result['findings'])} findings to review. Report: {args.out}")
            return 2 if result['errors'] else int(bool(args.fail_on_findings and result['findings']))
        if args.command == 'plan':
            report = load_json(args.report)
            result = language_plan(args.project, report, args.language) if args.language else model_plan(args.project, report, args.finding, args.allow_model, args.platform)
            write_json(args.out, result)
            print(f"Prepared {len(result['changes'])} file changes. Inspect {args.out} before applying.")
        elif args.command == 'apply':
            print(json.dumps(apply_plan(args.project, load_json(args.plan), args.worktree), indent=2))
        elif args.command == 'verify':
            result = verify(args.worktree, args.test, args.trust_tests)
            print('Configured checks and target rescan passed.' if result['verified'] else 'Verification failed. Inspect the candidate and test output.')
            for check in result['checks']:
                print(('PASS' if check['passed'] else 'FAIL') + ' ' + ' '.join(check['command']))
                if not check['passed']:
                    print(check['output_tail'])
            return 0 if result['verified'] else 1
        elif args.command == 'publish':
            print(publish(args.worktree, args.repo, args.title))
        elif args.command == 'serve':
            token = os.environ.get('CHARISMA_ADMIN_TOKEN', '')
            if not token:
                raise CharismaError('Set CHARISMA_ADMIN_TOKEN to a random secret of at least 24 characters. Keep it out of website code.')
            server = make_server(args.host, args.port, args.database, args.origin, args.site_key, token, args.runner_state)
            print(f'Charisma dashboard: http://{args.host}:{server.server_port}', flush=True)
            print('Pilot server. Use a TLS reverse proxy with access and request limits for a hosted installation.', flush=True)
            try:
                server.serve_forever()
            finally:
                server.server_close()
        return 0
    except KeyboardInterrupt:
        return 130
    except (CharismaError, OSError, ValueError, subprocess.SubprocessError) as exc:
        message = str(exc) if isinstance(exc, CharismaError) else 'Operation failed. Check file permissions, input format and required tools.'
        print('Charisma: ' + message, file=sys.stderr)
        return 2
