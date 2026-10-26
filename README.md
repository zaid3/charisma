# Charisma

**Monitoring, reviewed repairs and scoped protection for web, iOS and Android projects.**

Charisma helps maintain applications you own or are authorised to manage. It brings runtime reports, source checks, small repair proposals, independent review and operational controls into one workflow. You can see what happened, review the evidence and decide whether to accept a change.

Created and maintained by **Ahtashamul Haque**.

[![Checks](https://github.com/zaid3/charisma/actions/workflows/checks.yml/badge.svg)](https://github.com/zaid3/charisma/actions/workflows/checks.yml)
[![Production candidate](https://github.com/zaid3/charisma/actions/workflows/production.yml/badge.svg)](https://github.com/zaid3/charisma/actions/workflows/production.yml)
[![Dynamic assessment](https://github.com/zaid3/charisma/actions/workflows/assessment.yml/badge.svg)](https://github.com/zaid3/charisma/actions/workflows/assessment.yml)

## Release status

**0.2.0rc1 is a production deployment candidate.** The repository includes a deployable monitor, TLS gateway configuration, native reporting libraries, a supervised repair worker, recovery tools and integration tests. Hosting, application integration and release acceptance remain specific to your installation. Creating this repository does not start a hosted service.

Charisma does not promise to find every bug, identify every attack or automatically repair every application. It keeps repairs small and records the checks used to assess them. The dashboard shows received data, rather than simulated activity.

## What is included

| Capability | Implemented behaviour | Integration needed |
| --- | --- | --- |
| Website observation | Browser error categories, rejected promises and selected rendered usability checks | Add the browser script to an authorised website |
| Native observation | Swift and Android Java libraries for explicit, bounded error reports | Call the library from your app's existing error handling |
| Source analysis | Selected HTML, JavaScript, iOS transport-policy and Android WebView/manifest checks; SARIF import | Give the worker a clean local checkout |
| Platform specialists | Separate web, iOS and Android repair instructions | Configure a compatible OpenAI model and key |
| Independent audit | A fresh model request reviews original and proposed source | Optionally choose a different audit model |
| Verification | Operator-selected tests, target rescan and rejection of new built-in findings | Supply actual project checks and platform toolchains |
| Draft PRs | Verified candidate branches can become draft GitHub pull requests | Configure Git identity, `gh` and repository access |
| Background work | Polling, duplicate-run prevention, stage history and pause/resume | Run on an available, supervised worker |
| Gateway protection | Temporary service-specific IP blocks and manual service isolation | Route the protected service through the gateway |
| Trusted incident signals | Optional automatic blocks after repeated backend-reported authentication failures | Instrument your backend; public telemetry cannot trigger a block |
| Database isolation | PostgreSQL restrictive row policies for selected tenant scopes | Apply and test policies against your own schema |
| Recovery | Unpublished candidate undo, verified SQLite backups and static-site release switching | Connect the relevant worker state, database or static release root |
| Security assessment | Real ZAP scans against an isolated CI fixture; import of existing scoped ZAP reports | Assess your actual deployment separately |

The native SDKs do not intercept every crash. Runtime reports do not automatically map themselves to source lines or trigger repair commands. Mobile store releases, arbitrary backend deployments, general reverse engineering and complete application redesign are outside this release.

## Start locally

Use Python 3.11 or later and Git. The core CLI has no third-party Python dependencies. The production server extra installs Gunicorn. Linux and macOS support the worker and recovery locks; iOS verification requires macOS with Xcode.

```sh
git clone https://github.com/zaid3/charisma.git
cd charisma
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
charisma --help
```

`python -m charisma` also works from this checkout. No model key is needed to scan source, inspect reports or try the offline HTML language repair.

Start the **development** dashboard with a locally generated operator token:

```sh
export CHARISMA_ADMIN_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
charisma serve --origin http://localhost:3000 \
  --site-key local-installation-key
```

Open `http://127.0.0.1:8787` and enter the token from your local environment. It is held in memory for the current tab and cleared on disconnect or reload. The dashboard starts empty. The built-in development server is not the production entry point.

## Production deployment

The [deployment guide](docs/deployment.md) covers Docker Compose, TLS, DNS, credentials, private networks, worker separation and upgrade checks. The included stack uses Gunicorn behind Caddy, separate credentials for each private role, a read-only container filesystem and persistent SQLite storage.

Prepare the files on your own Linux server:

```sh
cp deploy/server.example.toml deploy/server.toml
python deploy/prepare.py
```

Set your real monitor and application origins in `deploy/server.toml`. Set `MONITOR_DOMAIN`, `APP_DOMAIN` and `APP_UPSTREAM` in a private `deploy/.env` file. Follow the guide to assign directory ownership to container UID 10001, connect the application upstream and verify the configuration before starting:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yml config --quiet
docker compose --env-file deploy/.env -f deploy/compose.yml up --build -d
```

Only Caddy publishes network ports. The application must be reachable from Caddy, and direct access to the application's original upstream must be restricted if the gateway is to enforce protection. Keep an independently authenticated operator route available when isolating a service.

This stack is a single installation. It does not provide customer account registration, billing, tenant-separated dashboards, SSO, a managed service-level agreement or a distributed high-availability database.

## Connect a website

Add the script to an authorised website after deploying your monitor:

```html
<script defer src="https://monitor.example.com/monitor.js"
  data-endpoint="https://monitor.example.com/ingest"
  data-site-key="your-public-installation-key"
  data-page="checkout"></script>
```

Use the exact HTTPS website origin in the monitor's `origins` configuration. The installation key is public. Keep operator, reader, gateway and model credentials out of website code.

The script checks rendered elements after load and reports selected issues such as missing image descriptions or field labels. These checks are limited heuristics, not a complete accessibility audit. After client-side navigation, call `window.Charisma?.scan()` once the new view has rendered. `window.Charisma?.stop()` removes listeners and prevents future reports.

Reports exclude error messages, stack traces, full URLs, query strings, cookies, form values and DOM content. Use a fixed label such as `checkout`; never use a person's name, order number or email as a page label. See [privacy and retention](docs/privacy.md).

The dashboard supports search, review status, report categories, refresh and acknowledgement. Acknowledgement marks an item as reviewed; it does not claim the defect has been fixed. A later occurrence reopens the item.

## Connect iOS and Android

The [native SDK guide](docs/native-sdks.md) includes installation and code examples.

* **iOS:** the Swift package is in `sdk/ios`, supports iOS 15 or later, and provides an actor with `record(screen:category:)` and `stop()`.
* **Android:** the Java library is in `sdk/android`, supports Android API 21 or later, and provides `record(screen)` and `close()`. Kotlin apps can use the same API.

Both send explicit reports to `/ingest/native` using a configured public app identifier and installation key. Both require HTTPS, refuse redirects, bound requests and avoid automatic retries. They are not a substitute for the app's normal error handling or a full native crash-reporting service. Public app identifiers are not device attestation.

## Scan source

```sh
charisma scan /path/to/project \
  --out /private/charisma-report.json \
  --markdown /private/charisma-report.md
```

The scanner reads bounded source files and records scope, findings and incomplete reads. Use `--fail-on-findings` for a nonzero exit on findings. An incomplete scan returns exit code 2. Review findings in context: a matched pattern is not proof of an exploitable vulnerability.

Use `--sarif /private/report.sarif` to import an existing SARIF 2.1.0 report. Importing does not run its scanner. Imported findings are report-only and are not automatically repaired.

## Prepare and verify a repair

Start with a clean, committed checkout. Keep reports outside the project or ignore the project's `.charisma/` directory.

For a missing HTML document language, provide the page's actual language. This deterministic repair needs no model:

```sh
charisma plan /path/to/project --report /private/charisma-report.json \
  --language en-GB --out /private/charisma-plan.json
```

For model-assisted work, configure `OPENAI_API_KEY` and `CHARISMA_MODEL` privately on the worker. Choose a model available to your account that supports Responses structured outputs. `CHARISMA_AUDIT_MODEL` can select a different auditor model; when omitted, a separate request uses the specialist's model.

```sh
charisma plan /path/to/project --report /private/charisma-report.json \
  --platform web --allow-model --out /private/charisma-plan.json
```

Use `ios` or `android` for native projects. Repeat `--finding FINDING_ID` to select related built-in findings. A plan can modify at most three existing source files from one platform. It cannot add shell commands, modify protected test/configuration paths or authorise publication. Each plan makes at most one specialist request and one auditor request, without automatic retries. Provider usage may incur charges.

Inspect the plan, then apply it to a separate Git worktree:

```sh
charisma apply /path/to/project --plan /private/charisma-plan.json \
  --worktree /srv/candidates/my-project

charisma verify /srv/candidates/my-project \
  --test "npm test" --test "npm run build" --trust-tests \
  --container-image 'your-prepared-test-image@sha256:REPLACE_WITH_64_HEX_DIGEST'
```

Prepare and pull your own test image in advance, with the project's dependencies available. The digest above is a placeholder. Container checks run without network access, host credentials, added capabilities or a writable root filesystem. Only the candidate is mounted writable. Tests that need downloads will fail until you prepare their dependencies. See [test execution boundaries](docs/architecture.md).

Without `--container-image`, tests run on the host with a reduced environment. This is suitable only for a trusted, isolated worker. Native iOS checks need an isolated Mac with the project's actual Xcode scheme and simulator; a Linux container cannot verify an iOS app. No command is silently treated as passed.

Verification fails when a selected issue remains, a command fails, source changes unexpectedly or a new built-in finding appears. A passing result establishes only the recorded checks for that candidate.

## Agent responsibilities

| Role | Work performed | Check on its work |
| --- | --- | --- |
| Scout | Collects bounded source findings | Recorded scan scope and specialist context review |
| Web, iOS or Android specialist | Proposes a focused source change | Independent auditor receives original and proposed files |
| Independent auditor | Reviews correctness, security and scope in a fresh request | Tests and rescan must still pass |
| Verifier | Executes operator-selected checks and compares findings | Candidate hashes and release checks |
| Release guard | Allows a verified candidate to become a draft PR | Repository CI and maintainer review |
| Coordinator | Routes projects, prevents repeat runs and records stages | Persistent history and explicit configuration |

Specialists and auditors make model calls. Scouting, scheduling, verification and release checks are deterministic components. Independent requests can still share the same blind spots; agreement is not a guarantee.

## Background operation and GitHub

Copy [the runner example](examples/runner/charisma.toml), set existing absolute checkout paths, and start in scan mode:

```sh
charisma watch --config /private/charisma.toml --once
charisma watch --config /private/charisma.toml
```

Repair mode requires `--allow-model --trust-tests`. Set `production = true` for production workers: repair projects then require a pinned `test_image`, or an iOS project with `isolated_native_worker = true` on a genuinely isolated Mac.

The runner processes configured projects sequentially and attempts each project/commit/configuration once, including failed attempts. It does not pull remote repositories. Update the checkout through your trusted CI process. To retry a reviewed failure deliberately, change that project's configuration revision or source commit.

For draft PR publication, configure Git identity and authenticate GitHub CLI on the worker:

```sh
charisma publish /srv/candidates/my-project \
  --repo your-account/your-project --title "Resolve reviewed application findings"
```

Background publication also requires `publish = true`, `repository = "owner/name"` and `--allow-publish`. Charisma never merges these PRs or deploys a model-generated change. Keep signing and production release credentials outside the worker.

Continuous operation requires an available host and supervision. [A Linux systemd example](examples/runner/charisma.service) is supplied. The default polling interval is 15 minutes, configurable from 60 seconds to one day. This is scheduled maintenance, not a promise that every runtime event triggers an immediate repair.

## History, pause and recovery

Set `runner_state` in the server configuration, or use `charisma serve --runner-state /private/runner-state` locally, to connect history. The server needs the appropriate state and worktree access; the default deployment deliberately keeps the repair worker separate. The deployment guide describes the tradeoff before enabling worker controls.

History shows stages, timestamps, commits and recorded details. Pause prevents the next repair phase; an already-running request or test can finish. Resume permits future eligible work. **Undo candidate** restores only the recorded, unpublished candidate files after checking for later edits. It refuses to overwrite subsequent human work or committed candidates.

The separate [recovery guide](docs/recovery.md) covers:

* Consistent SQLite backups with checksums and integrity checks.
* Offline restoration with an expected-current checksum and a preserved pre-restore backup.
* Immutable static-site releases, atomic activation and switching back to a verified earlier version.

These are explicit operator actions. A source candidate undo, a static-site rollback and a database restore have different effects. None reverses an App Store or Play Store release.

## Gateway protection and service isolation

Configure explicit service identifiers in `server.toml`. The supplied Caddy route uses the `website` service. Additional routes must supply their own configured service identifier and the actual client IP from a trusted network boundary.

An authenticated operator can review and apply a temporary IP block, unblock an address, isolate a service or resume it from the dashboard. Leases last 30 to 3,600 seconds. Controls affect only the selected service and expire automatically when their timestamp passes. A service isolation rejects every request through that service's protected route, including legitimate traffic; keep a separate management route available.

Automatic blocking is **off by default**. When enabled, it uses repeated `auth_failure` signals submitted by your backend with a private gateway credential. Configure the threshold, observation window, duration and protected operator networks. Replayed signal IDs are ignored while retained. Ordinary server errors and public browser/native reports cannot create automatic blocks.

The gateway checks policy before forwarding a request. It is not a general web application firewall, malware detector or DDoS service. If the policy service is unavailable, the supplied gateway does not forward the protected request. Measure and plan for this availability dependency.

See the [API and control guide](docs/api.md) for exact headers and payloads. The [PostgreSQL isolation guide](docs/database-isolation.md) explains how an administrator can restrict one tenant scope without disconnecting every tenant. The SQL integration is explicit and does not discover or rewrite your database schema.

## Incident evidence and security reports

Analyse a bounded, authorised local server log without contacting source addresses:

```sh
charisma triage --log /private/server.ndjson \
  --out /private/incident.json --markdown /private/incident.md
```

Each line needs `source_ip`, integer `status` and a timezone-aware ISO timestamp:

```json
{"source_ip":"192.0.2.10","status":401,"timestamp":"2026-10-26T12:00:00Z"}
```

Reports include an evidence hash, observed counts, timestamps, possible impact, unconfirmed causes and investigation steps. An IP address identifies an observed network source, not a person. Charisma does not deploy programs onto visitors' devices, collect a suspected person's private details or retaliate.

The **Isolated dynamic assessment** workflow runs ZAP against a disposable copy of Charisma on an internal Docker network. Normal pushes use a baseline scan. Manual workflow dispatch offers an active scan of that same fixed fixture, with no arbitrary target input. The workflow retains the actual scanner evidence and rejects high-risk observations. It does not assess your live app or establish that every authenticated workflow is secure.

Import an existing authorised ZAP JSON report with:

```sh
charisma import-zap --report /private/zap.json \
  --target https://your-authorised-app.example \
  --out /private/assessment.json --markdown /private/assessment.md
```

The importer checks report scope, records the source hash and labels the result as an automated assessment. It does not execute a scanner or certify a complete manual penetration test.

## Credentials and data boundaries

| Value | Purpose | Where it belongs |
| --- | --- | --- |
| Public site key and native app ID | Identify the installation receiving telemetry | Website or native app configuration |
| Reader token | View events, history and security controls | Authorised viewer's private session |
| Operator token | View and mutate controls | Authorised operator's private session |
| Gateway token | Policy checks and trusted backend signals | Proxy/backend secret storage |
| Audit key | Authenticate the local protection history chain | Server secret storage and protected backup |
| OpenAI API key | Optional proposal and audit requests | Repair worker only |
| GitHub credentials | Optional draft PR publication | Repository-scoped worker access |

Private roles require different tokens. The monitor does not need a model key or GitHub write access. HTTP bodies are limited to 4,096 bytes. Telemetry, rate-limit storage, gateway signals and audit records have different retention rules; read [privacy](docs/privacy.md) before deployment.

## Development and verification

```sh
python -m unittest discover -s tests -v
node --test tests/monitor.test.cjs
npm ci --ignore-scripts
npx playwright install chromium
npm run test:browser
```

| CI workflow | What it exercises |
| --- | --- |
| Checks | Python 3.11/3.12/3.13, package installation, browser SDK behaviour, desktop/mobile dashboard interactions |
| Production candidate | Actual container gateway, service-scoped controls, isolated Docker checks, PostgreSQL row policies, Swift tests/iOS simulator compilation, Java tests/Android API compilation and DEX generation |
| Isolated dynamic assessment | Actual ZAP output for the disposable monitor fixture, scoped report import and severity gate |

The badges link to current results. Browser screenshots and integration reports are uploaded as short-lived workflow artifacts. Model calls use fixtures in CI; a paid live provider call is not part of these checks. SDK compilation is not evidence that your own app has been integrated, signed, tested on devices or accepted by an app store. Run installation-specific acceptance tests before exposing a live service.

## Documentation and support

* [Production deployment and operations](docs/deployment.md)
* [API, credentials and control integration](docs/api.md)
* [iOS and Android SDKs](docs/native-sdks.md)
* [Backups and recovery](docs/recovery.md)
* [PostgreSQL scope isolation](docs/database-isolation.md)
* [Architecture and trust boundaries](docs/architecture.md)
* [Privacy and retention](docs/privacy.md)
* [Security reporting](SECURITY.md) and [contribution guidance](CONTRIBUTING.md)

## Licence

[Apache License 2.0](LICENSE). It permits commercial reuse subject to its terms. Hosted services, support and custom integrations can be offered separately. This repository does not include a billing system or impose a noncommercial restriction.
