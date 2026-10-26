"""Local triage of operator-supplied server logs. No callbacks or identity lookup."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path

from .core import CharismaError, digest


def triage(path: Path) -> dict:
    if path.stat().st_size > 5_000_000:
        raise CharismaError('Use a log slice of at most 5 MB.')
    data=path.read_bytes()
    groups={}; count=0
    for line in data.decode('utf-8').splitlines():
        if not line.strip(): continue
        count+=1
        if count > 10000: raise CharismaError('Use at most 10000 log records per report.')
        try:
            record=json.loads(line)
            source=str(ipaddress.ip_address(record['source_ip']))
            code=record['status']
            if type(code) is not int or not 100 <= code <= 599: raise ValueError()
            timestamp=datetime.fromisoformat(record['timestamp'].replace('Z','+00:00'))
            if timestamp.tzinfo is None: raise ValueError()
            stamp=timestamp.astimezone(timezone.utc).isoformat()
        except (ValueError,TypeError,KeyError,AttributeError):
            raise CharismaError(f'Invalid server-log record at nonempty line {count}. Use source_ip, numeric status and a timestamp with timezone.') from None
        group=groups.setdefault(source,{'source_ip':source,'requests':0,'statuses':Counter(),'first_seen':stamp,'last_seen':stamp})
        group['requests']+=1;group['statuses'][str(code)]+=1
        group['first_seen']=min(group['first_seen'],stamp);group['last_seen']=max(group['last_seen'],stamp)
    signals=[]
    for group in groups.values():
        statuses=group['statuses']; reasons=[]
        if statuses['401']+statuses['403'] >= 10: reasons.append('At least 10 denied or unauthenticated requests in this log slice.')
        if statuses['429'] >= 10: reasons.append('At least 10 rate-limited requests in this log slice.')
        if sum(n for status,n in statuses.items() if status.startswith('5')) >= 5: reasons.append('At least 5 server-error responses in this log slice; investigate application health.')
        if reasons:
            signals.append({**group,'statuses':dict(statuses),'observations':reasons,
                'cause':'Unconfirmed. A faulty client, shared network or abusive activity could produce these counts.',
                'potential_impact':'Possible access abuse or service disruption; the logs do not prove compromise.',
                'next_steps':['Review original server records and authentication events.','Apply proportionate temporary access or rate controls through your own gateway if corroborated.','Preserve evidence and check whether legitimate users share the source address.']})
    return {'schema_version':1,'assessment_type':'local_server_log_triage','records_reviewed':count,
            'evidence_sha256':digest(data),'signals':signals,'network_requests_made':0,
            'limitations':['Source IPs can be shared, proxied or belong to compromised systems; they do not identify a person.',
                           'Thresholds apply to the supplied log slice, not a rate model. This is not a penetration test.',
                           'No device probing, tracking program, retaliation or automatic blocking is performed.']}


def incident_markdown(report: dict) -> str:
    lines=['# Charisma incident triage','','Assessment: authorised local server logs.',f"Records reviewed: {report['records_reviewed']}",f"Evidence SHA-256: {report['evidence_sha256']}",'']
    for signal in report['signals']:
        lines.extend([f"## Source {signal['source_ip']}",f"Window: {signal['first_seen']} to {signal['last_seen']}",f"Requests observed: {signal['requests']}",''])
        lines += ['* '+reason for reason in signal['observations']]
        lines += ['', '**Cause:** '+signal['cause'], '**Potential impact:** '+signal['potential_impact'],'','Next steps:','']
        lines += ['* '+step for step in signal['next_steps']]
        lines.append('')
    if not report['signals']: lines+=['No configured threshold was reached. This does not establish that the traffic is safe.','']
    lines+=['## Limits','']+['* '+limit for limit in report['limitations']]
    return '\n'.join(lines)+'\n'
