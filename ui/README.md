# memorywire-governance-ui

The **Governance UI** for [memorywire](https://github.com/mthamil107/memorywire).
A server-rendered Starlette + HTMX + Tailwind app that gives operators a
human-in-the-loop view over memories produced by memorywire-conformant stores.

## Screens

1. **Pending Approvals** (`/`) Ã¢â‚¬â€ every memory awaiting HITL review, with a
   structured diff against current state and approve/reject buttons.
2. **Memory Health Dashboard** (`/health-dashboard`) Ã¢â‚¬â€ counts, staleness %,
   contradiction-pair drift, and type-coverage breakdown.
3. **Audit Log** (`/audit`) Ã¢â‚¬â€ filterable + paginated view of every operation;
   exportable as JSON or CSV.
4. **Co-memorize Bulk Review** (`/co-memorize`) Ã¢â‚¬â€ forget / merge candidates
   surfaced from heuristics, with a bulk-apply form.
5. **Approval Patterns** (`/patterns`) Ã¢â‚¬â€ clusters of repeated approval
   decisions, with "auto-allow?" recommendations and one-click acceptance.

## Run

```
python -m memorywire_ui
```

Environment variables:

* `MEMORYWIRE_UI_DB_PATH` Ã¢â‚¬â€ path to the sqlite-vec database (default: `./memorywire-cli.db`).
* `MEMORYWIRE_UI_AGENT_ID` Ã¢â‚¬â€ agent scope (default: `default`).
* `MEMORYWIRE_UI_HOST` Ã¢â‚¬â€ bind host (default: `127.0.0.1`).
* `MEMORYWIRE_UI_PORT` Ã¢â‚¬â€ bind port (default: `8765`).
* `MEMORYWIRE_UI_TOKEN` Ã¢â‚¬â€ optional bearer token. When set, every request must carry
  `Authorization: Bearer <token>` or the `memorywire_ui_session=<token>` cookie.
  **Required** for any non-loopback bind: if `MEMORYWIRE_UI_HOST` is anything other
  than `127.0.0.1` / `localhost` / `::1` and `MEMORYWIRE_UI_TOKEN` is empty, the
  process refuses to start (exit code 1) so an unauthenticated governance UI
  can't be accidentally exposed to the public internet. Generate one with:

  ```
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```

* `MEMORYWIRE_UI_ALLOW_UNAUTHENTICATED_PUBLIC` Ã¢â‚¬â€ set to `1` to opt out of the
  public-bind safety check above. Use only when the UI sits behind another
  auth layer (e.g. a reverse proxy with mTLS, or a demo deployment that
  intentionally has no auth and is segregated to throwaway data).
* `MEMORYWIRE_UI_CSRF_SECRET` Ã¢â‚¬â€ base64-encoded HMAC secret (must decode to at least
  16 raw bytes) used to sign CSRF tokens. When unset, a fresh random secret
  is generated per-process, which invalidates every browser session across
  restarts. **Pin this in production** so cookies survive restarts; rotating
  it logs everyone out (intentional). Generate one with:

  ```
  python -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
  ```

  Then export it before launching the UI:

  ```
  export MEMORYWIRE_UI_CSRF_SECRET=<that-value>
  ```

  If the variable is set but not valid base64, or decodes to fewer than 16
  bytes, the process exits with a clear error rather than silently falling
  back to weak randomness.

The UI reads the same SQLite file the `SqliteVecStore` adapter writes to Ã¢â‚¬â€
integration is via the shared file, not a network call.

## License

Functional Source License 1.1, Apache-2.0 Future License (FSL-1.1-ALv2).
Source-available, with an automatic relicensing to Apache-2.0 two years after
each release. See `LICENSE` for the full text.
