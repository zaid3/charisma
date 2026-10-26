"""Authenticated operator controls over recorded local maintenance runs."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
import time

from .core import CharismaError, git, load_json, write_json
from .repair import receipt_path, unchanged_candidate


def recent_runs(state: Path | None) -> dict:
    if state is None:
        return {'enabled':False,'runs':[],'message':'Start the dashboard with --runner-state to view worker activity.'}
    database=state/'runs.sqlite3'
    if not database.is_file():
        return {'enabled':True,'runs':[],'message':'No worker runs have been recorded yet.'}
    controls=load_json(state/'controls.json') if (state/'controls.json').exists() else {}
    with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as connection:
        connection.row_factory=sqlite3.Row
        rows=connection.execute('SELECT id,project,commit_sha,status,updated,detail FROM runs ORDER BY updated DESC LIMIT 100').fetchall()
    runs=[]
    for row in rows:
        item=dict(row)
        if not re.fullmatch(r'[0-9a-f]{16}', item['id']):
            continue
        folder=state/item['id']
        activity=folder/'activity.json'
        timeline=[]
        if activity.is_file() and not activity.is_symlink() and activity.stat().st_size < 200_000:
            value=json.loads(activity.read_text())
            if isinstance(value,list): timeline=value[-50:]
        item['timeline']=timeline
        item['paused']=bool(controls.get(item['project'],False))
        item['can_undo']=item['status'] in {'awaiting_human_review','verification_failed','blocked'} and (folder/'candidate').is_dir()
        runs.append(item)
    return {'enabled':True,'runs':runs,'message':'Recorded maintenance activity. Active commands may finish before a pause takes effect.'}


def lookup_run(state: Path, run_id: str) -> dict:
    if not re.fullmatch(r'[0-9a-f]{16}', run_id):
        raise CharismaError('Invalid run identifier.')
    database=state/'runs.sqlite3'
    if not database.is_file():
        raise CharismaError('No worker history is available.')
    with sqlite3.connect(database) as connection:
        connection.row_factory=sqlite3.Row
        row=connection.execute('SELECT * FROM runs WHERE id=?',(run_id,)).fetchone()
    if row is None:
        raise CharismaError('Run not found.')
    return dict(row)


def pause_project(state: Path, run_id: str, paused: bool) -> dict:
    run=lookup_run(state,run_id)
    path=state/'controls.json'
    controls=load_json(path) if path.exists() else {}
    controls[run['project']]=paused
    write_json(path,controls)
    return {'project':run['project'],'paused':paused}


def undo_candidate(state: Path, run_id: str) -> dict:
    # Uses the same lock as an individual work cycle, preventing a race with apply/verify.
    from .runner import cycle_lock
    with cycle_lock(state):
        run=lookup_run(state,run_id)
        if run['status'] not in {'awaiting_human_review','verification_failed','blocked'}:
            raise CharismaError('Only an unpublished, idle candidate can be undone here.')
        folder=state/run_id
        worktree=folder/'candidate'
        if folder.is_symlink() or worktree.is_symlink() or not worktree.resolve().is_relative_to(state.resolve()):
            raise CharismaError('Candidate path is outside this worker state.')
        receipt=load_json(receipt_path(worktree))
        unchanged_candidate(worktree,receipt)
        git(worktree,'restore','--source',receipt['base_commit'],'--staged','--worktree','--',*(item['path'] for item in receipt['files']))
        receipt['verified']=False;receipt['rolled_back']=True
        write_json(receipt_path(worktree),receipt)
        activity=folder/'activity.json'
        timeline=json.loads(activity.read_text()) if activity.exists() else []
        timeline.append({'role':'human_operator','status':'candidate_undone','detail':'Restored only the recorded candidate files. Original source and deployed services were not changed.','at':int(time.time())})
        write_json(activity,timeline)
        with sqlite3.connect(state/'runs.sqlite3') as connection:
            connection.execute('UPDATE runs SET status=?,updated=?,detail=? WHERE id=?',('candidate_undone',int(time.time()),'Candidate changes restored to their base commit.',run_id))
        return {'status':'candidate_undone'}
