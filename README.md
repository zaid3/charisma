# Charisma

**A small team of agents for keeping your web, iOS and Android projects in better shape.**

Charisma brings website reports, source checks and reviewed repair proposals into one workflow. A platform specialist prepares a change. A separate auditor challenges it. The verifier runs the tests you choose, and the release guard can open a draft pull request for you to review.

Created and maintained by **Ahtashamul Haque**.

[![Checks](https://github.com/zaid3/charisma/actions/workflows/checks.yml/badge.svg)](https://github.com/zaid3/charisma/actions/workflows/checks.yml)

## Where the project stands

This is the first working pilot. The local scanner, browser monitor, authenticated dashboard, separate specialist/auditor calls, worktree repairs and background runner are implemented. The browser script runs inside a website; the repair agents run beside its source repository.

Charisma cannot find every bug or guarantee that a project is secure. Agent agreement is a review signal, not proof. Tests, platform builds and human review still matter.

| Component | Available now | Boundary |
| --- | --- | --- |
| Website monitor | Browser error categories, rejected promises, selected rendered UX checks | No session replay, source maps or automatic runtime-to-source diagnosis |
| Web specialist | Proposals for selected HTML and JavaScript findings | Requires a configured model and source access |
| iOS specialist | Swift/Objective-C/plist source support, selected XML transport-policy checks | No native crash SDK; real app verification requires your Mac, Xcode and tests |
| Android specialist | Kotlin/Java/XML source support, selected WebView and manifest checks | No native crash SDK; real app verification requires your Android build tools and tests |
| Independent auditor | A separate model call reviews original and proposed code | Can still miss defects; an approval never bypasses tests |
| Verifier | Runs operator-selected commands, rescans targets and rejects new built-in findings | Executes trusted project code on its host, not in a security sandbox |
| Background runner | Polls configured checkouts and records each role's work | Must be hosted and configured to operate continuously |
| Release guard | Opens a draft GitHub PR after verification when explicitly enabled | Never merges, deploys or publishes to an app store |

## Start locally

Python 3.11 or later and Git are required. The runtime has no third-party Python dependencies.

```sh
git clone https://github.com/zaid3/charisma.git
cd charisma
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
charisma --help
```

You can also run `python -m charisma` directly from this checkout without installing it. Windows users can use `.venv\Scripts\Activate.ps1`; the background runner currently supports Linux and macOS.

## Connect your website

Generate a dashboard secret locally. Keep it out of your website and Git history:

```sh
export CHARISMA_ADMIN_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
charisma serve \
  --origin https://your-website.example \
  --site-key your-public-installation-key
```

Open `http://127.0.0.1:8787` and enter that token. The dashboard displays real received reports; it starts empty.

For a hosted installation, put the server behind a TLS reverse proxy with connection limits, request-size limits and dashboard access controls. The bundled HTTP server is for local use and pilots, not a hardened public ingestion platform. See [deployment](docs/deployment.md).

Add this script to a site you control, using your hosted monitor address:

```html
<script defer src="https://YOUR-MONITOR/monitor.js"
  data-endpoint="https://YOUR-MONITOR/ingest"
  data-site-key="your-public-installation-key"
  data-page="checkout"></script>
```

The site key is public. **Never put the dashboard token or an API key in the script.** Configure each exact website origin with `--origin`. HTTP origins are allowed only for local development.

The script checks the page after load. For client-side navigation, call `window.Charisma?.scan()` after the new view renders. `window.Charisma?.stop()` removes listeners and stops reports. Deploy it only after considering your site's consent and privacy requirements.

The dashboard lets you search, filter, refresh and acknowledge reports. Acknowledging a report does not fix it. Another occurrence reopens it.

## Scan a project

```sh
charisma scan /path/to/project \
  --out /tmp/charisma-report.json \
  --markdown /tmp/charisma-report.md
```

Use `--fail-on-findings` in CI if you want a nonzero exit code when findings exist. An incomplete scan returns exit code 2. Ordinary findings are review items; some patterns can be harmless in context.

An existing SARIF 2.1.0 file can be included with `--sarif path/to/report.sarif`. Importing it does not run that scanner. Imported findings are displayed but are not automatically repaired in this version.

## Prepare, review and verify a change

Start with a clean, committed Git checkout. Keep reports outside it, or add `.charisma/` to the project's ignore file.

An offline repair is available for missing HTML document language. Supply the language the page actually uses:

```sh
charisma plan /path/to/project --report /tmp/charisma-report.json \
  --language en-GB --out /tmp/charisma-plan.json
```

For a model-assisted proposal, configure an OpenAI API key and a model available to your account that supports Responses structured outputs. The key is read from `OPENAI_API_KEY`; choose the model with `CHARISMA_MODEL`. Set `CHARISMA_AUDIT_MODEL` to use a different model for review, or omit it to use the same model in an independent request.

```sh
charisma plan /path/to/project --report /tmp/charisma-report.json \
  --platform web --allow-model --out /tmp/charisma-plan.json
```

Use `ios` or `android` for the other specialists. Select particular findings by repeating `--finding FINDING_ID`. Each plan is limited to three existing source files from one platform. It makes at most one proposal request and one audit request, without automatic retries. Model usage may incur provider charges.

Only selected source files and finding descriptions are sent to the model provider. The auditor receives original and proposed source in a new request, without the specialist's reasoning. A refusal, incomplete response, rejected audit or invalid change blocks the plan. Review the saved plan before applying it.

```sh
charisma apply /path/to/project --plan /tmp/charisma-plan.json \
  --worktree /path/to/charisma-candidate

charisma verify /path/to/charisma-candidate \
  --test "npm test" --test "npm run build" --trust-tests
```

Replace those commands with your project's actual checks. No checks are silently skipped. For iOS, use your real `xcodebuild test` command on macOS. For Android, use appropriate Gradle tests, lint and device tests. The agent does not invent an app scheme, emulator or signing configuration.

Changes go into a new Git worktree and branch. Your original working files stay untouched. Verification fails if a target remains, a configured command fails, the candidate changes unexpectedly, or new built-in findings appear.

To publish a verified candidate, install and authenticate the GitHub CLI first:

```sh
charisma publish /path/to/charisma-candidate \
  --repo your-account/your-project --title "Improve reviewed website behaviour"
```

This uses your existing Git identity and GitHub access. It commits only the prepared files, pushes the candidate branch and opens a **draft** pull request. Review the diff and your normal CI before merging.

## Run an agent team in the background

Copy [the runner configuration](examples/runner/charisma.toml), then set real absolute paths and test commands. Start with scan mode:

```sh
charisma watch --config /path/to/charisma.toml --once
charisma watch --config /path/to/charisma.toml
```

Repair mode requires `--allow-model --trust-tests`. Automatic draft PR creation additionally requires `publish = true`, the correct repository in configuration, and `--allow-publish`.

The runner checks local committed source; it does **not** fetch or pull remote changes. Update the checkout through your own trusted CI or deployment process. Each configured project/commit/configuration is attempted once, including failures, to prevent repeat spending. A new commit or changed project configuration creates a new run. A mixed repository can have separate entries for web, iOS and Android.

Each run records its scan, approved plan, role activity and worktree. Failed model calls and rejected audits block the run. Evidence and candidate worktrees remain available for inspection. Use a service manager on an always-on host to keep it running; see [deployment](docs/deployment.md). Nothing becomes continuously hosted simply by creating the GitHub repository.

## Agent responsibilities

| Role | Responsibility | Who checks its work |
| --- | --- | --- |
| Scout | Collects bounded source findings | Specialist reviews context; report records scope |
| Web / iOS / Android specialist | Proposes a small platform-specific repair | Independent auditor |
| Independent auditor | Challenges correctness, security and scope | Verifier tests the approved candidate; human reviews the diff |
| Verifier | Runs trusted checks and compares scan results | Release guard checks the recorded candidate and outcomes |
| Release guard | Permits a draft PR only after the gates pass | Repository CI and the maintainer before merge |
| Coordinator | Routes configured projects and records progress | Persistent run history and explicit operator configuration |

The platform specialist and auditor use model calls. Scouting, verification, release checks and scheduling are deterministic Python components. They do not pretend to be additional intelligent models.

## Development

```sh
python -m unittest discover -s tests -v
node --test tests/monitor.test.cjs
npm install
npx playwright install chromium
npm run test:browser
```

CI runs the Python suite, SDK tests, package checks and desktop/mobile browser tests. No API key is needed for CI. Provider and audit boundaries are tested with fixtures; a paid live model run, an actual iOS app build, Android app build and authenticated draft-PR publication are separate integration checks requiring your configured environment.

See [architecture and trust boundaries](docs/architecture.md), [privacy](docs/privacy.md), and [security reporting](SECURITY.md).

## Licence

[Apache License 2.0](LICENSE). This permits commercial reuse subject to the licence terms. Hosted services, support and custom integrations can be offered separately; this repository does not include a billing system.
