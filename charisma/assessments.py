"""Import real ZAP evidence without labelling automated checks as a full pentest."""
import json
from pathlib import Path
from urllib.parse import urlsplit

from .core import CharismaError, digest, redact


def origin_of(value: str) -> str:
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 32 for c in value):
        raise CharismaError('Use one valid assessment origin.')
    parsed = urlsplit(value)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {'', '/'}):
        raise CharismaError('Use the exact assessed origin without credentials, path or query.')
    return f'{parsed.scheme}://{parsed.netloc}'


def import_zap(path: Path, target: str) -> dict:
    if path.stat().st_size > 10_000_000:
        raise CharismaError('Assessment input exceeds the size limit.')
    origin = origin_of(target)
    data = path.read_bytes()
    raw = json.loads(data)
    if not isinstance(raw, dict) or not isinstance(raw.get('site'), list) or not raw['site']:
        raise CharismaError('Expected a ZAP JSON report containing an assessed site.')
    findings = []
    for site in raw['site']:
        if not isinstance(site, dict) or not isinstance(site.get('alerts'), list):
            raise CharismaError('Invalid ZAP site report.')
        if origin_of(site.get('@name', '')) != origin:
            raise CharismaError('A report site is outside the declared assessment origin.')
        for alert in site['alerts']:
            if len(findings) >= 5000:
                raise CharismaError('Assessment finding limit reached.')
            if not isinstance(alert, dict):
                raise CharismaError('Invalid ZAP alert.')
            code = str(alert.get('riskcode', '0'))
            if code not in {'0', '1', '2', '3'}:
                raise CharismaError('Unsupported alert risk code.')
            findings.append({
                'id': str(alert.get('pluginid', ''))[:80],
                'title': redact(str(alert.get('name', alert.get('alert', 'Finding'))))[:300],
                'severity': {'0': 'informational', '1': 'low', '2': 'medium', '3': 'high'}[code],
                'confidence': str(alert.get('confidence', 'unknown'))[:40],
                'cause_status': 'Scanner observation requiring verification; root cause is not established automatically.',
                'recommendation': redact(str(alert.get('solution', 'Review the original scanner evidence.')))[:1500],
            })
    insights = raw.get('insights', [])
    if not isinstance(insights, list):
        raise CharismaError('Invalid assessment insights.')
    quality = []
    endpoint_count = None
    for insight in insights[:1000]:
        if not isinstance(insight, dict):
            continue
        if insight.get('key') == 'insight.endpoint.total' and insight.get('site') == origin:
            try:
                endpoint_count = max(0, min(1_000_000, int(insight.get('statistic', 0))))
            except (ValueError, TypeError):
                raise CharismaError('Invalid assessed endpoint count.') from None
        if insight.get('key') in {'insight.log.error', 'insight.network.failure'}:
            quality.append({'key': insight['key'], 'value': str(insight.get('statistic', 'unknown'))[:40],
                            'description': redact(str(insight.get('description', 'Scanner quality observation')))[:300]})
    return {
        'assessment_type': 'imported_automated_dynamic_scan', 'target_origin': origin,
        'source': 'OWASP ZAP', 'source_sha256': digest(data),
        'scanner_version': str(raw.get('@version', 'unknown'))[:40],
        'reported_at': str(raw.get('@generated', 'unknown'))[:100],
        'reported_endpoint_count': endpoint_count, 'scanner_quality_observations': quality,
        'findings': findings, 'full_manual_pentest_completed': False,
        'limitations': [
            'The scanner output alone does not establish complete security.',
            'Authenticated workflows, business logic and native applications need separate scoped assessment.',
            'The original report supplies evidence; this import does not execute or authenticate the scanner.',
        ],
    }


def assessment_markdown(report: dict) -> str:
    def clean(value):
        return str(value).replace('<', '&lt;').replace('>', '&gt;').replace('|', '\\|').replace('\n', ' ')
    lines = ['# Charisma security assessment', '',
             f"Target origin: {clean(report['target_origin'])}",
             f"Source evidence SHA-256: {report['source_sha256']}",
             f"Reported endpoint count: {report['reported_endpoint_count'] if report['reported_endpoint_count'] is not None else 'not supplied'}", '',
             'This report summarises an actual supplied automated scan report. It is not a complete manual penetration test.', '',
             '| Severity | Finding | Confidence |', '| --- | --- | --- |']
    lines += [f"| {f['severity']} | {clean(f['title'])} | {clean(f['confidence'])} |" for f in report['findings']]
    if not report['findings']:
        lines += ['', 'No alerts were included in the supplied report. This does not establish complete coverage.']
    if report['scanner_quality_observations']:
        lines += ['', '## Scanner quality observations', '']
        lines += ['* '+clean(v['description'])+': '+clean(v['value']) for v in report['scanner_quality_observations']]
    lines += ['', '## Limits', ''] + ['* '+v for v in report['limitations']]
    return '\n'.join(lines) + '\n'
