from __future__ import annotations

from collections import OrderedDict
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from urllib.parse import urlsplit

from .core import CharismaError
from .history import recent_runs, pause_project, undo_candidate

CODES = {
    'ios-error': ('runtime', 'Reported iOS application error'),
    'android-error': ('runtime', 'Reported Android application error'),
    'script-error': ('runtime', 'Browser script error'),
    'promise-rejection': ('runtime', 'Unhandled promise rejection'),
    'missing-alt': ('ux', 'Images without alt attributes'),
    'missing-label': ('ux', 'Form controls without accessible names'),
    'horizontal-overflow': ('ux', 'Page content extends beyond the viewport'),
    'missing-language': ('ux', 'Document language is missing'),
}
ERROR_NAMES = {'Error', 'TypeError', 'ReferenceError', 'SyntaxError', 'RangeError', 'URIError', 'EvalError', 'Unknown'}
ASSETS = {'/': ('dashboard.html', 'text/html; charset=utf-8'), '/dashboard.js': ('dashboard.js', 'text/javascript; charset=utf-8'),
          '/dashboard.css': ('dashboard.css', 'text/css; charset=utf-8'), '/monitor.js': ('monitor.js', 'text/javascript; charset=utf-8')}


def valid_origin(value: str) -> str:
    if not re.fullmatch(r'https?://(?:\[[0-9a-fA-F:]+\]|[A-Za-z0-9.-]+)(?::[0-9]{1,5})?/?', value):
        raise CharismaError('Supply an exact website origin without a path, credentials or wildcard.')
    parts = urlsplit(value)
    try:
        parts.port
    except ValueError:
        raise CharismaError('The origin port is invalid.') from None
    if parts.scheme not in {'http', 'https'} or not parts.netloc or parts.username or parts.password or parts.query or parts.fragment or parts.path not in {'', '/'}:
        raise CharismaError('Supply an exact website origin without a path, credentials or wildcard.')
    if parts.scheme == 'http' and parts.hostname not in {'localhost', '127.0.0.1', '::1'}:
        raise CharismaError('Public website origins must use HTTPS.')
    return f'{parts.scheme}://{parts.netloc}'


def validate_event(value: dict) -> dict:
    keys = {'code', 'error', 'file', 'line', 'column', 'count', 'page'}
    if not isinstance(value, dict) or set(value) != keys or not isinstance(value.get('code'), str) or value.get('code') not in CODES:
        raise CharismaError('Unsupported event schema.')
    if not isinstance(value['error'], str) or value['error'] not in ERROR_NAMES or not isinstance(value['file'], str) or not re.fullmatch(r'[A-Za-z0-9_.-]{0,100}', value['file']):
        raise CharismaError('Only an error category and script basename may be recorded.')
    if not isinstance(value['page'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', value['page']):
        raise CharismaError('Use a fixed page label, not a URL or visitor data.')
    for name, minimum, maximum in [('line', 0, 1_000_000), ('column', 0, 1_000_000), ('count', 1, 100)]:
        if type(value[name]) is not int or not minimum <= value[name] <= maximum:
            raise CharismaError('Invalid event count or location.')
    return value


class EventStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        with self.connect() as connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE, code TEXT, error TEXT,
                file TEXT, line INTEGER, col INTEGER, page TEXT, count INTEGER,
                first_seen INTEGER, last_seen INTEGER, reviewed INTEGER DEFAULT 0)''')
        os.chmod(path, 0o600)

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def record(self, event: dict) -> None:
        validate_event(event)
        identity = {k: v for k, v in event.items() if k != 'count'}
        fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        now = int(time.time())
        with self.lock, self.connect() as connection:
            connection.execute('DELETE FROM events WHERE last_seen < ?', (now - 30 * 86400,))
            connection.execute('''INSERT INTO events
                (fingerprint,code,error,file,line,col,page,count,first_seen,last_seen) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(fingerprint) DO UPDATE SET count=MIN(events.count+excluded.count,1000000),
                last_seen=excluded.last_seen, reviewed=0''',
                (fingerprint, event['code'], event['error'], event['file'], event['line'], event['column'], event['page'], event['count'], now, now))
            connection.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY last_seen DESC,id DESC LIMIT 5000)')

    def list(self) -> list[dict]:
        with self.lock, self.connect() as connection:
            connection.execute('DELETE FROM events WHERE last_seen < ?', (int(time.time()) - 30 * 86400,))
            connection.row_factory = sqlite3.Row
            rows = connection.execute('SELECT * FROM events ORDER BY reviewed,last_seen DESC,id DESC LIMIT 200').fetchall()
        return [{**dict(row), 'kind': CODES[row['code']][0], 'title': CODES[row['code']][1]} for row in rows]

    def review(self, event_id: int) -> bool:
        with self.lock, self.connect() as connection:
            return bool(connection.execute('UPDATE events SET reviewed=1 WHERE id=?', (event_id,)).rowcount)


class RateLimit:
    def __init__(self):
        self.entries = OrderedDict()
        self.lock = threading.Lock()
    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            start, count = self.entries.pop(key, (now, 0))
            if now - start >= 60:
                start, count = now, 0
            self.entries[key] = (start, count + 1)
            while len(self.entries) > 1000:
                self.entries.popitem(last=False)
            return count < 60


def make_server(host: str, port: int, database: Path, origins: list[str], site_key: str, admin_token: str, runner_state: Path | None = None):
    # Development entry point; production uses Gunicorn with the same WSGI application.
    from wsgiref.simple_server import make_server as wsgi_server, WSGIRequestHandler
    from .web import Application, Settings
    class QuietHandler(WSGIRequestHandler):
        def log_message(self, *args):
            pass
    return wsgi_server(host,port,Application(Settings(database,origins,site_key,admin_token,runner_state=runner_state)),handler_class=QuietHandler)
