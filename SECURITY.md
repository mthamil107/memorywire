# Security Policy

## Supported Versions

memorywire is in early v0 development. Only the most recent published version on PyPI
receives security fixes. Breaking changes may land between minor versions until
v1.0; consult `CHANGELOG.md` for migration guidance.

## Reporting a vulnerability

Please do **not** open a public GitHub issue for security reports. Instead,
report privately via GitHub's "Report a vulnerability" feature on the repository
Security tab, or email the maintainers at the contact listed on the project
homepage.

We aim to:

- Acknowledge receipt within 72 hours.
- Provide an initial assessment within 7 days.
- Coordinate disclosure timing with the reporter when a fix is ready.

When reporting, please include:

- A clear description of the issue and its potential impact.
- Steps to reproduce, ideally a minimal proof of concept.
- The affected memorywire version(s) and backend adapter(s) if known.

## Scope

In scope:

- The memorywire reference implementation in `src/memorywire/`.
- The governance UI in `ui/`.
- Backend adapters shipped in this repository.

Out of scope (report directly to the upstream project):

- Vulnerabilities in third-party backends (mem0, Letta, Cognee, sqlite-vec,
  Postgres+pgvector) themselves.
- Vulnerabilities in the surrounding application's authentication or transport
  security Ã¢â‚¬â€ memorywire delegates these to the host application by design.
