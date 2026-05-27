"""``python -m amp_ui`` entry point.

Reads ``AMP_UI_DB_PATH``, ``AMP_UI_AGENT_ID``, ``AMP_UI_HOST``,
``AMP_UI_PORT``, ``AMP_UI_TOKEN``, and ``AMP_UI_CSRF_SECRET`` from the
environment, builds the Starlette app via :func:`amp_ui.app.create_app`,
and hands it to ``uvicorn.run``.

``AMP_UI_TOKEN`` — when set, gates every request behind that bearer
token. Strongly recommended for any non-loopback bind; the app will emit
a stderr warning at boot when ``AMP_UI_HOST`` is set to anything other
than ``127.0.0.1`` / ``localhost`` / ``::1`` without it.

``AMP_UI_CSRF_SECRET`` — base64-encoded HMAC secret (>= 16 raw bytes)
used to sign CSRF tokens. When unset a fresh random secret is generated
per-process, which invalidates every browser session across restarts.
Pin it in production so cookies survive restarts; rotate it to log
everyone out intentionally. Generate one with::

    python -c "import secrets, base64; \
print(base64.b64encode(secrets.token_bytes(32)).decode())"
"""

from __future__ import annotations

import base64
import binascii
import os
import sys

import uvicorn

from amp_ui.app import create_app

CSRF_SECRET_ENV_VAR = "AMP_UI_CSRF_SECRET"
_MIN_CSRF_SECRET_BYTES = 16


def _load_csrf_secret_from_env(
    raw: str | None = None,
    *,
    env_var: str = CSRF_SECRET_ENV_VAR,
) -> bytes | None:
    """Decode the CSRF secret from a base64 env-var value, if any.

    Parameters
    ----------
    raw:
        The raw env-var string. When ``None`` (the default), the value is
        looked up from :data:`os.environ` using ``env_var``. Pass ``raw``
        explicitly from tests to avoid ``os.environ`` patching gymnastics.
    env_var:
        Name of the environment variable; only used in error messages and
        for the implicit lookup when ``raw`` is ``None``.

    Returns
    -------
    bytes | None
        The decoded secret, or ``None`` when the env var is unset or empty
        (the caller should fall back to its per-process random default).

    Raises
    ------
    ValueError
        If the env-var value is set but not valid base64, or if it decodes
        to fewer than 16 bytes. The caller is responsible for translating
        this into a process exit; :func:`main` does so with exit code 1.
    """
    if raw is None:
        raw = os.environ.get(env_var)
    if raw is None or raw == "":
        return None
    try:
        secret = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(
            f"{env_var} is not valid base64: {exc}. "
            'Generate one with: python -c "import secrets, base64; '
            'print(base64.b64encode(secrets.token_bytes(32)).decode())"'
        ) from exc
    if len(secret) < _MIN_CSRF_SECRET_BYTES:
        raise ValueError(
            f"{env_var} decoded to {len(secret)} bytes; "
            f"need at least {_MIN_CSRF_SECRET_BYTES}. "
            'Generate one with: python -c "import secrets, base64; '
            'print(base64.b64encode(secrets.token_bytes(32)).decode())"'
        )
    return secret


def main() -> None:
    """Launch the governance UI under uvicorn."""
    host = os.environ.get("AMP_UI_HOST", "127.0.0.1")
    port = int(os.environ.get("AMP_UI_PORT", "8765"))
    agent_id = os.environ.get("AMP_UI_AGENT_ID", "default")
    db_path = os.environ.get("AMP_UI_DB_PATH")
    token = os.environ.get("AMP_UI_TOKEN") or None

    try:
        csrf_secret = _load_csrf_secret_from_env()
    except ValueError as exc:
        print(f"[amp-ui] FATAL: {exc}", file=sys.stderr)
        sys.exit(1)

    app = create_app(
        db_path=db_path,
        agent_id=agent_id,
        token=token,
        csrf_secret=csrf_secret,
    )
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":  # pragma: no cover - exercised by `python -m`
    main()
