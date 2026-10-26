"""Explicit backups and bounded recovery operations for operator-controlled storage."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
import uuid

from .core import CharismaError, sensitive_path, write_json, load_json


def checksum(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def backup_sqlite(source: Path, output: Path) -> dict:
    source=source.absolute();output=output.absolute()
    if source.is_symlink() or not source.is_file() or output.exists() or output.is_symlink():
        raise CharismaError('Back up an existing database to a new private file.')
    output.parent.mkdir(parents=True,exist_ok=True)
    descriptor=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(descriptor)
    try:
        with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as origin, sqlite3.connect(output) as target:
            origin.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise CharismaError('Database integrity verification failed.')
        manifest={'schema_version':1,'kind':'sqlite','source':str(source.resolve()),'created_at':int(time.time()),'sha256':checksum(output),'bytes':output.stat().st_size}
        write_json(output.with_suffix(output.suffix+'.json'),manifest)
        return manifest
    except Exception:
        output.unlink(missing_ok=True)
        raise


def restore_sqlite(backup: Path, target: Path, expected_current_sha256: str, offline: bool) -> dict:
    target=target.absolute();backup=backup.absolute()
    if not offline:raise CharismaError('Stop the application and pass --offline before restoring its database.')
    if target.is_symlink() or backup.is_symlink() or not target.is_file() or not backup.is_file():
        raise CharismaError('Use existing regular database files.')
    manifest=load_json(backup.with_suffix(backup.suffix+'.json'))
    if manifest.get('kind')!='sqlite' or manifest.get('source')!=str(target.resolve()) or manifest.get('sha256')!=checksum(backup):
        raise CharismaError('Backup provenance or content does not match this database.')
    if expected_current_sha256!=checksum(target):raise CharismaError('The current database changed. Inspect it before restoring.')
    for suffix in ['-wal','-shm']:
        if Path(str(target)+suffix).exists():raise CharismaError('A WAL or shared-memory file is present. Close and checkpoint all database users first.')
    with sqlite3.connect(backup.as_uri()+'?mode=ro',uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise CharismaError('Backup integrity verification failed.')
    previous=target.with_name(target.name+'.before-'+uuid.uuid4().hex[:12])
    backup_sqlite(target,previous)
    with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as stream:
        temporary=Path(stream.name)
        with backup.open('rb') as original:shutil.copyfileobj(original,stream)
        stream.flush();os.fsync(stream.fileno())
    try:
        if checksum(target)!=expected_current_sha256:raise CharismaError('The database changed during preparation. Restore cancelled.')
        os.replace(temporary,target)
    finally:temporary.unlink(missing_ok=True)
    return {'restored':str(target),'previous_backup':str(previous),'sha256':checksum(target)}


@contextmanager
def release_lock(root: Path):
    import fcntl
    root.mkdir(parents=True,exist_ok=True)
    with (root/'.release.lock').open('a') as stream:
        try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise CharismaError('Another release operation is active.') from None
        try:yield
        finally:fcntl.flock(stream,fcntl.LOCK_UN)


def register_static_release(source: Path, root: Path, release: str) -> dict:
    source=source.resolve();root=root.resolve()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',release) or release in {'.','..'}:
        raise CharismaError('Use a simple release identifier.')
    if root.is_relative_to(source) or source.is_relative_to(root):raise CharismaError('Keep the built site separate from the release store.')
    files={};total=0
    for folder,dirs,names in os.walk(source,followlinks=False):
        for name in dirs:
            if Path(folder,name).is_symlink():raise CharismaError('Symbolic links are not accepted in static releases.')
        for name in names:
            path=Path(folder,name);rel=path.relative_to(source).as_posix()
            if path.is_symlink() or sensitive_path(rel) or '.git' in path.relative_to(source).parts:
                raise CharismaError('Release contains a link, Git history or sensitive file.')
            total+=path.stat().st_size
            if total>500_000_000 or len(files)>=10000:raise CharismaError('Static release exceeds the size or file limit.')
            files[rel]=checksum(path)
    if 'index.html' not in files:raise CharismaError('A static release needs index.html.')
    with release_lock(root):
        destination=root/'releases'/release
        if destination.exists():raise CharismaError('Release identifiers are immutable. Use a new identifier.')
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copytree(source,destination,symlinks=False)
        for name,expected in files.items():
            if checksum(destination/name)!=expected:raise CharismaError('Source changed while copying the release.')
        manifest={'kind':'static_web','id':release,'created_at':int(time.time()),'files':files}
        write_json(root/'manifests'/(release+'.json'),manifest)
    return {'release':release,'files':len(files),'bytes':total}


def activate_static_release(root: Path, release: str, expected_current: str) -> dict:
    root=root.resolve()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',release):raise CharismaError('Invalid release identifier.')
    with release_lock(root):
        manifest=load_json(root/'manifests'/(release+'.json'))
        directory=root/'releases'/release
        if manifest.get('id')!=release or manifest.get('kind')!='static_web' or directory.is_symlink():raise CharismaError('Release manifest does not match.')
        actual={p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
        if actual!=set(manifest['files']):raise CharismaError('Release contents changed after registration.')
        for name,expected in manifest['files'].items():
            path=directory/name
            if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()) or checksum(path)!=expected:
                raise CharismaError('Release hash verification failed.')
        current=root/'current'
        if current.exists() and not current.is_symlink():raise CharismaError('The current release pointer is not a symbolic link.')
        before=current.resolve().name if current.is_symlink() else ''
        if before!=expected_current:raise CharismaError('The active release changed. Refresh before activating another version.')
        if current.is_symlink() and current.resolve().parent!=(root/'releases').resolve():raise CharismaError('Current pointer is outside this release store.')
        temporary=root/('.switch-'+uuid.uuid4().hex)
        temporary.symlink_to(Path('releases')/release,target_is_directory=True)
        os.replace(temporary,current)
        history_path=root/'history.json';history=load_json(history_path) if history_path.exists() else {'events':[]}
        history['events'].append({'from':before,'to':release,'at':int(time.time())})
        write_json(history_path,history)
        return {'active':release,'previous':before}
