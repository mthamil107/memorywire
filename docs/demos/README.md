# Demo recordings

The `ui.gif` in this folder shows AMP's governance UI driving the
**diff-and-approve flow**: a human reviewer sees a pending memory,
expands the structured diff against the closest live counterpart,
clicks Approve, and the action lands in the audit log as a `remember`
row keyed by `approved_by: ui-operator`.

## Re-rendering the GIF

Both scripts are deterministic — re-running them rebuilds the demo DB
from scratch and overwrites `ui.gif`.

```bash
.venv/Scripts/python.exe docs/demos/seed_demo_db.py
.venv/Scripts/python.exe docs/demos/record_ui.py
```

The first command writes `docs/demos/demo-ui.db` (gitignored). The
second boots `amp_ui` against that DB on a free localhost port, drives
the scenario in headless Chromium via Playwright, captures PNG frames
into `docs/demos/frames/` (gitignored), then assembles them into
`docs/demos/ui.gif` via Pillow.

## Requirements

- `playwright` + `pillow` in the venv (`pip install playwright pillow`)
- Chromium for Playwright (`python -m playwright install chromium` — ~150 MB,
  cached after first install)
