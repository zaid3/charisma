# Security reporting

Charisma is an early pilot, not a security assurance service. Use it on projects you own or are authorised to maintain.

Please report a suspected vulnerability privately to **ahaque@atomicmail.io**. Include a minimal reproduction, affected version and expected versus observed behaviour. Do not post working credentials, customer data or sensitive exploit details in a public issue.

The repair process is intentionally bounded, but models and automated checks can miss defects. Review proposed changes and run the application's own tests. See [trust boundaries](docs/architecture.md) before enabling tests or model calls on a worker.

The bundled ingestion server needs a TLS reverse proxy and additional operational controls before internet exposure. Native app runtime monitoring is not implemented in this version.
