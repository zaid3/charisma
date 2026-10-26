from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
from typing import Any

MAX_FILE_BYTES = 250_000
MAX_FILES = 5_000
SOURCE_SUFFIXES = {'.html', '.htm', '.js', '.jsx', '.ts', '.tsx', '.css', '.py', '.swift', '.m', '.mm', '.kt', '.java', '.xml', '.plist'}
TEXT_SUFFIXES = SOURCE_SUFFIXES | {'.json', '.toml', '.yml', '.yaml', '.md', '.txt', '.sql'}
IGNORED_DIRS = {'.git', '.charisma', '.venv', 'venv', 'node_modules', 'dist', 'build', 'coverage', '__pycache__', '.next', 'vendor'}
SENSITIVE_NAMES = {'.npmrc', '.pypirc', 'id_rsa', 'id_ed25519', 'credentials', 'credentials.json'}
SECRET_PATTERNS = [
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(r'\bgh[pousr]_[A-Za-z0-9]{30,}\b'),
    re.compile(r'\bgithub_pat_[A-Za-z0-9_]{40,}\b'),
    re.compile(r'\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}\b'),
    re.compile(r'(?i)(?:password|api[_-]?key|client[_-]?secret|access[_-]?token)\s*[:=]\s*[\"\'][^\"\'\r\n]{12,}[\"\']'),
]


class CharismaError(Exception):
    """An actionable error that is safe to show without a stack trace."""


def digest(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def contains_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub('[REDACTED]', text)
    return text


def sensitive_path(name: str) -> bool:
    path = PurePosixPath(name)
    return any(part in SENSITIVE_NAMES or part == '.env' or
               (part.startswith('.env.') and part not in {'.env.example', '.env.template'})
               for part in path.parts) or path.suffix.lower() in {'.pem', '.key', '.p12', '.pfx', '.keystore'}


def safe_file(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or '\\' in name or '\x00' in name or any(ord(c) < 32 for c in name):
        raise CharismaError('Invalid repository path.')
    rel = PurePosixPath(name)
    if rel.is_absolute() or '..' in rel.parts or any(part in {'.git', '.charisma'} for part in rel.parts):
        raise CharismaError('Path is outside the permitted source tree.')
    root = root.resolve()
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise CharismaError('Symbolic links are outside the scan and edit scope.')
    if not current.resolve().is_relative_to(root):
        raise CharismaError('Path escapes the project root.')
    return current


def read_source(root: Path, name: str) -> str:
    path = safe_file(root, name)
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise CharismaError('Source file is missing or exceeds the size limit.')
    try:
        data = path.read_bytes()
        if b'\x00' in data:
            raise ValueError()
        return data.decode('utf-8')
    except (UnicodeDecodeError, ValueError) as exc:
        raise CharismaError('Only UTF-8 text files are supported.') from exc


def git(root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(root), *args],
                            capture_output=True, text=True, timeout=30)
    if check and result.returncode:
        raise CharismaError('Git operation failed: ' + redact(result.stderr.strip())[:300])
    return result.stdout.strip()


def head(root: Path) -> str | None:
    try:
        value = git(root, 'rev-parse', '--verify', 'HEAD')
        return value if re.fullmatch(r'[0-9a-f]{40,64}', value) else None
    except (CharismaError, OSError, subprocess.TimeoutExpired):
        return None


def require_clean_repo(root: Path) -> str:
    root = root.resolve()
    if Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != root:
        raise CharismaError('Use the Git repository root, not a subdirectory.')
    commit = head(root)
    if not commit:
        raise CharismaError('Commit the project before preparing a fix.')
    if git(root, 'status', '--porcelain', '--untracked-files=all'):
        raise CharismaError('The source repository has uncommitted files. Save the report outside it or ignore .charisma/.')
    return commit


def write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise CharismaError('Refusing to replace a symbolic-link output.')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def write_json(path: Path, value: Any) -> None:
    write_private(path, json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def load_json(path: Path, limit: int = 2_000_000) -> dict:
    if path.stat().st_size > limit:
        raise CharismaError('JSON input exceeds the size limit.')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise CharismaError('Expected a JSON object.')
    return value
