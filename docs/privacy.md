# What Charisma records

The browser monitor sends only an enumerated event code, an enumerated error category, a same-origin script basename, bounded line/column numbers, an occurrence count and a fixed page label.

It does not intentionally collect error messages, stack traces, complete page URLs, URL query strings, cookies, form values, DOM text, screenshots, user IDs or session recordings. The browser requests omit credentials. Do not put personal information in page labels or script filenames: these values can still carry information if your own naming scheme includes it.

Events are grouped in a local SQLite database. Groups inactive for 30 days are removed during ingestion or dashboard reads. Storage is capped at 5,000 groups; the dashboard loads up to 200. Counters are capped at 1,000,000. A quiet server does not run a separate timed deletion task. Operators must manage backups and any independent proxy or hosting logs.

The monitor sends at most 30 distinct reports per page load and caps each reported count at 100. Duplicate payloads are suppressed in that page. Counts are therefore observed, limited reports, not an exact count of affected visitors or every occurrence.

The server uses the connecting IP address in a bounded in-memory rate limiter. It does not put that address in event records, and bundled HTTP access logging is disabled. A reverse proxy still sees network metadata and may log it. Configure retention and request limits there; forwarded IP headers are not trusted by this server.

The public site key identifies an installation. It is not a secret or proof of event authenticity. The separate dashboard token is required to read and acknowledge reports. The UI holds it in memory for the current tab and clears it on disconnect/reload. It does not use localStorage or cookies for that token.

Local scan reports contain paths, hashes and findings. Fix plans contain replacement source. Runner state and worktrees retain project material until the operator removes it. Keep all of these private and outside public repositories.

When explicitly enabled, model planning sends selected source and findings to OpenAI. The independent audit sends the original and proposed files in a separate request. Requests set `store: false`; this does not promise zero provider retention. Review the provider's applicable data policies and your own authority to share the source.

Charisma does not decide whether your particular installation meets privacy law, workplace monitoring policies or consent requirements. Configure it for your own users and environment.
