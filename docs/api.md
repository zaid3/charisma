# API and control integration

Use HTTPS at the real deployment boundary. JSON bodies are limited to 4,096 bytes. Unknown telemetry fields are rejected. The monitor serves one installation; origins and native app identifiers do not create separate customer accounts.

## Routes and credentials

Private requests use `Authorization: Bearer TOKEN`. Tokens are compared without an early-exit string comparison. Use unique strong values for each role.

| Method and route | Access | Behaviour |
| --- | --- | --- |
| `GET /`, `/dashboard.js`, `/dashboard.css`, `/monitor.js` | Public | Static dashboard and monitor assets |
| `GET /health` | Public | Process health |
| `GET /ready` | Public | Event database readiness |
| `POST /ingest` | Allowed exact Origin + public site key | Accept bounded browser report; 202 on success |
| `OPTIONS /ingest` | Allowed exact Origin | Browser CORS preflight |
| `POST /ingest/native` | Allowed app ID + public site key | Accept explicit iOS/Android report; 202 on success |
| `GET /api/events` | Reader or operator | Up to 200 event groups and `can_control` |
| `POST /api/events/{id}/review` | Operator | Acknowledge a report |
| `GET /api/runs` | Reader or operator | Connected worker history |
| `POST /api/runs/{id}/pause`, `/resume`, `/undo` | Operator | Control a connected worker/candidate |
| `GET /api/security` | Reader or operator | Services, up to 200 active blocks, isolations and latest 100 audit entries |
| `POST /api/security/control` | Operator | Apply a reviewed temporary control |
| `GET /edge/check` | Gateway only | 204 if allowed; non-2xx must prevent forwarding |
| `POST /edge/signal` | Gateway only | Record a trusted backend observation; 202 on success |

The reader cannot mutate. The operator cannot impersonate the gateway. Public app identifiers and installation keys are intentionally distributable and do not prove a report is genuine. They can never authorise protection controls. Do not send private tokens in query strings.

CORS applies only to the browser ingestion endpoint. Private mutations reject an Origin that differs from configured `public_origin`. The dashboard sends bearer credentials from memory, uses no login cookie, and disables mutation controls for a reader; the server independently enforces that restriction.

## Event format

Headers for browsers:

```text
Origin: https://app.example.com
X-Charisma-Site-Key: your-public-installation-key
Content-Type: application/json
```

Native requests replace the Origin requirement with `X-Charisma-App-ID: com.example.yourapp`. The exact event fields are:

```json
{"code":"ios-error","error":"Unknown","file":"","line":0,"column":0,"count":1,"page":"checkout"}
```

Use the supplied SDK to construct reports. Codes and categories are enumerated, lengths/counts are bounded, and messages, stacks and extra fields are rejected. Native endpoints accept only `ios-error` and `android-error`; the browser endpoint rejects these codes.

Successful acceptance means the report was stored/grouped. It does not mean the issue was reproduced or repaired. A duplicate browser payload may be suppressed before it reaches the server.

## Trusted backend signals

Integrate this call in an authorised backend after its existing authentication system has determined a failure. The sample gateway performs policy checks; it does not automatically discover application authentication outcomes. Do not publish gateway credentials to browser/native clients.

```text
POST /edge/signal
Authorization: Bearer PRIVATE_GATEWAY_TOKEN
Content-Type: application/json
```

```json
{"id":"your-unique-event-id-123","service":"website","source_ip":"192.0.2.10","kind":"auth_failure"}
```

`id` is 8–80 letters, digits, underscores or hyphens and must be stable across delivery retries. Accepted kinds are `auth_failure`, `rate_limit` and `server_error`. Use the verified connection address from your backend's trusted proxy chain, not an arbitrary user-supplied header. This example IP is documentation-only.

Only repeated `auth_failure` events can create automatic blocks, and only for a service with `auto_block = true`. Duplicate IDs do not increase the count while retained. Signals use server receipt time, are retained for up to 24 hours until pruning on ingestion, and are capped at 100,000 records. Do not replay old retained events under new IDs.

Policy bounds:

| Setting | Default | Permitted range |
| --- | --- | --- |
| `threshold` | 20 | 5–1,000 failures |
| `window_seconds` | 60 | 10–3,600 seconds |
| `block_seconds` | 600 | 30–3,600 seconds |
| `auto_block` | false | Boolean |
| `protected_networks` | Loopback only | Explicit IP networks |

An active automatic block is not continuously extended by each new event. A later qualifying event after expiry may create a new block. Shared NAT, proxies, legitimate login mistakes and faulty instrumentation can produce false positives. Tune against your actual service and retain operator access.

## Gateway policy request

The trusted gateway sends:

```text
GET /edge/check
Authorization: Bearer PRIVATE_GATEWAY_TOKEN
X-Charisma-Service: website
X-Charisma-Source-IP: 192.0.2.10
```

A 204 response allows forwarding. A 403 indicates an active service isolation or IP block and includes `Retry-After`. Invalid policy, missing authentication, service errors and other non-2xx responses must not forward the request. The provided Caddy configuration applies this behaviour. Policy headers must be set by the gateway, not copied from untrusted clients.

## Operator controls

```text
POST /api/security/control
Authorization: Bearer PRIVATE_OPERATOR_TOKEN
Content-Type: application/json
```

```json
{"action":"isolate","service":"website","source_ip":"","seconds":600,"reason":"Investigating repeated errors in this service"}
```

Actions are `block`, `unblock`, `isolate` and `resume`. Supply one valid IP for block/unblock; use an empty string for isolate/resume. The exact schema always requires `seconds` between 30 and 3,600, including release actions. Reasons are 3–200 characters without control characters. Keep reasons free of personal data.

`unblock` removes only that service/address entry. `resume` removes only the service isolation. Neither clears an unrelated control. Protected operator networks prevent manual/automatic IP blocks, but do not bypass whole-service isolation. The dashboard requires review before submitting a control.

## Audit history and request limits

Protection actions form an HMAC-authenticated hash chain in `security.sqlite3`. It detects changed stored entries when verified with the original audit key. `GuardStore.verify_audit()` returns validity, records checked and the latest chain signature. Archive checkpoints separately if you need to detect removal of the end of a valid chain. This is not a tamper-proof ledger against a host administrator or key theft.

Current rate limits are 60 ingestion requests, 120 private API requests and 2,000 gateway signals per source per minute. The `/edge/check` path is not rate-limited by this counter because it is used for every protected request. Apply infrastructure capacity and connection limits. Per-source counters use HMAC values, persist across WSGI workers and are bounded to 10,000 entries. Forwarded IPs are accepted only from explicitly trusted peers.

Typical responses: 400 for invalid fields/framing, 401 for missing or wrong private credentials, 403 for denied origin/policy, 404 for unknown routes, 409 for unavailable worker/control integration, 413 for oversized application payloads, 429 for request limits, and 503 for storage/service failures. The WSGI framing layer uses 400 for invalid or oversized declared Content-Length; the reverse proxy may reject a large body before Python sees it.
