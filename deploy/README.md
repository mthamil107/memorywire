# Hosted demo Ã¢â‚¬â€ Fly.io scaffolding

This directory ships the memwire Governance UI as a public hosted demo at
`https://memwire-governance-demo.fly.dev`. The intent is a one-click "Try it
live" path from the README so newcomers see the diff-and-approve flow
without `git clone`.

## What deploys

A single Fly.io machine (`shared-cpu-1x`, 256 MB RAM) runs the
`amp-ui` container built from [`Dockerfile`](Dockerfile). Booting it
runs [`seed-on-boot.py`](seed-on-boot.py), which idempotently seeds
`/app/data/demo.db` with **2 pending approvals + 2 approved memories +
5 audit-log rows** scoped to `agent_id=demo-agent`, then execs into
`python -m memwire_ui`. The database lives on a persistent 1 GB volume
(`memwire_demo_data`) so the seeded state survives restarts.

`MEMWIRE_UI_TOKEN` gates write operations (approve / reject / co-memorize /
pattern accept). Anonymous visitors browse the read-only screens
freely; clicking an approve button returns **401**. That is the demo
contract Ã¢â‚¬â€ let the world see the workflow, but don't let randos
mutate state.

`MEMWIRE_UI_TOKEN` is also **required** by the boot guard whenever
`MEMWIRE_UI_HOST` is non-loopback (`fly.toml` binds `0.0.0.0`). If the
secret is missing the container exits with code 1 before uvicorn
starts Ã¢â‚¬â€ Fly will surface this as a deploy failure rather than
publishing an unauthenticated UI. Set
`MEMWIRE_UI_ALLOW_UNAUTHENTICATED_PUBLIC=1` only if you intentionally
front the UI with another auth layer.

## One-time setup

Run from the repository root:

```sh
fly launch --no-deploy --config deploy/fly.toml --copy-config
fly volumes create memwire_demo_data --region iad --size 1
fly secrets set \
  MEMWIRE_UI_TOKEN=$(openssl rand -hex 32) \
  MEMWIRE_UI_CSRF_SECRET=$(python -c 'import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())')
fly deploy --config deploy/fly.toml
```

If `memwire-governance-demo` is taken on Fly (app names are global), edit
the `app` field in `fly.toml` and update the "Try it live" link in
the repo `README.md`.

## Verify

```sh
fly status --config deploy/fly.toml
curl -fsS https://memwire-governance-demo.fly.dev/ | head -n 5
fly logs   --config deploy/fly.toml | grep '\[seed-on-boot\]'
```

Expect HTTP 200 on `GET /`. The Pending Approvals screen renders two
rows for `alice@acme.com`.

## Rotate the bearer token / CSRF secret

```sh
fly secrets set MEMWIRE_UI_TOKEN=$(openssl rand -hex 32)              # rolling restart, ~10s
fly secrets set MEMWIRE_UI_CSRF_SECRET=$(python -c 'import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())')
```

Setting a secret triggers a rolling redeploy automatically. Rotating
`MEMWIRE_UI_CSRF_SECRET` invalidates every active browser cookie, which
is desirable as a "log everyone out" hammer.

## Take the demo offline

```sh
fly scale count 0 --config deploy/fly.toml   # park; volume + secrets persist
fly scale count 1 --config deploy/fly.toml   # bring it back later
```

## Cost expectation

**~$0/month on the Fly free tier.** `auto_stop_machines="stop"` parks
the machine when idle; `min_machines_running=0` means we pay only for
wall-time while serving traffic. The 1 GB persistent volume stays under
Fly's 3 GB free allowance. Expect a 2Ã¢â‚¬â€œ4 s cold-start when traffic
returns after an idle period (Python + Starlette boot + SQLite WAL
attach).

## Deferred to v0.2

* Dedicated `/healthz` endpoint Ã¢â‚¬â€ the Dockerfile probes `GET /`
  currently. A 1-line route + a smoke test is the right v0.2 follow-up.
* Per-session `agent_id` scoping Ã¢â‚¬â€ the demo is hard-pinned to
  `demo-agent`.
* Read-only banner in the UI when `MEMWIRE_UI_TOKEN` is set and no session
  cookie is present, so visitors know up front that the buttons will
  401.
