# Data collection and retention

## Browser and native reports

The browser sends an enumerated code/category, a same-origin script basename, bounded line/column numbers, an occurrence count and a fixed page label. Native libraries send a platform error code/category and a fixed screen label, with empty file and zero line/column fields.

The supplied SDKs do not intentionally collect error messages, stack traces, full URLs, queries, form values, DOM text, screenshots, user/device IDs or session recordings. Do not put personal information into labels or script filenames. Browser requests omit credentials. The Swift transport uses an ephemeral session with cookies/cache disabled. The Android SDK does not read cookies and sends an empty Cookie header; app-wide network handlers remain under the embedding application's control.

Reports are grouped in SQLite. Groups inactive for 30 days are removed during ingestion or dashboard reads. Storage is capped at 5,000 groups; the dashboard returns up to 200. Counters are capped at 1,000,000. A quiet server does not run a separate timed deletion task.

The browser reports at most 30 distinct payloads per page load and caps each payload count at 100. Native monitor instances allow at most 30 distinct reports, with duplicates suppressed. Counts represent limited observations, not exact affected-user totals or every occurrence.

## Network and protection data

Request limiting stores HMAC-derived source keys in SQLite rather than plain source IPs in event records. Keys use the private operator credential, are capped at 10,000 entries and are pruned after 120 seconds during subsequent requests. Counter windows are one minute. This is pseudonymisation, not a claim that the server or hosting provider cannot observe a connecting IP.

Gunicorn access logging and the bundled development request logs are disabled. Proxies, infrastructure, error logs and upstream applications may still record network metadata. Configure those separately. Forwarded IP headers are trusted only from explicitly configured peer networks.

Protection data has a different purpose and retention:

| Data | Stored fields | Retention |
| --- | --- | --- |
| Trusted gateway signal | Event ID, service, source IP, kind and receipt time | Pruned after 24 hours on new signals; 100,000-record cap |
| Temporary block/isolation | Service, optional source IP, expiry and reason | Ignored after expiry; expired rows pruned on new signals |
| Protection audit | Action, service, source IP where relevant, reason, timestamps and hash-chain values | Operator-managed; no automatic audit deletion |
| PostgreSQL scope control | Service, tenant UUID, expiry and reason | Expiry stops enforcement; operator manages row retention |
| PostgreSQL control history | Database login, action and previous/current scope row | Operator-managed |

Audit and control records can contain personal or sensitive security data. Do not include customer details in reasons. Restrict reader access appropriately, monitor disk space and archive/retain records according to your own obligations. Do not simply delete the middle of an audit chain; use an explicit archival/checkpoint process.

A source address is not proof of a person's identity. Charisma does not contact source addresses, send tracking programs or collect private details about suspected individuals.

## Credentials and source evidence

The dashboard stores its token only in tab memory and clears it on disconnect/reload. It does not use localStorage or cookies for authentication. Public installation keys and native app IDs are not secrets. Private reader, operator, gateway, audit, model and GitHub credentials have separate purposes.

Local source reports contain paths, hashes and findings. Repair plans include source replacements. Runner history, worktrees and test logs retain project material until removed by the operator. Bounded log redaction detects some common credential forms but cannot guarantee that arbitrary test output contains no secrets.

Explicitly enabled model requests send selected files/findings to OpenAI. The auditor receives original and proposed files separately. Requests use `store: false`; that does not promise zero provider retention. Review the applicable provider data policy and your authority to share source.

The log triage command retains source-IP evidence and aggregate counts from a bounded authorised input slice. ZAP imports retain scoped findings, recommendations, quality observations and a hash; original scanner reports may contain more sensitive material. Keep real production reports private. The public CI artifacts contain disposable fixture evidence only and expire after the configured 7 or 14 days.

## Backups and deletion

SQLite backups and static release stores are not encrypted by Charisma. Use encrypted private storage, off-host copies and a documented retention policy. Deleting a live record does not remove copies in backups, archived scanner output or hosting logs.

This software does not determine whether your particular use meets privacy law, workplace policies or consent requirements. Configure collection, access, retention and disclosures for your actual users and environment.
