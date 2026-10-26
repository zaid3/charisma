"""A supervised background loop for explicitly configured local checkouts."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
import re
from pathlib import Path
import sqlite3
import time
import tomllib
import uuid

from .agents import platform_for_path
from .core import CharismaError, digest, require_clean_repo, write_json, load_json
from .repair import apply_plan, editable, model_plan, publish, verify
from .scan import scan


def read_config(path: Path) -> dict:
    if path.stat().st_size > 100_000:
        raise CharismaError('Runner configuration exceeds the size limit.')
    with path.open('rb') as stream:
        config = tomllib.load(stream)
    projects = config.get('projects')
    if not isinstance(projects,list) or not 1 <= len(projects) <= 10:
        raise CharismaError('Configure one to ten projects.')
    interval = config.get('interval_seconds', 900)
    if type(interval) is not int or not 60 <= interval <= 86400:
        raise CharismaError('Use a polling interval between 60 and 86400 seconds.')
    state = config.get('state_directory')
    if not isinstance(state,str) or not Path(state).is_absolute():
        raise CharismaError('Use an absolute state_directory outside your source checkouts.')
    names=set()
    for project in projects:
        if not isinstance(project,dict) or not isinstance(project.get('name'),str) or project['name'] in names or not 1 <= len(project['name']) <= 80:
            raise CharismaError('Each project needs a unique short name.')
        names.add(project['name'])
        if not isinstance(project.get('path'),str) or not Path(project['path']).is_absolute() or not Path(project['path']).is_dir():
            raise CharismaError('Each project path must be an existing absolute checkout directory.')
        if Path(state).resolve().is_relative_to(Path(project['path']).resolve()):
            raise CharismaError('Keep runner state outside monitored source checkouts.')
        if project.get('mode','scan') not in {'scan','repair'} or project.get('platform','auto') not in {'auto','web','ios','android'}:
            raise CharismaError('Invalid project mode or platform.')
        if config.get('production',False) and project.get('mode') == 'repair' and not project.get('test_image'):
            if project.get('platform') != 'ios' or project.get('isolated_native_worker') is not True:
                raise CharismaError('Production repair workers require a pinned test_image or an explicitly isolated iOS worker.')
        image=project.get('test_image')
        if image is not None and (not isinstance(image,str) or not re.fullmatch(r'[A-Za-z0-9./:_-]+@sha256:[0-9a-f]{64}',image)):
            raise CharismaError('Configure a test image pinned by its sha256 digest.')
        tests=project.get('tests',[])
        if not isinstance(tests,list) or any(not isinstance(t,str) or not t.strip() for t in tests) or (project.get('mode') == 'repair' and not tests):
            raise CharismaError('Repair mode requires explicit trusted test commands.')
    config['interval_seconds']=interval
    return config


@contextmanager
def runner_lock(state: Path):
    try:
        import fcntl
    except ImportError:
        raise CharismaError('The background runner currently requires Linux or macOS.') from None
    state.mkdir(parents=True, exist_ok=True)
    os.chmod(state,0o700)
    with (state/'runner.lock').open('a') as file:
        try:
            fcntl.flock(file,fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CharismaError('Another Charisma runner is using this state directory.') from None
        try:
            yield
        finally:
            fcntl.flock(file,fcntl.LOCK_UN)


@contextmanager
def cycle_lock(state: Path):
    try:
        import fcntl
    except ImportError:
        raise CharismaError('Worker controls require Linux or macOS.') from None
    state.mkdir(parents=True,exist_ok=True)
    with (state/'cycle.lock').open('a') as file:
        try:
            fcntl.flock(file,fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CharismaError('A worker cycle is active. Pause repairs and wait for it to finish before undoing a candidate.') from None
        try:
            yield
        finally:
            fcntl.flock(file,fcntl.LOCK_UN)


def assert_not_paused(state: Path, name: str):
    control=state/'controls.json'
    if control.exists() and load_json(control).get(name):
        raise CharismaError('Repairs for this project are paused by the operator.')


def run_cycle(config: dict, allow_model=False, trust_tests=False, allow_publish=False) -> list[dict]:
    state=Path(config['state_directory']); state.mkdir(parents=True,exist_ok=True)
    results=[]
    with sqlite3.connect(state/'runs.sqlite3') as db:
        os.chmod(state/'runs.sqlite3',0o600)
        db.execute('CREATE TABLE IF NOT EXISTS runs (fingerprint TEXT PRIMARY KEY, id TEXT, project TEXT, commit_sha TEXT, status TEXT, updated INTEGER, detail TEXT)')
        for project in config['projects']:
            name, root = project['name'], Path(project['path'])
            fingerprint=None
            try:
                assert_not_paused(state,name)
                mode=project.get('mode','scan')
                if mode == 'repair' and (not allow_model or not trust_tests):
                    raise CharismaError('Repair mode requires --allow-model and --trust-tests on the runner.')
                if project.get('publish',False) and (not allow_publish or not project.get('repository')):
                    raise CharismaError('Automatic draft PRs require a repository and --allow-publish.')
                commit=require_clean_repo(root)
                fingerprint=digest(json.dumps({'project':project,'commit':commit,'schema':1},sort_keys=True))
                existing=db.execute('SELECT status,id FROM runs WHERE fingerprint=?',(fingerprint,)).fetchone()
                if existing:
                    results.append({'project':name,'status':'unchanged','previous_status':existing[0],'run_id':existing[1]}); continue
                run_id=uuid.uuid4().hex[:16]; folder=state/run_id; folder.mkdir(mode=0o700)
                db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?)',(fingerprint,run_id,name,commit,'scanning',int(time.time()),'')); db.commit()
                timeline=[]
                def stage(role, status, detail=''):
                    timeline.append({'role':role,'status':status,'detail':detail,'at':int(time.time())})
                    write_json(folder/'activity.json',timeline)
                    db.execute('UPDATE runs SET status=?,updated=?,detail=? WHERE fingerprint=?',(status,int(time.time()),detail,fingerprint)); db.commit()
                report=scan(root); write_json(folder/'scan.json',report)
                stage('scout','scanned',f"{len(report['findings'])} findings; {report['files_scanned']} files")
                if report['errors']:
                    raise CharismaError('Source scan was incomplete. Repair is blocked.')
                if mode == 'scan':
                    stage('coordinator','reported'); results.append({'project':name,'status':'reported','run_id':run_id}); continue
                candidates=[f for f in report['findings'] if f['rule'] != 'credential-pattern' and not f.get('external') and editable(f['path']) and (project.get('platform','auto') == 'auto' or platform_for_path(f['path']) == project['platform'])]
                if not candidates:
                    stage('coordinator','needs_review' if report['findings'] else 'no_supported_findings')
                    results.append({'project':name,'status':timeline[-1]['status'],'run_id':run_id}); continue
                platform=platform_for_path(candidates[0]['path']) if project.get('platform','auto') == 'auto' else project['platform']
                stage(platform+'_specialist','preparing')
                # One proposal and one separate audit request at most. No automatic retry loop.
                plan=model_plan(root,report,None,True,platform); assert_not_paused(state,name); write_json(folder/'plan.json',plan)
                stage('independent_auditor','approved',plan['audit']['summary'])
                worktree=folder/'candidate'; apply_plan(root,plan,worktree)
                stage('verifier','testing')
                assert_not_paused(state,name)
                receipt=verify(worktree,project['tests'],True,project.get('test_image'))
                if not receipt['verified']:
                    stage('verifier','verification_failed')
                    results.append({'project':name,'status':'verification_failed','run_id':run_id,'worktree':str(worktree)}); continue
                stage('verifier','verified')
                if project.get('publish',False):
                    assert_not_paused(state,name)
                    url=publish(worktree,project['repository'],'Charisma: resolve reviewed '+platform+' findings')
                    stage('release_guard','draft_pr_opened',url)
                else:
                    stage('release_guard','awaiting_human_review',str(worktree))
                results.append({'project':name,'status':timeline[-1]['status'],'run_id':run_id,'worktree':str(worktree)})
            except Exception as exc:
                # Do not persist raw provider responses, tracebacks or environment values.
                detail=str(exc)[:600] if isinstance(exc,CharismaError) else 'Run failed. Check local permissions, tool availability and the configured project.'
                if fingerprint:
                    db.execute('UPDATE runs SET status=?,updated=?,detail=? WHERE fingerprint=?',('blocked',int(time.time()),detail,fingerprint)); db.commit()
                results.append({'project':name,'status':'blocked','detail':detail})
        # Retain the recent summary index. Worktree/evidence cleanup remains explicit.
        db.execute('DELETE FROM runs WHERE updated < ? AND status IN (?,?)',(int(time.time())-90*86400,'reported','no_supported_findings'))
    return results


def watch(path: Path, once=False, allow_model=False, trust_tests=False, allow_publish=False) -> int:
    config=read_config(path)
    with runner_lock(Path(config['state_directory'])):
        while True:
            with cycle_lock(Path(config['state_directory'])):
                outcomes=run_cycle(config,allow_model,trust_tests,allow_publish)
            print(json.dumps(outcomes),flush=True)
            if once:
                return int(any(r['status'] in {'blocked','verification_failed'} for r in outcomes))
            time.sleep(config['interval_seconds'])
