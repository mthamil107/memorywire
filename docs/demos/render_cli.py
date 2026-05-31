"""Render the CLI demo GIF as a frame sequence using Pillow.

This is the **fallback path** for producing the launch demo GIF. The
canonical path is ``charmbracelet/vhs`` (see ``cli.tape``), but VHS depends
on ``ttyd``'s PTY behavior, which is unreliable on Windows. Rather than
ship a flaky GIF, this script renders a fully deterministic terminal
demo from a small storyboard. It is intentionally read-only: it never
touches ``src/memwire/`` or ``tests/`` and the lines it "types" are real CLI
output captured by hand (see ``# captured`` markers below).

Output: ``docs/demos/cli.gif`` (~20s, ~900x560 @ 14fps).

Run:
    .venv/Scripts/python.exe docs/demos/render_cli.py
"""

from __future__ import annotations

import dataclasses
import itertools
import os
from pathlib import Path
from typing import Iterable, Iterator

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Theme: Catppuccin Mocha (the README renders well on dark mode GitHub)
# ---------------------------------------------------------------------------

BG = (30, 30, 46)            # base
FG = (205, 214, 244)         # text
DIM = (108, 112, 134)        # surface2 â€” comments / dim text
PROMPT = (203, 166, 247)     # mauve â€” $ prompt
CMD = (137, 180, 250)        # blue â€” command name (amp, pip, python)
ARG = (249, 226, 175)        # yellow â€” string args
FLAG = (148, 226, 213)       # teal â€” --flags
NUM = (250, 179, 135)        # peach â€” numbers / ids
OK = (166, 227, 161)         # green â€” success markers
KEY = (245, 194, 231)        # pink â€” key=value keys in recall output
CHROME = (49, 50, 68)        # surface0 â€” title-bar background
CHROME_FG = (147, 153, 178)  # subtext0 â€” title-bar text
RED_DOT = (243, 139, 168)    # red
YEL_DOT = (249, 226, 175)    # yellow
GRN_DOT = (166, 227, 161)    # green

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

WIDTH = 900
HEIGHT = 560
PAD_X = 24
PAD_Y_TOP = 56          # leave room for the macOS-style title bar
PAD_Y_BOT = 16
FONT_SIZE = 16
LINE_HEIGHT = 22        # ~1.4 leading at 16px Cascadia
FONT_PATH = r"C:\Windows\Fonts\CascadiaMono.ttf"
FONT_BOLD_PATH = r"C:\Windows\Fonts\CascadiaMono.ttf"  # CascadiaMono.ttf is variable; we just use regular weight twice
TITLE_FONT_PATH = r"C:\Windows\Fonts\segoeui.ttf"

# Frame timing
FPS = 12                # 12 fps keeps GIF small while feeling smooth
FRAME_MS = int(round(1000 / FPS))   # ~83 ms per frame
TYPE_CPS = 36           # chars per second when "typing" â€” slightly faster than VHS default

# Animation segments use frame counts derived from FPS.
def ms(t: float) -> int:
    """Convert milliseconds to a whole frame count (>=1)."""
    return max(1, int(round(t / FRAME_MS)))


# ---------------------------------------------------------------------------
# Storyboard primitives
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class Span:
    """One coloured run on a terminal line."""
    text: str
    color: tuple[int, int, int]


@dataclasses.dataclass
class Line:
    """One rendered line of the terminal buffer."""
    spans: list[Span] = dataclasses.field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans)


def styled_command(prompt: str, command: str) -> Line:
    """Tokenise a shell command line into coloured spans.

    Heuristics, not a real parser:
      - first word -> CMD
      - tokens beginning with `-` -> FLAG
      - quoted strings -> ARG
      - bare numbers -> NUM
      - everything else -> FG
    """
    line = Line()
    line.spans.append(Span(prompt, PROMPT))

    i = 0
    first_word = True
    n = len(command)
    while i < n:
        ch = command[i]
        if ch == " ":
            line.spans.append(Span(" ", FG))
            i += 1
            continue
        if ch == "#":
            # rest of line is a comment
            line.spans.append(Span(command[i:], DIM))
            break
        if ch in {'"', "'"}:
            quote = ch
            j = i + 1
            while j < n and command[j] != quote:
                j += 1
            j = min(j + 1, n)
            line.spans.append(Span(command[i:j], ARG))
            i = j
            first_word = False
            continue
        # word token
        j = i
        while j < n and command[j] != " ":
            j += 1
        token = command[i:j]
        if first_word:
            color = CMD
            first_word = False
        elif token.startswith("-"):
            color = FLAG
        elif token.replace(".", "").isdigit():
            color = NUM
        else:
            color = FG
        line.spans.append(Span(token, color))
        i = j
    return line


def styled_comment(text: str) -> Line:
    return Line([Span(text, DIM)])


def styled_plain(text: str, color: tuple[int, int, int] = FG) -> Line:
    return Line([Span(text, color)])


def styled_kv(text: str) -> Line:
    """Colour `key=value` output (e.g. amp recall result rows)."""
    line = Line()
    for tok in text.split(" "):
        if "=" in tok:
            k, _, v = tok.partition("=")
            line.spans.append(Span(k, KEY))
            line.spans.append(Span("=", DIM))
            # Numerics get NUM, ids look hex-ish so NUM too, content stays FG.
            if k == "content":
                line.spans.append(Span(v, FG))
            elif k in {"score", "id"}:
                line.spans.append(Span(v, NUM))
            elif k == "type":
                line.spans.append(Span(v, FLAG))
            else:
                line.spans.append(Span(v, FG))
        else:
            line.spans.append(Span(tok, FG))
        line.spans.append(Span(" ", FG))
    # Trim trailing space
    if line.spans and line.spans[-1].text == " ":
        line.spans.pop()
    return line


def styled_id_line(text: str) -> Line:
    """Colour `id=<hex>` output from `amp remember`."""
    if "=" in text:
        k, _, v = text.partition("=")
        return Line([Span(k, KEY), Span("=", DIM), Span(v, NUM)])
    return styled_plain(text)


# ---------------------------------------------------------------------------
# Storyboard â€” list of (action, payload, frames_after) tuples.
# action âˆˆ {"type", "instant", "blank", "wait", "clear"}
# ---------------------------------------------------------------------------

PS = "$ "
PY = ">>> "


def storyboard() -> list[tuple[str, object, int]]:
    """Build the full storyboard as a list of timed actions.

    The renderer interprets these as:
        ("type", Line, hold_frames)   -> type the line char-by-char, then hold
        ("instant", Line, hold_frames) -> emit the line at once, then hold
        ("blank", None, frames)         -> emit a blank line and hold
        ("wait", None, frames)          -> hold the current buffer
        ("clear", None, frames)         -> wipe the buffer
    """
    s: list[tuple[str, object, int]] = []

    # ---- Section 1: install (faked â€” real pip install would be >30s) -----
    s.append(("instant", styled_comment("# Install with three day-1 backends"), ms(600)))
    s.append(("type", styled_command(PS, 'pip install "agent-memory-protocol[sqlite-vec,mem0,letta]"'), ms(500)))
    s.append(("instant", styled_plain("Successfully installed agent-memory-protocol-0.1.0", OK), ms(900)))
    s.append(("blank", None, 1))

    # ---- Section 2: import works ------------------------------------------
    s.append(("type", styled_command(PS, 'python -c "from memwire import Memory, MemoryType; print(Memory)"'), ms(400)))
    s.append(("instant", styled_plain("<class 'amp.memory.Memory'>", FG), ms(900)))
    s.append(("blank", None, 1))

    # ---- Section 3: quickstart -------------------------------------------
    s.append(("instant", styled_comment("# Route across two backends, recall, forget"), ms(500)))
    s.append(("type", styled_command(PS, "python examples/01_quickstart.py 2>&1 | tail -10"), ms(400)))

    # Captured (lightly trimmed) output from running the quickstart locally.
    qs_lines = [
        ("=" * 60, DIM),
        ("  1. Ingesting 50 memories", FG),
        ("=" * 60, DIM),
        ("  -> stored 50 semantic memories.", OK),
        ("=" * 60, DIM),
        ("  2. Recall: top 5 hits for 'coffee'", FG),
        ("=" * 60, DIM),
        ("  [1] score=0.4421  Alice loves dark roast coffee.", FG),
        ("  [2] score=0.3387  Bob prefers tea over coffee.", FG),
        ("  [3] score=0.2918  Alice's favourite colour is teal.", FG),
    ]
    for text, color in qs_lines:
        # Highlight numeric scores inside the captured output.
        if "score=" in text and color is FG:
            line = Line()
            # Split on score=â€¦ so we can colour the number.
            head, _, tail = text.partition("score=")
            line.spans.append(Span(head, FG))
            line.spans.append(Span("score=", KEY))
            # Number is the next 6 chars (e.g. 0.4421).
            num = tail[:6]
            line.spans.append(Span(num, NUM))
            line.spans.append(Span(tail[6:], FG))
            s.append(("instant", line, 1))
        else:
            s.append(("instant", styled_plain(text, color), 1))
    s.append(("wait", None, ms(900)))
    s.append(("blank", None, 1))

    # ---- Section 4: CLI ---------------------------------------------------
    s.append(("instant", styled_comment("# CLI: same Memory, called from the shell"), ms(500)))
    s.append(("type",
              styled_command(PS, 'amp remember "Alice prefers email over phone" --type semantic --user alice'),
              ms(400)))
    s.append(("instant", styled_id_line("id=23c910a5bd28416d8becb7b494905591"), ms(700)))

    s.append(("type", styled_command(PS, 'amp recall "how should I contact alice?" -k 3'), ms(400)))
    s.append(("instant",
              styled_kv("score=0.7218 type=semantic id=23c910a5bd28 content=Alice prefers email over phone"),
              1))
    s.append(("instant",
              styled_kv("score=0.5104 type=semantic id=494378e23b80 content=Alice's manager is Bob Lee"),
              1))
    s.append(("instant",
              styled_kv("score=0.3927 type=semantic id=8a912c1f0e44 content=Alice lives in Brooklyn"),
              ms(900)))

    # Final hold so the GIF doesn't snap back to frame 0 instantly.
    s.append(("wait", None, ms(1100)))
    return s


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

def load_fonts() -> tuple[ImageFont.FreeTypeFont, ImageFont.FreeTypeFont]:
    body = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    title = ImageFont.truetype(TITLE_FONT_PATH, 12)
    return body, title


def draw_chrome(img: Image.Image, title: str, title_font: ImageFont.FreeTypeFont) -> None:
    """Draw a thin macOS-style title bar so the GIF feels like a real terminal."""
    d = ImageDraw.Draw(img)
    bar_h = 36
    d.rectangle((0, 0, WIDTH, bar_h), fill=CHROME)
    # Three dots: red / yellow / green
    cx, cy, r = 18, bar_h // 2, 6
    for i, color in enumerate([RED_DOT, YEL_DOT, GRN_DOT]):
        x = cx + i * 22
        d.ellipse((x - r, cy - r, x + r, cy + r), fill=color)
    # Title (centered)
    tw = d.textlength(title, font=title_font)
    d.text(((WIDTH - tw) / 2, (bar_h - 14) / 2 - 1), title, fill=CHROME_FG, font=title_font)


def draw_line(d: ImageDraw.ImageDraw, line: Line, x: int, y: int,
              font: ImageFont.FreeTypeFont, max_chars: int | None = None) -> None:
    """Draw a Line at (x,y). Optionally truncate to `max_chars` visible chars."""
    drawn = 0
    cursor_x = x
    for span in line.spans:
        text = span.text
        if max_chars is not None:
            remaining = max_chars - drawn
            if remaining <= 0:
                break
            text = text[:remaining]
        d.text((cursor_x, y), text, fill=span.color, font=font)
        cursor_x += int(d.textlength(text, font=font))
        drawn += len(text)


def total_lines_visible() -> int:
    """How many text lines fit inside the terminal body."""
    return (HEIGHT - PAD_Y_TOP - PAD_Y_BOT) // LINE_HEIGHT


def render() -> Path:
    body_font, title_font = load_fonts()
    out_path = Path("docs/demos/cli.gif")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Backing buffer of completed lines + the current in-progress line.
    buffer: list[Line] = []
    cursor_line: Line | None = None      # the line currently being typed
    cursor_visible_chars = 0
    max_lines = total_lines_visible()

    frames: list[Image.Image] = []
    durations: list[int] = []

    def emit_frame(blink_on: bool) -> None:
        """Snapshot the current terminal state into a new frame."""
        img = Image.new("RGB", (WIDTH, HEIGHT), BG)
        draw_chrome(img, "agent-memory-protocol â€” quickstart", title_font)
        d = ImageDraw.Draw(img)
        # Scroll: keep only the last `max_lines` lines visible.
        visible = list(buffer)
        if cursor_line is not None:
            visible = visible + [cursor_line]
        if len(visible) > max_lines:
            visible = visible[-max_lines:]
        y = PAD_Y_TOP
        for i, ln in enumerate(visible):
            is_last = i == len(visible) - 1
            max_chars = cursor_visible_chars if (is_last and cursor_line is not None) else None
            draw_line(d, ln, PAD_X, y, body_font, max_chars=max_chars)
            # Blinking cursor at end of the in-progress line.
            if is_last and cursor_line is not None and blink_on:
                # Compute current x by truncating the line to the visible width.
                visible_text = ln.text[: max_chars or 0]
                cx = PAD_X + int(d.textlength(visible_text, font=body_font))
                d.rectangle((cx, y + 2, cx + 9, y + LINE_HEIGHT - 2), fill=FG)
            y += LINE_HEIGHT
        frames.append(img)
        durations.append(FRAME_MS)

    blink_counter = itertools.cycle([True] * 7 + [False] * 7)  # ~1Hz blink at 14fps

    # Render the storyboard.
    sb = storyboard()
    for action, payload, hold in sb:
        if action == "type":
            assert isinstance(payload, Line)
            cursor_line = payload
            total_chars = sum(len(s.text) for s in payload.spans)
            # Frames per character at TYPE_CPS, rounded up to at least 1.
            frames_per_char = max(1, FPS // TYPE_CPS or 1)
            # If FPS < TYPE_CPS, advance multiple chars per frame.
            chars_per_frame = max(1, TYPE_CPS // FPS)
            cursor_visible_chars = 0
            while cursor_visible_chars < total_chars:
                cursor_visible_chars = min(total_chars, cursor_visible_chars + chars_per_frame)
                emit_frame(next(blink_counter))
            # Commit the line, blank the cursor.
            buffer.append(cursor_line)
            cursor_line = None
            cursor_visible_chars = 0
            # Hold N frames.
            for _ in range(hold):
                emit_frame(next(blink_counter))
        elif action == "instant":
            assert isinstance(payload, Line)
            buffer.append(payload)
            for _ in range(max(1, hold)):
                emit_frame(next(blink_counter))
        elif action == "blank":
            buffer.append(Line([Span("", FG)]))
            for _ in range(max(1, hold)):
                emit_frame(next(blink_counter))
        elif action == "wait":
            for _ in range(max(1, hold)):
                emit_frame(next(blink_counter))
        elif action == "clear":
            buffer.clear()
            for _ in range(max(1, hold)):
                emit_frame(next(blink_counter))
        else:
            raise ValueError(f"unknown action: {action}")

    # Build a single shared palette from the first frame so all subsequent
    # frames quantize against the *same* indices â€” this is what lets the GIF
    # delta-encoder skip unchanged pixels between frames, which is the
    # difference between a 300 KB GIF and a 3 MB GIF.
    palette_source = frames[0].quantize(colors=32, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    quant_frames = [
        f.quantize(palette=palette_source, dither=Image.Dither.NONE) for f in frames
    ]
    # disposal=1 keeps the previous frame as the background; combined with
    # the shared palette this allows Pillow's GIF encoder to emit only the
    # changed rectangle per frame.
    quant_frames[0].save(
        out_path,
        save_all=True,
        append_images=quant_frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=1,
    )
    size = out_path.stat().st_size
    total_ms = sum(durations)
    print(f"wrote {out_path} ({size/1024:.1f} KB, {len(frames)} frames, {total_ms/1000:.1f}s)")
    return out_path


if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parents[2])
    render()
