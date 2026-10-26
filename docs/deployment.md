# Production deployment and operations

This guide deploys the 0.2 release candidate as a single installation. Test it in staging with your application's real traffic patterns before live use. The repository provides software and configuration; it does not provide a server, domain, managed uptime or model account.

## Components and requirements

The monitor receives bounded telemetry and serves an authenticated dashboard. Gunicorn runs the Python WSGI application. Caddy terminates TLS and checks the service policy before forwarding protected application traffic. SQLite data stays in a persistent local directory. A repair worker runs separately with source access and its build tools.

Use a Linux host with Docker Engine and Docker Compose v2, available DNS names for the monitor and application, and an upstream application you control. The host must be able to build images and obtain TLS certificates. Reserve capacity beyond the example container limits and monitor disk space, latency and restarts.

## Configure the stack

From the repository root:

```sh
cp deploy/server.example.toml deploy/server.toml
python3 deploy/prepare.py
```

The preparation script creates private directories and four independent credentials without printing them. It preserves existing credentials when rerun. These paths are ignored by Git.

Edit `deploy/server.toml`:

```toml
public_origin = "https://monitor.example.com"
origins = ["https://app.example.com"]
site_key = "your-public-installation-key"
database = "/data/events.sqlite3"
security_database = "/data/security.sqlite3"
native_apps = ["com.example.yourapp"]
trusted_proxies = []

[services.website]
auto_block = false
threshold = 20
window_seconds = 60
block_seconds = 600
protected_networks = ["127.0.0.0/8", "::1/128"]
```

Use your exact origins. An origin has no path or trailing slash. Add only your intended native app identifiers, or leave the list empty. Add a known operator network to `protected_networks` if appropriate; this exempts it from IP blocks, not whole-service isolation.

Create `deploy/.env` with the real values:

```dotenv
MONITOR_DOMAIN=monitor.example.com
APP_DOMAIN=app.example.com
APP_UPSTREAM=your-owned-application:8080
```

`APP_UPSTREAM` is the existing application's reachable host and port. The example does not create that application. If it runs in Docker, connect it to the appropriate network or add it to Compose. If it runs elsewhere, use the permitted reachable address and secure transport where needed. Restrict direct upstream access so clients cannot bypass the gateway. Do not set the upstream to an unrelated public service.

Set the data and credential ownership to the container user on Linux:

```sh
sudo chown -R 10001:10001 deploy/secrets deploy/state deploy/caddy-data deploy/caddy-config
chmod 600 deploy/.env deploy/server.toml
```

`server.toml` must also be readable by UID 10001. For example:

```sh
sudo chown 10001:10001 deploy/server.toml
```

The `.env` file is read by Compose on the host; its owner should remain the operator invoking Compose. Use your approved secret-management process to retrieve the reader/operator tokens for authorised users. Never commit or paste them into issues, command transcripts or application code.

Validate and start:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yml config --quiet
docker compose --env-file deploy/.env -f deploy/compose.yml up --build -d
docker compose --env-file deploy/.env -f deploy/compose.yml ps
```

Point both DNS names to the proxy and permit the required HTTP/HTTPS certificate and application traffic. Visit the real HTTPS monitor URL. `/health` reports process availability; `/ready` checks event database access. Confirm TLS, ingestion, reader restrictions and one reversible control against a staging service before protecting a live route.

## Proxy behaviour and availability

Only Caddy exposes host ports 80 and 443. Its administration API is disabled. The monitor uses a private Docker network, a non-root UID, a read-only root filesystem and bounded temporary storage. No Docker socket, repository or provider key is mounted into the monitor.

The sample protected route uses service ID `website`. For another service, add an explicit policy and a separate Caddy route whose `X-Charisma-Service` header is fixed by the proxy. The proxy replaces the source-IP and gateway-authentication headers on the policy request; client-supplied headers are not policy authority.

The policy check fails closed: non-successful checks do not reach the application upstream. This makes monitor availability part of application availability. Test your recovery process and keep operator access outside the protected service. Do not claim that this single-instance example provides high availability or DDoS mitigation.

The example caps monitor bodies at 4 KB and application bodies at 5 MB. Adjust the application cap for legitimate uploads after reviewing its own limits. Caddy has header/body/idle timeouts. Additional perimeter connection and abuse controls belong in your infrastructure.

If another CDN or load balancer sits in front of Caddy, `{remote_host}` identifies that intermediary until you configure and verify trusted proxy handling. Do not enable automatic IP blocking until the gateway supplies the true client address reliably. Never trust arbitrary forwarded headers from the public internet.

For ingestion rate limits, the monitor trusts a single forwarded IP only from a peer explicitly listed in `trusted_proxies`. The default empty list sees the proxy's address and shares the per-source limit. Configure the proxy's verified fixed address or narrow private CIDR; do not use `0.0.0.0/0`. Do not add unrelated containers to that trusted network.

## Credentials

Production secrets can be supplied through `CHARISMA_ADMIN_TOKEN_FILE`, `CHARISMA_READ_TOKEN_FILE`, `CHARISMA_GATEWAY_TOKEN_FILE` and `CHARISMA_AUDIT_KEY_FILE`. Without a `_FILE` setting, the corresponding environment value is used. Compose mounts local secret files. These mounts are not an encrypted secret store.

Use different strong values for every role. Rotate operator/reader/gateway credentials by updating the relevant files and recreating affected services. A gateway rotation must be coordinated with the proxy and backend signal publishers. Old dashboard sessions must reconnect with the replacement token.

Keep the audit key stable with its database and encrypted backups. Changing it makes old HMAC entries fail verification. Plan an explicit archived history and a new database if rotating that key; do not silently discard the old history. Full host/key compromise or truncation of a valid chain is outside the protection offered by local HMAC records.

## Repair worker

Use a separate unprivileged host/account. Install Python, Git and the project's real build tools. Add GitHub CLI only if publishing draft PRs. The monitor container is not the repair worker.

Copy `examples/runner/charisma.toml`, set existing clean checkout paths and private state storage, then run:

```sh
charisma watch --config /private/charisma.toml --once
```

Start in scan mode. For repair, configure model credentials on the worker only, add real tests, set `production = true`, and enable `--allow-model --trust-tests`. Web/Android repair projects need a `test_image` pinned to a pulled SHA-256 digest. Build dependencies into that image or provide them in the candidate before execution. Tests have no network access and may write only to the candidate and temporary filesystem.

Docker access itself is privileged infrastructure access. Give it only to a dedicated worker, preferably using a suitable rootless or disposable host setup. Containers limit the test process; they do not sandbox every Git operation or the entire coordinator. Git filters and repository tooling can execute on the worker. Treat the source checkout as trusted and keep unrelated credentials off the host.

An iOS repair project may use `isolated_native_worker = true` instead of a Linux test image, with `platform = "ios"`. This flag is an operator assertion, not a Mac isolation mechanism. Supply a genuinely isolated Mac/VM, Xcode, the actual scheme and simulator. Do not provide App Store signing keys just to compile or test.

The runner polls local committed source. Your trusted synchronisation process must update it. Runs are deduplicated by project/commit/configuration. A failed model request is not automatically retried. After investigating, changing a project's `revision = 2` value is one way to request a new attempt.

The supplied systemd example starts scan mode. Replace paths/account, install through your normal server administration process and use a private environment file. On macOS, use a supervised launchd process with equivalent arguments; no launchd template is included.

## Connect worker history deliberately

The default container has no worker mount, Git binary or candidate access. Runtime monitoring and protection work without it.

`runner_state` enables the history API when the server can access the worker state. Read-only access is enough to inspect history. Pause/resume and candidate undo require writable state, access to the same absolute candidate paths, Git and compatible user permissions. Those privileges expand what a compromised monitor could affect. For controls, prefer a separate private operator-only monitor on the worker rather than mounting repositories into the publicly reachable monitor.

Pause takes effect at the next phase boundary. An active model request or test can finish. Resume does not retry an already-attempted run automatically. Undo refuses published/committed candidates or unexpected later changes.

## Operations, updates and rollback

Back up SQLite files through `charisma backup`; do not copy only the main file while live WAL writes are active. Store backups and manifests off-host with encryption and your own retention policy. Practise [restoration](recovery.md) before needing it. Gateway audit records, runner evidence and backups need operator-managed retention and disk monitoring.

For an update, review the commit and CI, build the image in staging, record its image digest and test your real integrations. Back up state, then recreate the services using the tested image. The example uses version tags and a Python base-image tag; record and pin verified image digests in your own deployment process for reproducibility. There is no automatic image updater.

Do not run old application code against a changed database schema without verifying compatibility. This release does not supply a general database migration rollback framework. A static-site pointer switch affects only an explicitly configured static release store.

## Acceptance checks for your installation

1. HTTPS works and the monitor/upstream are not directly reachable through unintended ports.
2. A real website/native error produces only the expected bounded data.
3. A reader cannot mutate controls, and public app credentials cannot submit gateway signals.
4. A temporary block/isolation affects the configured staging service only and can be reversed.
5. Backend signals carry verified source addresses; shared proxies are not accidentally blocked.
6. Your own app tests run in the intended isolation environment, and a draft PR can be reviewed.
7. Backups restore in a disposable environment; operator access survives service isolation.
8. Hosting supervision, disk alerts, retention and credential rotation have owners.

Repository CI checks fixtures and SDK builds. It does not establish these installation-specific conditions for you.
