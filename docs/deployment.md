# Running Charisma continuously

The repository contains the software. It does not include a hosted service, paid model access, an Apple account, an Android device farm or a GitHub App installation.

Use Linux for a web/Android worker, and macOS with Xcode for a worker that verifies native iOS changes. Install the project's actual build tools. A single worker can route several configured projects, but it cannot substitute for the platform toolchains.

## First run

1. Install Charisma in a virtual environment on an isolated host.
2. Create a dedicated unprivileged account and private state directory.
3. Prepare clean local Git checkouts that the account can access.
4. Copy `examples/runner/charisma.toml` and replace its paths and tests.
5. Run `charisma watch --config /absolute/path/charisma.toml --once` in scan mode.
6. Inspect the scan and activity files before enabling repair mode.
7. Set `OPENAI_API_KEY`, `CHARISMA_MODEL` and optionally `CHARISMA_AUDIT_MODEL` in the worker's secret environment. Do not commit them.
8. Enable repair with `--allow-model --trust-tests`. This authorizes the selected source to leave the host and the configured project commands to run.

The runner needs no GitHub access for scans or local candidates. Automatic draft PRs need explicit configuration, the `--allow-publish` flag, Git commit identity and an authenticated `gh` installation. Prefer repository-scoped credentials. Never give the worker an Apple signing key merely to run static checks or simulator tests.

## Keep it running

`examples/runner/charisma.service` is a Linux systemd template. Replace its paths and account, put secrets in a file readable only by the service account, then install it through your own server administration process. The template starts scan mode. Enable model/test/publication switches only after configuring those capabilities.

On macOS, use a supervised launchd process with equivalent environment and arguments on a machine that has the necessary Xcode installation. A macOS service template is not supplied in this version.

Continuous operation depends on the host being available, the checkout being updated, credentials remaining valid and configured tests completing. The default polling interval is 15 minutes. The runner does not promise uninterrupted service or detection of every change between polls.

A run is attempted once per project/commit/configuration, including failures. Inspect blocked or interrupted runs before retrying. Updating the source commit or changing the project's configuration creates a new run; adding a `revision = 2` field to that project is an explicit way to request another attempt. Do not create an automatic retry loop that spends model credits indefinitely.

Activity is recorded in each run's `activity.json`, with summaries in `runs.sqlite3`. Scan reports and plans are private files; candidate worktrees contain the project. Use `git worktree remove /path/to/candidate` after review when you no longer need it. Remove its metadata/evidence deliberately according to your retention needs. Unmerged candidate branches are not automatically deleted.

## Website ingestion

Start `charisma serve` separately from the repair runner. It listens on localhost by default. For a real website, host it behind a TLS reverse proxy. Restrict dashboard routes to your team, cap request bodies at the edge, limit connections and apply ingestion rate limits before requests reach Python. The built-in per-IP limiter sees the proxy address unless connections come directly from visitors.

The database is single-installation storage, not a multi-tenant platform. Repeat `--origin` only for websites you intend to share that installation and event list. Do not expose the pilot HTTP server directly to the internet.

No production website, cloud service or app store is changed by following the local setup alone.
