# Security reporting

Charisma 0.2 is a production deployment candidate. It provides bounded maintenance and protection controls for projects you own or are authorised to manage. It does not certify that an application is secure or replace its own testing and incident response.

Report suspected vulnerabilities privately to **ahaque@atomicmail.io**. Include the affected commit/version, a minimal reproduction, expected behaviour and observed impact. Do not publish credentials, customer data or sensitive exploit details in a public issue. No response-time service-level agreement or bug bounty is currently offered.

Before deployment, read the [trust boundaries](docs/architecture.md), [deployment guide](docs/deployment.md) and [data handling documentation](docs/privacy.md). Keep the development server private. The production bundle separates monitor and worker privileges and uses a TLS gateway, private role credentials and scoped controls; your installation still needs its own access restrictions and acceptance tests.

Only use trusted project checkouts on isolated workers. Containerised tests do not sandbox every coordinator or Git operation. Do not give a public monitor repository write access, signing keys, a Docker socket or provider credentials. Models, scanners and tests can miss defects, so review draft PRs before merging.

Security assessments in this repository run against disposable, network-isolated fixtures. They are not permission to test unrelated services, access someone else's device, identify a person behind an address or retaliate. Runtime telemetry has no authority to execute code or trigger protection actions.

There is no separate long-term support branch or automated update service in this release. Review changes and CI, record tested image digests, back up state and validate upgrades in staging.
