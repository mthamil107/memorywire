"""Render the LinkedIn-format memorywire explainer GIF using Pillow.

A 1080x1080 square explainer GIF that walks a scroll-past viewer through
six storyboard beats in ~6 seconds, then loops:

  1. Title / pain statement                       (0.0-1.0s)
  2. Five separate framework boxes ("islands")    (1.0-2.0s)
  3. Red pain banner sweeps in                    (2.0-3.0s)
  4. memorywire layer inserts itself between agent/boxes (3.0-4.0s)
  5. Governance UI / diff-and-approve slides in   (4.0-5.0s)
  6. Hold + CTA caption                           (5.0-6.5s)

This is reproducible: no randomness, no HTTP, no file IO besides the
output GIF. Run with the project's bundled venv:

    .venv/Scripts/python.exe docs/demos/render_amp_explainer.py
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Theme â€” light, "technical book" feel.
# ---------------------------------------------------------------------------

BG = (248, 246, 242)              # cream paper
FG = (26, 26, 26)                 # near-black ink
DIM = (110, 110, 110)             # body text grey
SOFT = (210, 206, 198)            # hairline ruled-page grey
INDIGO = (59, 91, 181)            # memorywire accent
INDIGO_LIGHT = (220, 226, 245)    # memorywire fill
RED = (200, 65, 65)               # pain banner
RED_LIGHT = (245, 220, 220)
GREEN = (44, 140, 94)             # approve
GREEN_LIGHT = (218, 238, 228)
STRIKE = (200, 65, 65)
ADD_BG = (218, 238, 228)
DEL_BG = (245, 220, 220)

# Five-framework palette â€” desaturated so the memorywire indigo stays visually
# dominant in beat 4. These are the "island" colors.
FRAMEWORK_COLORS = [
    ((215, 200, 230), (90, 60, 130)),    # mem0: violet
    ((205, 222, 230), (40, 90, 110)),    # Letta: teal
    ((235, 215, 195), (140, 80, 30)),    # Cognee: terracotta
    ((215, 230, 205), (60, 110, 50)),    # Zep: olive
    ((230, 220, 200), (130, 100, 40)),   # MemoryOS: sand
]
FRAMEWORK_NAMES = ["mem0", "Letta", "Cognee", "Zep", "MemoryOS"]
FRAMEWORK_QUIRKS = ["bespoke SDK", "own JSON shape", "own TTL", "own ACL", "own auth"]

# ---------------------------------------------------------------------------
# Geometry â€” 1080x1080 square.
# ---------------------------------------------------------------------------

WIDTH = 1080
HEIGHT = 1080
FPS = 12
FRAME_MS = int(round(1000 / FPS))   # ~83 ms

# Beat durations in frames
BEAT_FRAMES = [
    12,    # B1: 1.0s
    12,    # B2: 1.0s
    12,    # B3: 1.0s
    12,    # B4: 1.0s
    12,    # B5: 1.0s
    18,    # B6: 1.5s hold
]
TOTAL_FRAMES = sum(BEAT_FRAMES)   # 78

# Ease length for pop-in animations
EASE_FRAMES = 3

# Fonts: prefer Segoe UI (Windows ships these), fall back to DejaVu,
# fall back to Pillow's bitmap default. Never crash on missing font.
FONT_CANDIDATES_REGULAR = [
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
]
FONT_CANDIDATES_BOLD = [
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
]
FONT_CANDIDATES_MONO = [
    r"C:\Windows\Fonts\CascadiaMono.ttf",
    r"C:\Windows\Fonts\consola.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]


def _load_font(candidates: list[str], size: int) -> ImageFont.ImageFont:
    for p in candidates:
        try:
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
        except OSError:
            continue
    # PIL's built-in bitmap font ignores size â€” last-resort safety net.
    try:
        return ImageFont.load_default()
    except OSError:
        return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Easing helpers
# ---------------------------------------------------------------------------

def ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def pop_progress(frame_in_beat: int, ease: int = EASE_FRAMES) -> float:
    """Return 0..1 progress for a pop-in over `ease` frames."""
    if ease <= 0:
        return 1.0
    return ease_out_cubic(frame_in_beat / ease)


# ---------------------------------------------------------------------------
# Drawing primitives
# ---------------------------------------------------------------------------

def draw_text_centered(
    d: ImageDraw.ImageDraw,
    text: str,
    cx: int,
    cy: int,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int] = FG,
) -> None:
    bbox = d.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    d.text((cx - w / 2 - bbox[0], cy - h / 2 - bbox[1]), text, fill=fill, font=font)


def draw_text_anchored(
    d: ImageDraw.ImageDraw,
    text: str,
    x: int,
    y: int,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int] = FG,
    anchor: str = "lt",
) -> None:
    """Draw text with manual anchor handling (more reliable cross-version)."""
    bbox = d.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    if anchor[0] == "l":
        dx = -bbox[0]
    elif anchor[0] == "r":
        dx = -bbox[2]
    else:  # center
        dx = -w / 2 - bbox[0]
    if anchor[1] == "t":
        dy = -bbox[1]
    elif anchor[1] == "b":
        dy = -bbox[3]
    else:
        dy = -h / 2 - bbox[1]
    d.text((x + dx, y + dy), text, fill=fill, font=font)


def rounded_rect(
    d: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    radius: int,
    fill: tuple[int, int, int] | None = None,
    outline: tuple[int, int, int] | None = None,
    width: int = 1,
) -> None:
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def draw_arrow(
    d: ImageDraw.ImageDraw,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    color: tuple[int, int, int],
    width: int = 3,
    head: int = 10,
) -> None:
    """Draw a straight line with a small filled triangle arrowhead at (x2,y2)."""
    d.line((x1, y1, x2, y2), fill=color, width=width)
    # Compute arrowhead orientation from the line vector.
    dx, dy = x2 - x1, y2 - y1
    length = (dx * dx + dy * dy) ** 0.5 or 1
    ux, uy = dx / length, dy / length
    # Perp vector
    px, py = -uy, ux
    p1 = (x2, y2)
    p2 = (x2 - ux * head + px * head * 0.55, y2 - uy * head + py * head * 0.55)
    p3 = (x2 - ux * head - px * head * 0.55, y2 - uy * head - py * head * 0.55)
    d.polygon([p1, p2, p3], fill=color)


def draw_agent_icon(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    """A simple 'agent' glyph: rounded square + small antenna circle."""
    box = (cx - r, cy - r, cx + r, cy + r)
    rounded_rect(d, box, radius=r // 3, fill=INDIGO_LIGHT, outline=INDIGO, width=3)
    # Two "eye" dots
    eye_r = max(3, r // 8)
    eye_y = cy - r // 5
    eye_dx = r // 2
    d.ellipse(
        (cx - eye_dx - eye_r, eye_y - eye_r, cx - eye_dx + eye_r, eye_y + eye_r),
        fill=INDIGO,
    )
    d.ellipse(
        (cx + eye_dx - eye_r, eye_y - eye_r, cx + eye_dx + eye_r, eye_y + eye_r),
        fill=INDIGO,
    )
    # Smile
    d.arc(
        (cx - r // 2, cy - r // 8, cx + r // 2, cy + r // 2),
        start=20,
        end=160,
        fill=INDIGO,
        width=3,
    )
    # Antenna
    d.line((cx, cy - r, cx, cy - r - r // 2), fill=INDIGO, width=3)
    d.ellipse(
        (cx - 5, cy - r - r // 2 - 10, cx + 5, cy - r - r // 2),
        fill=INDIGO,
    )


def draw_framework_box(
    d: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    name: str,
    pattern_idx: int,
    fill: tuple[int, int, int],
    accent: tuple[int, int, int],
    font_label: ImageFont.ImageFont,
    scale: float = 1.0,
) -> None:
    """Pop-in framework box with a distinct interior pattern hint.

    Patterns are rendered onto a per-box mini-image so we can clip them
    cleanly against the rounded interior â€” drawing diagonals straight on
    the main canvas would leak out beyond the box border.
    """
    x0, y0, x1, y1 = box
    if scale != 1.0:
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2
        w = (x1 - x0) * scale / 2
        h = (y1 - y0) * scale / 2
        box = (int(cx - w), int(cy - h), int(cx + w), int(cy + h))
        x0, y0, x1, y1 = box
    rounded_rect(d, box, radius=14, fill=fill, outline=accent, width=2)
    # Inner clipping rect for the pattern. Use a separate mask so patterns
    # never spill past the box edges, regardless of step alignment.
    inner = (x0 + 10, y0 + 38, x1 - 10, y1 - 10)
    ix0, iy0, ix1, iy1 = inner
    pw = max(1, ix1 - ix0)
    ph = max(1, iy1 - iy0)
    pat = Image.new("RGB", (pw, ph), fill)
    pd = ImageDraw.Draw(pat)
    if pattern_idx == 0:
        # horizontal stripes
        step = 8
        for y in range(0, ph, step):
            pd.line((0, y, pw, y), fill=accent, width=1)
    elif pattern_idx == 1:
        # diagonal hatch
        step = 10
        for off in range(-ph, pw + ph, step):
            pd.line((off, 0, off + ph, ph), fill=accent, width=1)
    elif pattern_idx == 2:
        # dots grid
        step = 10
        for y in range(4, ph, step):
            for x in range(4, pw, step):
                pd.ellipse((x - 1, y - 1, x + 1, y + 1), fill=accent)
    elif pattern_idx == 3:
        # grid
        step = 12
        for y in range(0, ph, step):
            pd.line((0, y, pw, y), fill=accent, width=1)
        for x in range(0, pw, step):
            pd.line((x, 0, x, ph), fill=accent, width=1)
    else:
        # crosshatch
        step = 14
        for off in range(-ph, pw + ph, step):
            pd.line((off, 0, off + ph, ph), fill=accent, width=1)
        for off in range(-ph, pw + ph, step):
            pd.line((off, ph, off + ph, 0), fill=accent, width=1)
    # Build a rounded-rect mask the size of the inner area so the pattern
    # clips to the box geometry (with a small inset radius).
    mask = Image.new("L", (pw, ph), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, pw - 1, ph - 1), radius=8, fill=255)
    # Paste onto the parent image via the draw's underlying ._image.
    parent = d._image  # type: ignore[attr-defined]
    parent.paste(pat, (ix0, iy0), mask)
    # Re-draw label after pattern so text stays crisp on top.
    draw_text_centered(d, name, (x0 + x1) // 2, y0 + 18, font_label, fill=accent)


# ---------------------------------------------------------------------------
# Beat renderers â€” each returns a fully composed PIL Image for one frame.
# ---------------------------------------------------------------------------


class Layout:
    """Static layout constants shared across beats."""

    AGENT_CX = WIDTH // 2
    AGENT_CY = 200
    AGENT_R = 56

    BOX_TOP = 620
    BOX_BOT = 820
    BOX_W = 160
    BOX_GAP = 28
    BOX_TOTAL = 5 * BOX_W + 4 * BOX_GAP

    @classmethod
    def box_x(cls, idx: int) -> int:
        start = (WIDTH - cls.BOX_TOTAL) // 2
        return start + idx * (cls.BOX_W + cls.BOX_GAP)

    @classmethod
    def box_rect(cls, idx: int) -> tuple[int, int, int, int]:
        x0 = cls.box_x(idx)
        return (x0, cls.BOX_TOP, x0 + cls.BOX_W, cls.BOX_BOT)

    # memorywire horizontal layer between agent and boxes
    AMP_TOP = 430
    AMP_BOT = 510
    AMP_LEFT = 140
    AMP_RIGHT = WIDTH - 140


def render_frame(
    frame_idx: int,
    beat: int,
    frame_in_beat: int,
    fonts: dict[str, ImageFont.ImageFont],
) -> Image.Image:
    """Compose one frame given its global index and its beat-local index."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(img)

    # Subtle "ruled paper" hairline at top and bottom for the technical-book feel.
    d.line((60, 70, WIDTH - 60, 70), fill=SOFT, width=1)
    d.line((60, HEIGHT - 70, WIDTH - 60, HEIGHT - 70), fill=SOFT, width=1)

    # Header label (small)
    draw_text_anchored(
        d,
        "MEMORYWIRE",
        80,
        40,
        fonts["mono_sm"],
        fill=INDIGO,
        anchor="lt",
    )
    draw_text_anchored(
        d,
        "explainer",
        WIDTH - 80,
        40,
        fonts["mono_sm"],
        fill=DIM,
        anchor="rt",
    )

    # Dispatch per beat
    if beat == 0:
        _draw_beat1(d, frame_in_beat, fonts)
    elif beat == 1:
        _draw_beat2(d, frame_in_beat, fonts)
    elif beat == 2:
        _draw_beat3(d, frame_in_beat, fonts)
    elif beat == 3:
        _draw_beat4(d, frame_in_beat, fonts)
    elif beat == 4:
        _draw_beat5(d, frame_in_beat, fonts)
    elif beat == 5:
        _draw_beat6(d, frame_in_beat, fonts)

    return img


# --- Beat 1: title -----------------------------------------------------------

def _draw_beat1(
    d: ImageDraw.ImageDraw,
    f: int,
    fonts: dict[str, ImageFont.ImageFont],
) -> None:
    # Cap fade-in baseline at 0.55 on frame 0 so the loop's first frame
    # already shows readable text â€” LinkedIn often previews frame 0 as a
    # static thumbnail and a blank thumbnail is unforgivable.
    raw = pop_progress(f, ease=5)
    p = 0.55 + 0.45 * raw
    title = "Every agent-memory framework"
    title2 = "is its own island."
    subtitle = "And there's no governance surface."

    title_color = _blend(BG, FG, p)
    subtitle_color = _blend(BG, DIM, p)

    draw_text_centered(d, title, WIDTH // 2, 380, fonts["title"], fill=title_color)
    draw_text_centered(d, title2, WIDTH // 2, 460, fonts["title"], fill=title_color)
    draw_text_centered(
        d, subtitle, WIDTH // 2, 560, fonts["subtitle"], fill=subtitle_color
    )

    # Kicker fades in slightly behind the main title.
    kicker_p = max(0.0, min(1.0, raw * 1.4 - 0.2))
    if kicker_p > 0.0:
        draw_text_centered(
            d,
            "A protocol problem hiding as an integration problem.",
            WIDTH // 2,
            HEIGHT - 130,
            fonts["caption"],
            fill=_blend(BG, DIM, kicker_p),
        )


# --- Beat 2: five islands appearing -----------------------------------------

def _draw_beat2(
    d: ImageDraw.ImageDraw,
    f: int,
    fonts: dict[str, ImageFont.ImageFont],
) -> None:
    # Agent at the top, persistent for beats 2-6.
    draw_agent_icon(d, Layout.AGENT_CX, Layout.AGENT_CY, Layout.AGENT_R)
    # Label sits to the right of the agent so it never collides with the
    # downward fan of arrows or the memorywire arrow in later beats.
    draw_text_anchored(
        d, "Your agent",
        Layout.AGENT_CX + Layout.AGENT_R + 18, Layout.AGENT_CY,
        fonts["label"], fill=FG, anchor="lm",
    )

    # Section caption above the agent so it never sits in the arrow fan.
    draw_text_centered(
        d,
        "Today: five frameworks, five wire formats.",
        WIDTH // 2,
        Layout.AGENT_CY - Layout.AGENT_R - 60,
        fonts["caption_lg"],
        fill=DIM,
    )

    # Boxes pop in left-to-right. Each box gets its own ease window.
    for i in range(5):
        appear_start = i * 2          # stagger by 2 frames
        local = f - appear_start
        if local < 0:
            continue
        scale = pop_progress(local, ease=EASE_FRAMES)
        fill, accent = FRAMEWORK_COLORS[i]
        draw_framework_box(
            d,
            Layout.box_rect(i),
            FRAMEWORK_NAMES[i],
            i,
            fill,
            accent,
            fonts["label"],
            scale=0.4 + 0.6 * scale,
        )
        # Arrow from agent down to this box appears slightly after the box
        arrow_local = local - 2
        if arrow_local >= 0:
            arrow_p = pop_progress(arrow_local, ease=3)
            _draw_agent_to_box_arrow(d, i, arrow_p, FRAMEWORK_QUIRKS[i], fonts)


def _draw_agent_to_box_arrow(
    d: ImageDraw.ImageDraw,
    box_idx: int,
    progress: float,
    quirk: str,
    fonts: dict[str, ImageFont.ImageFont],
) -> None:
    """Stretch an arrow from agent center down to box top."""
    bx0, by0, bx1, _ = Layout.box_rect(box_idx)
    bx_mid = (bx0 + bx1) // 2
    sx = Layout.AGENT_CX
    sy = Layout.AGENT_CY + Layout.AGENT_R + 4
    # Use box_idx fan-out: shift start slightly so arrows visibly fan out.
    sx = Layout.AGENT_CX + (box_idx - 2) * 8
    ex = bx_mid
    ey = by0 - 4
    # Animate stretch from (sx,sy) toward (ex,ey)
    cur_ex = sx + (ex - sx) * progress
    cur_ey = sy + (ey - sy) * progress
    accent = FRAMEWORK_COLORS[box_idx][1]
    draw_arrow(d, sx, sy, int(cur_ex), int(cur_ey), accent, width=2, head=9)
    if progress > 0.85:
        # Quirk label near the arrow midpoint (offset to avoid overlap)
        mx = (sx + ex) / 2
        my = (sy + ey) / 2 + (box_idx - 2) * 12
        # Outline-style: draw a small cream-filled rounded backing so labels
        # stay legible over crossing arrows.
        bbox = d.textbbox((0, 0), quirk, font=fonts["tiny"])
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        pad = 4
        bx = (int(mx - tw / 2 - pad), int(my - th / 2 - pad),
              int(mx + tw / 2 + pad), int(my + th / 2 + pad))
        rounded_rect(d, bx, radius=6, fill=BG, outline=SOFT, width=1)
        draw_text_centered(d, quirk, int(mx), int(my), fonts["tiny"], fill=accent)


# --- Beat 3: red pain banner -------------------------------------------------

def _draw_beat3(
    d: ImageDraw.ImageDraw,
    f: int,
    fonts: dict[str, ImageFont.ImageFont],
) -> None:
    # Keep the agent + boxes underneath as fully-revealed.
    draw_agent_icon(d, Layout.AGENT_CX, Layout.AGENT_CY, Layout.AGENT_R)
    draw_text_anchored(
        d, "Your agent",
        Layout.AGENT_CX + Layout.AGENT_R + 18, Layout.AGENT_CY,
        fonts["label"], fill=FG, anchor="lm",
    )
    for i in range(5):
        fill, accent = FRAMEWORK_COLORS[i]
        draw_framework_box(
            d, Layout.box_rect(i), FRAMEWORK_NAMES[i], i, fill, accent, fonts["label"],
        )
        # full arrows (no progress animation, just static)
        _draw_agent_to_box_arrow(d, i, 1.0, FRAMEWORK_QUIRKS[i], fonts)

    # Banner sweeps in from the left.
    banner_top = 380
    banner_bot = 540
    banner_left_final = 60
    banner_right_final = WIDTH - 60
    # ease over EASE_FRAMES then hold
    p = pop_progress(f, ease=4)
    # Slide-in: width grows from left edge.
    cur_right = int(banner_left_final + (banner_right_final - banner_left_final) * p)
    rounded_rect(
        d,
        (banner_left_final, banner_top, cur_right, banner_bot),
        radius=18,
        fill=RED,
    )
    if p > 0.85:
        draw_text_centered(
            d,
            "5 integrations  x  every agent.",
            WIDTH // 2,
            banner_top + 42,
            fonts["banner"],
            fill=(255, 255, 255),
        )
        draw_text_centered(
            d,
            "No shared wire format.",
            WIDTH // 2,
            banner_top + 88,
            fonts["banner_sm"],
            fill=(255, 255, 255),
        )
        draw_text_centered(
            d,
            "Every migration = rebuild.",
            WIDTH // 2,
            banner_top + 128,
            fonts["banner_sm"],
            fill=(255, 255, 255),
        )


# --- Beat 4: memorywire layer inserts itself ----------------------------------------

def _draw_beat4(
    d: ImageDraw.ImageDraw,
    f: int,
    fonts: dict[str, ImageFont.ImageFont],
) -> None:
    # Agent persists.
    draw_agent_icon(d, Layout.AGENT_CX, Layout.AGENT_CY, Layout.AGENT_R)
    draw_text_anchored(
        d, "Your agent",
        Layout.AGENT_CX + Layout.AGENT_R + 18, Layout.AGENT_CY,
        fonts["label"], fill=FG, anchor="lm",
    )

    # Boxes still present.
    for i in range(5):
        fill, accent = FRAMEWORK_COLORS[i]
        draw_framework_box(
            d, Layout.box_rect(i), FRAMEWORK_NAMES[i], i, fill, accent, fonts["label"],
        )

    # memorywire layer grows in over the first few frames.
    p = pop_progress(f, ease=5)
    amp_top = Layout.AMP_TOP
    amp_bot = Layout.AMP_BOT
    amp_left = Layout.AMP_LEFT
    amp_right = Layout.AMP_RIGHT
    amp_h = amp_bot - amp_top
    cur_top = int(amp_top + amp_h * (1 - p) / 2)
    cur_bot = int(amp_bot - amp_h * (1 - p) / 2)
    rounded_rect(
        d,
        (amp_left, cur_top, amp_right, cur_bot),
        radius=16,
        fill=INDIGO_LIGHT,
        outline=INDIGO,
        width=3,
    )
    if p > 0.5:
        draw_text_centered(
            d,
            "memorywire - Agent Memory Protocol",
            WIDTH // 2,
            (cur_top + cur_bot) // 2 - 14,
            fonts["amp_title"],
            fill=INDIGO,
        )
        verbs = "remember()  recall()  forget()  merge()  expire()"
        draw_text_centered(
            d,
            verbs,
            WIDTH // 2,
            (cur_top + cur_bot) // 2 + 20,
            fonts["mono_md"],
            fill=INDIGO,
        )

    # Agent -> memorywire single arrow appears late.
    if p > 0.7:
        arr_p = (p - 0.7) / 0.3
        sx = Layout.AGENT_CX
        sy = Layout.AGENT_CY + Layout.AGENT_R + 4
        ex = WIDTH // 2
        ey = amp_top - 4
        cur_ex = sx + (ex - sx) * arr_p
        cur_ey = sy + (ey - sy) * arr_p
        draw_arrow(d, sx, sy, int(cur_ex), int(cur_ey), INDIGO, width=4, head=12)

    # memorywire -> 5 boxes arrows appear last.
    if p > 0.85:
        for i in range(5):
            bx0, by0, bx1, _ = Layout.box_rect(i)
            sx = WIDTH // 2 + (i - 2) * 60
            sy = amp_bot + 4
            ex = (bx0 + bx1) // 2
            ey = by0 - 4
            draw_arrow(d, sx, sy, ex, ey, INDIGO, width=2, head=8)


# --- Beat 5: governance UI panel slides in ----------------------------------

def _draw_beat5(
    d: ImageDraw.ImageDraw,
    f: int,
    fonts: dict[str, ImageFont.ImageFont],
) -> None:
    # Persist beat 4 backdrop (agent, memorywire, boxes, arrows) at reduced contrast
    # so the governance panel on the right pops.
    _draw_beat4_backdrop(d, fonts)

    # Governance panel slides in from the right edge.
    p = pop_progress(f, ease=5)
    panel_w = 360
    panel_h = 520
    panel_top = 280
    panel_right_final = WIDTH - 60
    panel_left_final = panel_right_final - panel_w
    # Off-screen start: shifted right by panel_w.
    shift = int((1 - p) * panel_w * 1.1)
    panel_left = panel_left_final + shift
    panel_right = panel_right_final + shift

    rounded_rect(
        d,
        (panel_left, panel_top, panel_right, panel_top + panel_h),
        radius=18,
        fill=BG,
        outline=INDIGO,
        width=3,
    )
    # Title bar
    rounded_rect(
        d,
        (panel_left, panel_top, panel_right, panel_top + 50),
        radius=18,
        fill=INDIGO,
    )
    # Square off the bottom of the title bar by drawing a small rect over the
    # rounded bottom corners.
    d.rectangle(
        (panel_left, panel_top + 30, panel_right, panel_top + 50),
        fill=INDIGO,
    )
    draw_text_anchored(
        d,
        "governance / pending review",
        panel_left + 18,
        panel_top + 25,
        fonts["panel_title"],
        fill=(255, 255, 255),
        anchor="lm",
    )

    # Body â€” show a diff card for a pending memory write.
    body_x = panel_left + 18
    body_y = panel_top + 70

    draw_text_anchored(
        d,
        "memory  semantic",
        body_x,
        body_y,
        fonts["mono_sm"],
        fill=DIM,
        anchor="lt",
    )
    draw_text_anchored(
        d,
        "entity_name: alice@acme.com",
        body_x,
        body_y + 24,
        fonts["mono_sm"],
        fill=FG,
        anchor="lt",
    )

    # Diff lines: deletion + addition
    diff_top = body_y + 64
    del_line = "- contact_pref: phone"
    add_line = "+ contact_pref: email"
    rounded_rect(
        d,
        (body_x - 6, diff_top - 4, panel_right - 18, diff_top + 26),
        radius=4,
        fill=DEL_BG,
    )
    draw_text_anchored(
        d, del_line, body_x, diff_top + 11, fonts["mono_sm"], fill=STRIKE, anchor="lm",
    )
    rounded_rect(
        d,
        (body_x - 6, diff_top + 32, panel_right - 18, diff_top + 62),
        radius=4,
        fill=ADD_BG,
    )
    draw_text_anchored(
        d, add_line, body_x, diff_top + 47, fonts["mono_sm"], fill=GREEN, anchor="lm",
    )

    # A second changed field
    diff_top2 = diff_top + 84
    del2 = "- source: crm_sync"
    add2 = "+ source: chat_session_4421"
    rounded_rect(
        d,
        (body_x - 6, diff_top2 - 4, panel_right - 18, diff_top2 + 26),
        radius=4,
        fill=DEL_BG,
    )
    draw_text_anchored(
        d, del2, body_x, diff_top2 + 11, fonts["mono_sm"], fill=STRIKE, anchor="lm",
    )
    rounded_rect(
        d,
        (body_x - 6, diff_top2 + 32, panel_right - 18, diff_top2 + 62),
        radius=4,
        fill=ADD_BG,
    )
    draw_text_anchored(
        d, add2, body_x, diff_top2 + 47, fonts["mono_sm"], fill=GREEN, anchor="lm",
    )

    # Confidence row
    conf_y = diff_top2 + 96
    draw_text_anchored(
        d, "confidence  0.92", body_x, conf_y, fonts["mono_sm"], fill=DIM, anchor="lt",
    )
    draw_text_anchored(
        d,
        "source  chat_session_4421",
        body_x, conf_y + 24,
        fonts["mono_sm"], fill=DIM, anchor="lt",
    )

    # Action buttons
    btn_y = panel_top + panel_h - 70
    btn_w = 130
    btn_h = 44
    gap = 16
    btn_total = 2 * btn_w + gap
    btn_x0 = panel_left + (panel_w - btn_total) // 2
    # Approve (green)
    rounded_rect(
        d,
        (btn_x0, btn_y, btn_x0 + btn_w, btn_y + btn_h),
        radius=8,
        fill=GREEN,
    )
    draw_text_centered(
        d, "Approve", btn_x0 + btn_w // 2, btn_y + btn_h // 2,
        fonts["btn"], fill=(255, 255, 255),
    )
    # Reject (red outline)
    rx0 = btn_x0 + btn_w + gap
    rounded_rect(
        d,
        (rx0, btn_y, rx0 + btn_w, btn_y + btn_h),
        radius=8,
        fill=BG,
        outline=RED,
        width=2,
    )
    draw_text_centered(
        d, "Reject", rx0 + btn_w // 2, btn_y + btn_h // 2,
        fonts["btn"], fill=RED,
    )

    # Caption below the panel
    if p > 0.7:
        draw_text_centered(
            d,
            "Optional HITL review on every memory write.",
            WIDTH // 2,
            HEIGHT - 130,
            fonts["caption_lg"],
            fill=FG,
        )


def _draw_beat4_backdrop(
    d: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont]
) -> None:
    """Beat 4's final composed state, used as the static background for beats 5-6."""
    draw_agent_icon(d, Layout.AGENT_CX, Layout.AGENT_CY, Layout.AGENT_R)
    draw_text_anchored(
        d, "Your agent",
        Layout.AGENT_CX + Layout.AGENT_R + 18, Layout.AGENT_CY,
        fonts["label"], fill=FG, anchor="lm",
    )
    for i in range(5):
        fill, accent = FRAMEWORK_COLORS[i]
        draw_framework_box(
            d, Layout.box_rect(i), FRAMEWORK_NAMES[i], i, fill, accent, fonts["label"],
        )
    rounded_rect(
        d,
        (Layout.AMP_LEFT, Layout.AMP_TOP, Layout.AMP_RIGHT, Layout.AMP_BOT),
        radius=16,
        fill=INDIGO_LIGHT,
        outline=INDIGO,
        width=3,
    )
    draw_text_centered(
        d,
        "memorywire",
        WIDTH // 2,
        (Layout.AMP_TOP + Layout.AMP_BOT) // 2 - 14,
        fonts["amp_title"],
        fill=INDIGO,
    )
    verbs = "remember()  recall()  forget()  merge()  expire()"
    draw_text_centered(
        d,
        verbs,
        WIDTH // 2,
        (Layout.AMP_TOP + Layout.AMP_BOT) // 2 + 20,
        fonts["mono_md"],
        fill=INDIGO,
    )
    # Arrows
    sx = Layout.AGENT_CX
    sy = Layout.AGENT_CY + Layout.AGENT_R + 4
    draw_arrow(d, sx, sy, WIDTH // 2, Layout.AMP_TOP - 4, INDIGO, width=4, head=12)
    for i in range(5):
        bx0, by0, bx1, _ = Layout.box_rect(i)
        sx = WIDTH // 2 + (i - 2) * 60
        sy = Layout.AMP_BOT + 4
        ex = (bx0 + bx1) // 2
        ey = by0 - 4
        draw_arrow(d, sx, sy, ex, ey, INDIGO, width=2, head=8)


# --- Beat 6: final hold + CTA ------------------------------------------------

def _draw_beat6(
    d: ImageDraw.ImageDraw,
    f: int,
    fonts: dict[str, ImageFont.ImageFont],
) -> None:
    # Full beat-5 composition stays â€” including the governance panel â€” for
    # the hold. We just compose without the slide animation.
    _draw_beat4_backdrop(d, fonts)
    # Re-draw the panel in its final position.
    panel_w = 360
    panel_h = 520
    panel_top = 280
    panel_right = WIDTH - 60
    panel_left = panel_right - panel_w
    rounded_rect(
        d,
        (panel_left, panel_top, panel_right, panel_top + panel_h),
        radius=18,
        fill=BG,
        outline=INDIGO,
        width=3,
    )
    rounded_rect(
        d,
        (panel_left, panel_top, panel_right, panel_top + 50),
        radius=18,
        fill=INDIGO,
    )
    d.rectangle(
        (panel_left, panel_top + 30, panel_right, panel_top + 50),
        fill=INDIGO,
    )
    draw_text_anchored(
        d, "governance / pending review",
        panel_left + 18, panel_top + 25, fonts["panel_title"],
        fill=(255, 255, 255), anchor="lm",
    )
    body_x = panel_left + 18
    body_y = panel_top + 70
    draw_text_anchored(
        d, "memory  semantic", body_x, body_y, fonts["mono_sm"], fill=DIM, anchor="lt",
    )
    draw_text_anchored(
        d, "entity_name: alice@acme.com", body_x, body_y + 24,
        fonts["mono_sm"], fill=FG, anchor="lt",
    )
    diff_top = body_y + 64
    rounded_rect(d, (body_x - 6, diff_top - 4, panel_right - 18, diff_top + 26),
                 radius=4, fill=DEL_BG)
    draw_text_anchored(d, "- contact_pref: phone", body_x, diff_top + 11,
                       fonts["mono_sm"], fill=STRIKE, anchor="lm")
    rounded_rect(d, (body_x - 6, diff_top + 32, panel_right - 18, diff_top + 62),
                 radius=4, fill=ADD_BG)
    draw_text_anchored(d, "+ contact_pref: email", body_x, diff_top + 47,
                       fonts["mono_sm"], fill=GREEN, anchor="lm")
    diff_top2 = diff_top + 84
    rounded_rect(d, (body_x - 6, diff_top2 - 4, panel_right - 18, diff_top2 + 26),
                 radius=4, fill=DEL_BG)
    draw_text_anchored(d, "- source: crm_sync", body_x, diff_top2 + 11,
                       fonts["mono_sm"], fill=STRIKE, anchor="lm")
    rounded_rect(d, (body_x - 6, diff_top2 + 32, panel_right - 18, diff_top2 + 62),
                 radius=4, fill=ADD_BG)
    draw_text_anchored(d, "+ source: chat_session_4421", body_x, diff_top2 + 47,
                       fonts["mono_sm"], fill=GREEN, anchor="lm")
    conf_y = diff_top2 + 96
    draw_text_anchored(d, "confidence  0.92", body_x, conf_y,
                       fonts["mono_sm"], fill=DIM, anchor="lt")
    draw_text_anchored(d, "source  chat_session_4421", body_x, conf_y + 24,
                       fonts["mono_sm"], fill=DIM, anchor="lt")
    btn_y = panel_top + panel_h - 70
    btn_w = 130
    btn_h = 44
    gap = 16
    btn_total = 2 * btn_w + gap
    btn_x0 = panel_left + (panel_w - btn_total) // 2
    rounded_rect(d, (btn_x0, btn_y, btn_x0 + btn_w, btn_y + btn_h),
                 radius=8, fill=GREEN)
    draw_text_centered(d, "Approve", btn_x0 + btn_w // 2, btn_y + btn_h // 2,
                       fonts["btn"], fill=(255, 255, 255))
    rx0 = btn_x0 + btn_w + gap
    rounded_rect(d, (rx0, btn_y, rx0 + btn_w, btn_y + btn_h),
                 radius=8, fill=BG, outline=RED, width=2)
    draw_text_centered(d, "Reject", rx0 + btn_w // 2, btn_y + btn_h // 2,
                       fonts["btn"], fill=RED)

    # Final CTA at bottom: Apache 2.0, adapters, repo URL.
    cta1 = "Apache-2.0  -  5 backend adapters"
    cta2 = "github.com/mthamil107/memorywire"
    draw_text_centered(d, cta1, WIDTH // 2, HEIGHT - 150, fonts["cta"], fill=FG)
    # Pulse the URL line subtly: a slow scale of saturation between INDIGO and FG.
    # f goes 0..BEAT_FRAMES[5]-1; we want one gentle pulse cycle.
    import math
    pulse = 0.5 + 0.5 * math.sin(2 * math.pi * f / BEAT_FRAMES[5])
    url_color = _blend(FG, INDIGO, pulse)
    draw_text_centered(d, cta2, WIDTH // 2, HEIGHT - 100, fonts["cta"], fill=url_color)


# ---------------------------------------------------------------------------
# Color blending
# ---------------------------------------------------------------------------

def _blend(
    a: tuple[int, int, int], b: tuple[int, int, int], t: float
) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def _build_fonts() -> dict[str, ImageFont.ImageFont]:
    return {
        "title": _load_font(FONT_CANDIDATES_BOLD, 56),
        "subtitle": _load_font(FONT_CANDIDATES_REGULAR, 28),
        "caption_lg": _load_font(FONT_CANDIDATES_REGULAR, 22),
        "caption": _load_font(FONT_CANDIDATES_REGULAR, 18),
        "label": _load_font(FONT_CANDIDATES_BOLD, 18),
        "tiny": _load_font(FONT_CANDIDATES_REGULAR, 13),
        "banner": _load_font(FONT_CANDIDATES_BOLD, 34),
        "banner_sm": _load_font(FONT_CANDIDATES_REGULAR, 26),
        "amp_title": _load_font(FONT_CANDIDATES_BOLD, 30),
        "mono_md": _load_font(FONT_CANDIDATES_MONO, 20),
        "mono_sm": _load_font(FONT_CANDIDATES_MONO, 16),
        "panel_title": _load_font(FONT_CANDIDATES_BOLD, 18),
        "btn": _load_font(FONT_CANDIDATES_BOLD, 18),
        "cta": _load_font(FONT_CANDIDATES_BOLD, 22),
    }


def render() -> Path:
    fonts = _build_fonts()
    out_path = Path(__file__).resolve().parent / "memorywire-explainer.gif"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    frames: list[Image.Image] = []
    durations: list[int] = []

    # Map global frame index -> (beat, frame_in_beat).
    beat_index = []
    for beat, n in enumerate(BEAT_FRAMES):
        for i in range(n):
            beat_index.append((beat, i))

    for global_idx, (beat, local) in enumerate(beat_index):
        img = render_frame(global_idx, beat, local, fonts)
        frames.append(img)
        durations.append(FRAME_MS)

    # Shared 64-color palette computed from a composite reference image so
    # the encoder can delta-encode well across frames.
    ref = Image.new("RGB", (WIDTH, HEIGHT), BG)
    ref.paste(frames[0])
    # Mix in some pixels from a mid-beat 4 / beat 5 / beat 6 frame so the
    # quantizer sees indigo, red, green, framework colors all at once.
    sample_indices = [
        0,                           # beat 1 start
        BEAT_FRAMES[0] + 6,          # beat 2 middle
        sum(BEAT_FRAMES[:2]) + 8,    # beat 3 late
        sum(BEAT_FRAMES[:3]) + 8,    # beat 4 late
        sum(BEAT_FRAMES[:4]) + 8,    # beat 5 late
        sum(BEAT_FRAMES[:5]) + 4,    # beat 6
    ]
    # Build a horizontal strip from the sampled frames to inform the palette.
    strip = Image.new("RGB", (WIDTH, HEIGHT * len(sample_indices)), BG)
    for i, fi in enumerate(sample_indices):
        strip.paste(frames[fi], (0, i * HEIGHT))
    palette_source = strip.quantize(
        colors=64, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
    )

    quant_frames = [
        f.quantize(palette=palette_source, dither=Image.Dither.NONE) for f in frames
    ]

    # Pillow's GIF encoder silently drops the duration of consecutive
    # pixel-identical quantized frames, which throws off the loop timing.
    # We collapse such runs ourselves and roll the dropped duration into
    # the surviving frame â€” preserving the full 6.5s loop length while
    # producing a smaller GIF.
    merged_frames: list[Image.Image] = []
    merged_durations: list[int] = []
    prev_bytes: bytes | None = None
    for qf, dur in zip(quant_frames, durations):
        cur_bytes = qf.tobytes()
        if prev_bytes is not None and cur_bytes == prev_bytes:
            merged_durations[-1] += dur
            continue
        merged_frames.append(qf)
        merged_durations.append(dur)
        prev_bytes = cur_bytes

    merged_frames[0].save(
        out_path,
        save_all=True,
        append_images=merged_frames[1:],
        duration=merged_durations,
        loop=0,
        optimize=True,
        disposal=2,
    )
    size = out_path.stat().st_size
    total_ms = sum(merged_durations)
    print(
        f"wrote {out_path} ({size/1024:.1f} KB, "
        f"{len(merged_frames)} stored frames / {len(frames)} logical, "
        f"{total_ms/1000:.1f}s @ {FPS} fps)"
    )
    return out_path


if __name__ == "__main__":
    render()
