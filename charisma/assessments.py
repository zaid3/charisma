"""Import real ZAP evidence without labelling automated checks as a full pentest."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from .core import CharismaError, digest, redact


def import_zap(path: Path, target: str) -> dict:
    if path.stat().st_size>10_000_000:raise CharismaError('Assessment input exceeds the size limit.')
    parsed=urlsplit(target)
    if parsed.scheme not in {'http','https'} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise CharismaError('Use the exact assessed origin without credentials or a query.')
    origin=f'{parsed.scheme}://{parsed.netloc}'
    data=path.read_bytes();raw=json.loads(data)
    if not isinstance(raw,dict) or not isinstance(raw.get('site'),list):raise CharismaError('Expected a ZAP JSON report.')
    findings=[]
    for site in raw['site']:
        if not isinstance(site,dict) or not isinstance(site.get('alerts',[]),list):raise CharismaError('Invalid ZAP site report.')
        reported=urlsplit(site.get('@name',''))
        if f'{reported.scheme}://{reported.netloc}'!=origin:raise CharismaError('A report site is outside the declared assessment origin.')
        for alert in site.get('alerts',[]):
            if len(findings)>=5000:raise CharismaError('Assessment finding limit reached.')
            if not isinstance(alert,dict):raise CharismaError('Invalid ZAP alert.')
            code=str(alert.get('riskcode','0'))
            if code not in {'0','1','2','3'}:raise CharismaError('Unsupported alert risk code.')
            findings.append({'id':str(alert.get('pluginid',''))[:80], 'title':redact(str(alert.get('name',alert.get('alert','Finding'))))[:300],
                'severity':{'0':'informational','1':'low','2':'medium','3':'high'}[code],
                'confidence':str(alert.get('confidence','unknown'))[:40],
                'cause_status':'Scanner observation requiring verification; root cause is not established automatically.',
                'recommendation':redact(str(alert.get('solution','Review the original scanner evidence.')))[:1500]})
    return {'assessment_type':'imported_automated_dynamic_scan','target_origin':origin,'source':'OWASP ZAP','source_sha256':digest(data),
            'scanner_version':str(raw.get('@version','unknown'))[:40],'reported_at':str(raw.get('@generated','unknown'))[:100],
            'findings':findings,'full_manual_pentest_completed':False,
            'limitations':['The scanner output alone does not establish complete security.','Authenticated workflows, business logic and native applications need separate scoped assessment.','The original report supplies evidence; this import does not execute a scanner.']}


def assessment_markdown(report: dict) -> str:
    def clean(value):return str(value).replace('<','&lt;').replace('>','&gt;').replace('|','\\|').replace('\n',' ')
    lines=['# Charisma security assessment','',f"Target origin: {report['target_origin']}",f"Source evidence SHA-256: {report['source_sha256']}",'','This report summarises an actual automated scan. It is not a complete manual penetration test.','', '| Severity | Finding | Confidence |','| --- | --- | --- |']
    lines += [f"| {f['severity']} | {clean(f['title'])} | {clean(f['confidence'])} |" for f in report['findings']]
    lines += ['', '## Limits', '']+['* '+v for v in report['limitations']]
    return '\n'.join(lines)+'\n'
