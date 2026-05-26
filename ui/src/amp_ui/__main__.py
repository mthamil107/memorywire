"""``python -m amp_ui`` entry point.

Reads ``AMP_UI_DB_PATH``, ``AMP_UI_AGENT_ID``, ``AMP_UI_HOST`` and
``AMP_UI_PORT`` from the environment, builds the Starlette app via
:func:`amp_ui.app.create_app`, and hands it to ``uvicorn.run``.
"""

from __future__ import annotations

import os

import uvicorn

from amp_ui.app import create_app


def main() -> None:
    """Launch the governance UI under uvicorn."""
    host = os.environ.get("AMP_UI_HOST", "127.0.0.1")
    port = int(os.environ.get("AMP_UI_PORT", "8765"))
    agent_id = os.environ.get("AMP_UI_AGENT_ID", "default")
    db_path = os.environ.get("AMP_UI_DB_PATH")

    app = create_app(db_path=db_path, agent_id=agent_id)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":  # pragma: no cover - exercised by `python -m`
    main()
