"""Record an animated GIF of the memorywire Governance UI diff-and-approve flow.

Boots ``amp_ui`` against the seeded ``demo-ui.db`` under uvicorn, drives
the browser with Playwright at 1280x800, captures PNG frames at ~7 fps,
then assembles them into ``docs/demos/ui.gif`` via Pillow.

Run from the repo root (after ``seed_demo_db.py``)::

    .venv/Scripts/python.exe docs/demos/record_ui.py

The script is intentionally idempotent â€” it deletes prior frames and
GIFs at the start of every run, picks a free localhost port, and tears
the server subprocess down even on error paths.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image
from playwright.async_api import Page, async_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMOS_DIR = REPO_ROOT / "docs" / "demos"
DB_PATH = DEMOS_DIR / "demo-ui.db"
FRAMES_DIR = DEMOS_DIR / "frames"
OUTPUT_GIF = DEMOS_DIR / "ui.gif"

VIEWPORT = {"width": 1280, "height": 800}
# Pre-quantize-to-128-colors target size â€” 1024x640 keeps text crisp at ~1.5MB.
RESIZE_TO = (1024, 640)
FRAME_DURATION_MS = 140  # ~7 fps
AGENT_ID = "customer-bot"


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------


def _free_port() -> int:
    """Ask the OS for an unbound TCP port we can hand to uvicorn."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_http(url: str, *, timeout_s: float = 20.0) -> None:
    """Poll ``url`` until it returns a 2xx â€” fail loudly if it never does."""
    deadline = time.monotonic() + timeout_s
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as resp:
                if 200 <= resp.status < 300:
                    return
        except Exception as exc:  # noqa: BLE001 â€” we re-raise after the loop
            last_exc = exc
        time.sleep(0.25)
    raise RuntimeError(f"UI did not come up at {url}: {last_exc}")


def _start_ui(port: int) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env["MEMORYWIRE_UI_DB_PATH"] = str(DB_PATH)
    env["MEMORYWIRE_UI_AGENT_ID"] = AGENT_ID
    env["MEMORYWIRE_UI_HOST"] = "127.0.0.1"
    env["MEMORYWIRE_UI_PORT"] = str(port)
    # Pin the CSRF secret so the per-process random secret doesn't
    # change between subprocesses (it doesn't matter for the demo, but
    # makes the recorder deterministic if reused across sessions).
    env.setdefault(
        "MEMORYWIRE_UI_CSRF_SECRET",
        "ZGVtby1jc3JmLXNlY3JldC1zaG91bGQtYmUtMzItYnl0ZXMtbG9uZw==",
    )
    return subprocess.Popen(
        [sys.executable, "-m", "amp_ui"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ---------------------------------------------------------------------------
# Frame capture
# ---------------------------------------------------------------------------


class FrameCapture:
    """Owns the frame counter + per-frame PNG file path."""

    def __init__(self, frames_dir: Path) -> None:
        self._frames_dir = frames_dir
        self._idx = 0

    async def snap(self, page: Page) -> None:
        path = self._frames_dir / f"frame_{self._idx:04d}.png"
        await page.screenshot(path=str(path), full_page=False)
        self._idx += 1

    async def settle(self, page: Page, *, frames: int = 7, interval_ms: int = 140) -> None:
        """Burst-capture ``frames`` frames at ``interval_ms`` to show settling."""
        for _ in range(frames):
            await self.snap(page)
            await asyncio.sleep(interval_ms / 1000.0)

    @property
    def count(self) -> int:
        return self._idx


# ---------------------------------------------------------------------------
# Recording scenario
# ---------------------------------------------------------------------------


async def _record(base_url: str) -> int:
    """Drive the UI scenario and write frames. Returns total frame count."""
    if FRAMES_DIR.exists():
        shutil.rmtree(FRAMES_DIR)
    FRAMES_DIR.mkdir(parents=True)

    capture = FrameCapture(FRAMES_DIR)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--font-render-hinting=none", "--force-color-profile=srgb"],
        )
        try:
            ctx = await browser.new_context(
                viewport=VIEWPORT,
                device_scale_factor=1.0,
                # Disable HTMX's animated indicator so frames don't pick up
                # spinner artifacts.
                color_scheme="light",
            )
            page = await ctx.new_page()

            # ----- Scene 1: pending approvals -----
            await page.goto(f"{base_url}/", wait_until="networkidle")
            # Disable the HTMX 10s poller so the recorder is deterministic â€”
            # otherwise an auto-refresh swap could collide with our click.
            await page.evaluate(
                """() => {
                    const el = document.getElementById('approvals-list');
                    if (el) { el.removeAttribute('hx-trigger'); }
                }"""
            )
            await page.wait_for_selector("#approvals-list article")
            # Hold the initial frame for ~500ms of still-time at start.
            for _ in range(4):
                await capture.snap(page)
                await asyncio.sleep(0.13)

            # Expand the diff <details> on the first row so reviewers see
            # what they're approving against.
            first_diff = page.locator("#approvals-list article details summary").first
            try:
                await first_diff.click(timeout=2000)
                await capture.settle(page, frames=6, interval_ms=140)
            except Exception:
                # If the first row had no live counterpart there is no
                # summary to click; skip silently.
                pass

            # Hover the Approve button so it visually pops.
            approve_button = page.locator(
                "#approvals-list article form[hx-post*='/approve'] button"
            ).first
            await approve_button.hover()
            for _ in range(3):
                await capture.snap(page)
                await asyncio.sleep(0.13)

            # ----- Scene 2: the approve click -----
            await approve_button.click()
            # Burst-capture across the HTMX swap so the row disappearing is
            # visible in the GIF.
            await capture.settle(page, frames=10, interval_ms=140)

            # Wait until the list has only one row left (one of two pending
            # memories was just approved). The HTMX swap is synchronous w.r.t.
            # the server but the DOM update is async â€” give it a generous
            # ceiling but settle as soon as the count drops.
            try:
                await page.wait_for_function(
                    """() => document.querySelectorAll('#approvals-list article').length === 1""",
                    timeout=5000,
                )
            except Exception:
                pass
            await capture.settle(page, frames=4, interval_ms=140)

            # ----- Scene 3: navigate to /audit, filtered to remembers -----
            await page.goto(f"{base_url}/audit?operation=remember", wait_until="networkidle")
            await page.wait_for_selector("#audit-table table")
            # Hold a few frames so the new audit row is unambiguous.
            await capture.settle(page, frames=6, interval_ms=140)

            # Hover the first row's "approved by" cell to draw the eye to it.
            first_row = page.locator("#audit-table tbody tr").first
            await first_row.hover()
            for _ in range(4):
                await capture.snap(page)
                await asyncio.sleep(0.15)

            # End-of-loop hold so the GIF reads cleanly when it restarts.
            for _ in range(4):
                await capture.snap(page)
                await asyncio.sleep(0.13)
        finally:
            await browser.close()

    return capture.count


# ---------------------------------------------------------------------------
# GIF assembly
# ---------------------------------------------------------------------------


def _assemble_gif(frames_dir: Path, out_path: Path) -> tuple[int, int]:
    """Compose PNG frames into an optimized GIF. Returns (frame_count, size_bytes)."""
    paths = sorted(frames_dir.glob("frame_*.png"))
    if not paths:
        raise RuntimeError(f"no frames found in {frames_dir}")

    frames: list[Image.Image] = []
    for p in paths:
        img = Image.open(p).convert("RGB")
        if RESIZE_TO and img.size != RESIZE_TO:
            img = img.resize(RESIZE_TO, Image.Resampling.LANCZOS)
        # Quantize to a 128-color adaptive palette per frame; Pillow re-uses
        # the master palette across the save_all call.
        frames.append(img.quantize(colors=128, method=Image.Quantize.MEDIANCUT))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        out_path,
        save_all=True,
        append_images=frames[1:],
        duration=FRAME_DURATION_MS,
        loop=0,
        optimize=True,
        disposal=2,
    )
    return len(frames), out_path.stat().st_size


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    if not DB_PATH.exists():
        sys.exit(
            f"[record] {DB_PATH} not found â€” run seed_demo_db.py first."
        )

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    print(f"[record] booting UI on {base_url}")

    t0 = time.monotonic()
    proc = _start_ui(port)
    try:
        _wait_for_http(f"{base_url}/", timeout_s=20.0)
        boot_elapsed = time.monotonic() - t0
        print(f"[record] UI up in {boot_elapsed:.1f}s; driving scenario")

        t_record = time.monotonic()
        frame_count = asyncio.run(_record(base_url))
        record_elapsed = time.monotonic() - t_record
        print(f"[record] captured {frame_count} frames in {record_elapsed:.1f}s")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    print(f"[record] assembling GIF -> {OUTPUT_GIF}")
    if OUTPUT_GIF.exists():
        OUTPUT_GIF.unlink()
    written, size_bytes = _assemble_gif(FRAMES_DIR, OUTPUT_GIF)
    total_elapsed = time.monotonic() - t0
    fps = 1000.0 / FRAME_DURATION_MS
    print(
        f"[record] done: {written} frames @ {fps:.1f} fps, "
        f"{size_bytes/1024:.1f} KiB, total {total_elapsed:.1f}s"
    )


if __name__ == "__main__":
    main()
