# amp-governance-ui

The **Governance UI** for the [Agent Memory Protocol](https://github.com/mthamil107/agent-memory-protocol).
A server-rendered Starlette + HTMX + Tailwind app that gives operators a
human-in-the-loop view over memories produced by AMP-conformant stores.

## Screens

1. **Pending Approvals** (`/`) — every memory awaiting HITL review, with a
   structured diff against current state and approve/reject buttons.
2. **Memory Health Dashboard** (`/health-dashboard`) — counts, staleness %,
   contradiction-pair drift, and type-coverage breakdown.
3. **Audit Log** (`/audit`) — filterable + paginated view of every operation;
   exportable as JSON or CSV.
4. **Co-memorize Bulk Review** (`/co-memorize`) — forget / merge candidates
   surfaced from heuristics, with a bulk-apply form.
5. **Approval Patterns** (`/patterns`) — clusters of repeated approval
   decisions, with "auto-allow?" recommendations and one-click acceptance.

## Run

```
python -m amp_ui
```

Environment variables:

* `AMP_UI_DB_PATH` — path to the sqlite-vec database (default: `./amp-cli.db`).
* `AMP_UI_AGENT_ID` — agent scope (default: `default`).
* `AMP_UI_HOST` — bind host (default: `127.0.0.1`).
* `AMP_UI_PORT` — bind port (default: `8765`).
* `AMP_UI_TOKEN` — optional bearer token. When set, every request must carry
  `Authorization: Bearer <token>` or the `amp_ui_session=<token>` cookie.
  Strongly recommended for any non-loopback bind.
* `AMP_UI_CSRF_SECRET` — base64-encoded HMAC secret (must decode to at least
  16 raw bytes) used to sign CSRF tokens. When unset, a fresh random secret
  is generated per-process, which invalidates every browser session across
  restarts. **Pin this in production** so cookies survive restarts; rotating
  it logs everyone out (intentional). Generate one with:

  ```
  python -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
  ```

  Then export it before launching the UI:

  ```
  export AMP_UI_CSRF_SECRET=<that-value>
  ```

  If the variable is set but not valid base64, or decodes to fewer than 16
  bytes, the process exits with a clear error rather than silently falling
  back to weak randomness.

The UI reads the same SQLite file the `SqliteVecStore` adapter writes to —
integration is via the shared file, not a network call.

## License

Functional Source License 1.1, Apache-2.0 Future License (FSL-1.1-ALv2).
Source-available, with an automatic relicensing to Apache-2.0 two years after
each release. See `LICENSE` for the full text.
