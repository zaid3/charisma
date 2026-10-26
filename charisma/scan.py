from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import plistlib
from urllib.parse import unquote, urlsplit

from .core import (CharismaError, IGNORED_DIRS, MAX_FILES, TEXT_SUFFIXES, SECRET_PATTERNS,
                   digest, head, load_json, read_source, redact, safe_file, sensitive_path)


def finding(rule: str, path: str, line: int, title: str, description: str,
            category: str = 'accessibility', severity: str = 'medium', confidence: str = 'high') -> dict:
    return {'id': digest(f'{rule}:{path}:{line}')[:16], 'rule': rule, 'path': path,
            'line': max(1, line), 'title': title, 'description': description,
            'category': category, 'severity': severity, 'confidence': confidence,
            'source': 'charisma', 'status': 'needs_review'}


class MarkupChecks(HTMLParser):
    def __init__(self, path: str):
        super().__init__(convert_charrefs=True)
        self.path = path
        self.findings: list[dict] = []
        self.document = False
        self.title_text = ''
        self.in_title = False
        self.inputs: list[tuple[dict, int, bool]] = []
        self.labels: set[str] = set()
        self.label_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        attrs = dict(attrs)
        line = self.getpos()[0]
        if tag == 'html':
            self.document = True
            if not (attrs.get('lang') or '').strip():
                self.findings.append(finding('html-language', self.path, line, 'Document language is missing',
                    'Set the document language to the language actually used on this page.'))
        if tag == 'title':
            self.in_title = True
        if tag == 'label':
            self.label_depth += 1
            if attrs.get('for'):
                self.labels.add(attrs['for'])
        if tag == 'img' and 'alt' not in attrs:
            self.findings.append(finding('image-alt', self.path, line, 'Image has no alt attribute',
                'Describe meaningful images; use an empty alt attribute only for decorative images.'))
        if tag in {'input', 'select', 'textarea'} and (attrs.get('type') or '').lower() not in {'hidden', 'submit', 'reset', 'button', 'image'}:
            self.inputs.append((attrs, line, self.label_depth > 0))
        if tag == 'meta' and (attrs.get('name') or '').lower() == 'viewport':
            content = (attrs.get('content') or '').lower()
            if re.search(r'user-scalable\s*=\s*(?:no|0)\b', content) or re.search(r'maximum-scale\s*=\s*(?:1(?:\.0)?|0(?:\.\d+)?)\s*(?:,|$)', content):
                self.findings.append(finding('zoom-disabled', self.path, line, 'Viewport restricts zoom',
                    'Allow people to enlarge content. Check the rendered page after changing viewport settings.'))

    def handle_endtag(self, tag: str) -> None:
        if tag == 'title':
            self.in_title = False
        if tag == 'label':
            self.label_depth = max(0, self.label_depth - 1)

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_text += data

    def finish(self) -> list[dict]:
        if self.document and not self.title_text.strip():
            self.findings.append(finding('page-title', self.path, 1, 'Page title is missing or empty',
                'Add a title that describes the page. Client-rendered titles need a browser check.', confidence='medium'))
        for attrs, line, wrapped in self.inputs:
            if not wrapped and not attrs.get('aria-label') and not attrs.get('aria-labelledby') and not attrs.get('title') and attrs.get('id') not in self.labels:
                self.findings.append(finding('input-label', self.path, line, 'Form control has no static label',
                    'Connect a visible label or an accessible name. Confirm dynamic markup in a browser.', confidence='medium'))
        return self.findings


def scan_text(path: str, text: str) -> list[dict]:
    findings = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if any(pattern.search(line) for pattern in SECRET_PATTERNS):
            findings.append(finding('credential-pattern', path, line_number, 'Possible credential in source',
                'Review locally. If a real credential was exposed, revoke or rotate it; deleting a line is not enough.',
                'security', 'high', 'medium'))
        if Path(path).suffix.lower() in {'.js', '.jsx', '.ts', '.tsx'}:
            if re.search(r'\beval\s*\(|\bnew\s+Function\s*\(', line):
                findings.append(finding('dynamic-code', path, line_number, 'Dynamic code execution needs review',
                    'Trace the input to this call. Untrusted input must not be executed as code.', 'security', 'high', 'medium'))
            if re.search(r'\b(?:innerHTML|outerHTML)\s*=|dangerouslySetInnerHTML\s*=', line):
                findings.append(finding('html-sink', path, line_number, 'HTML insertion needs review',
                    'Check data flow and sanitisation. This pattern alone does not prove an XSS vulnerability.', 'security', 'medium', 'medium'))
    suffix = Path(path).suffix.lower()
    native_patterns = [
        ('android-webview-file-access', r'setAllowUniversalAccessFromFileURLs\s*\(\s*true\s*\)|allowUniversalAccessFromFileURLs\s*=\s*true', 'WebView allows broad file-origin access'),
        ('android-mixed-content', r'MIXED_CONTENT_ALWAYS_ALLOW', 'WebView permits mixed HTTP content'),
    ]
    if suffix in {'.kt', '.java'}:
        for rule, pattern, title in native_patterns:
            for match in re.finditer(pattern, text):
                findings.append(finding(rule, path, text.count('\n', 0, match.start()) + 1, title,
                    'Review the WebView configuration and required content. Validate changes with Android tests.', 'security', 'high', 'medium'))
    if Path(path).name == 'AndroidManifest.xml':
        for match in re.finditer(r'android:usesCleartextTraffic\s*=\s*[\"\x27]true[\"\x27]', text):
            findings.append(finding('android-cleartext', path, text.count('\n', 0, match.start()) + 1,
                'Android manifest permits cleartext traffic', 'Check the release manifest and endpoint requirements before changing transport policy.', 'security', 'medium', 'medium'))
    if suffix == '.plist':
        try:
            data = plistlib.loads(text.encode())
            ats = data.get('NSAppTransportSecurity', {}) if isinstance(data, dict) else {}
            if isinstance(ats, dict) and ats.get('NSAllowsArbitraryLoads') is True:
                findings.append(finding('ios-arbitrary-loads', path, 1, 'iOS transport policy allows arbitrary loads',
                    'Review transport exceptions against real endpoints. Verify changes with Xcode and device testing.', 'security', 'medium', 'high'))
        except Exception:
            # Binary, malformed and non-plist files are outside this XML check.
            findings.append(finding('ios-plist-parse', path, 1, 'Property list could not be parsed',
                'Validate this file with plutil or Xcode. The transport-policy check did not run.', 'configuration', 'low', 'medium'))
    if suffix in {'.html', '.htm'}:
        parser = MarkupChecks(path)
        parser.feed(text)
        parser.close()
        findings.extend(parser.finish())
    return findings


def scan(root: Path) -> dict:
    root = root.resolve()
    if not root.is_dir():
        raise CharismaError('Project directory does not exist.')
    findings, skipped, errors = [], [], []
    hashes = {}
    visited = 0
    exhausted = False
    def walk_error(error):
        errors.append('A directory could not be read; this report is incomplete.')
    for folder, directories, files in os.walk(root, followlinks=False, onerror=walk_error):
        directories[:] = sorted(d for d in directories if d not in IGNORED_DIRS and not Path(folder, d).is_symlink())
        for filename in sorted(files):
            visited += 1
            if visited > MAX_FILES:
                errors.append('File limit reached; this report is incomplete.')
                exhausted = True
                break
            path = Path(folder, filename)
            name = path.relative_to(root).as_posix()
            if sensitive_path(name) or path.is_symlink():
                skipped.append({'path': name, 'reason': 'sensitive file or symbolic link'})
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES:
                skipped.append({'path': name, 'reason': 'unsupported file type'})
                continue
            try:
                text = read_source(root, name)
            except (CharismaError, OSError) as exc:
                skipped.append({'path': name, 'reason': str(exc)[:150]})
                continue
            hashes[name] = digest(text)
            findings.extend(scan_text(name, text))
        if exhausted:
            break
    return {'schema_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
            'base_commit': head(root), 'scope': str(root), 'mode': 'local_static',
            'files_scanned': len(hashes), 'file_hashes': hashes, 'skipped': skipped,
            'errors': errors, 'findings': findings,
            'coverage': ['Selected credential patterns', 'JavaScript execution and HTML-insertion patterns',
                         'Static HTML language, title, image, form-label and zoom checks',
                         'Selected Android WebView/manifest and iOS XML transport-policy checks'],
            'limitations': ['Not a penetration test or assurance of security.',
                            'Rendered accessibility, business logic and runtime behaviour require separate testing.']}


def import_sarif(report: dict, source: Path, root: Path) -> dict:
    data = load_json(source)
    if data.get('version') != '2.1.0' or not isinstance(data.get('runs'), list):
        raise CharismaError('Expected a SARIF 2.1.0 report.')
    additions = []
    try:
        for run in data['runs']:
            driver = run.get('tool', {}).get('driver', {}).get('name', 'external')
            results = run.get('results', [])
            if not isinstance(results, list):
                raise ValueError()
            for result in results:
                if len(additions) >= 2_000:
                    raise CharismaError('SARIF result limit reached.')
                physical = next(iter(result.get('locations', [])), {}).get('physicalLocation', {})
                uri = physical.get('artifactLocation', {}).get('uri', '')
                if not isinstance(uri, str):
                    raise ValueError()
                decoded = unquote(uri)
                if urlsplit(decoded).scheme or urlsplit(decoded).netloc or sensitive_path(decoded):
                    raise CharismaError('SARIF locations must be non-sensitive relative source paths.')
                path = safe_file(root, decoded)
                if not path.is_file():
                    raise CharismaError('SARIF location does not exist in this project.')
                message = result.get('message', {}).get('text', 'Imported finding')
                item = finding(str(result.get('ruleId', 'external'))[:100], decoded,
                               int(physical.get('region', {}).get('startLine', 1)),
                               redact(str(message))[:200], 'Imported result; rerun the original scanner after remediation.',
                               'security', {'error':'high', 'warning':'medium', 'note':'low'}.get(result.get('level'), 'medium'), 'external')
                item['source'] = redact(str(driver))[:100]
                item['external'] = True
                additions.append(item)
    except (AttributeError, TypeError, ValueError, KeyError, StopIteration):
        raise CharismaError('Malformed SARIF result or location.') from None
    report['findings'].extend(additions)
    report['coverage'].append(f'Imported {len(additions)} SARIF findings; the external scanner was not run by Charisma.')
    return report


def markdown(report: dict) -> str:
    lines = ['# Charisma report', '', f"Files scanned: {report['files_scanned']}",
             f"Findings to review: {len(report['findings'])}", '',
             'This report covers the listed checks. An empty result does not establish that a site is secure.', '',
             '| Severity | Finding | Location |', '| --- | --- | --- |']
    def cell(value: str) -> str:
        return redact(value).replace('|', '\\|').replace('\n', ' ').replace('<', '&lt;').replace('>', '&gt;')
    for item in report['findings']:
        lines.append(f"| {cell(item['severity'])} | {cell(item['title'])} | {cell(item['path'])}:{item['line']} |")
    lines += ['', '## Coverage', ''] + ['* ' + cell(s) for s in report['coverage']]
    if report['errors']:
        lines += ['', '## Incomplete checks', ''] + ['* ' + cell(s) for s in report['errors']]
    lines += ['', f"Skipped files: {len(report['skipped'])}. See the JSON report for paths and reasons.", '']
    return '\n'.join(lines)
