# Tape script for the AMP CLI launch demo GIF.
#
# Canonical renderer: `charmbracelet/vhs`. On Linux/macOS run:
#     vhs docs/demos/cli.tape
#
# Windows fallback: VHS on Windows depends on ttyd, which uses ConPTY in
# a way that ttyd 1.7.x does not drive cleanly under VHS â€” the run
# produces no frames. Until that lands upstream we render the same
# storyboard deterministically via:
#     .venv/Scripts/python.exe docs/demos/render_cli.py
# That script (Pillow + Cascadia Mono) produces the identical
# `docs/demos/cli.gif` artifact this tape would emit on Linux.
#
# Pre-requisites if you do run this with VHS:
#   - amp installed in $PATH (or activate the project venv first)
#   - HF_HUB_OFFLINE=1 + the sentence-transformers model pre-cached
#     (otherwise each `amp recall` call blocks for 10-25s on cold load)
#   - rm -f ./memwire-cli.db    # clean state

Output docs/demos/cli.gif

Set FontSize 16
Set FontFamily "CaskaydiaCove Nerd Font Mono"
Set Width 900
Set Height 560
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set PlaybackSpeed 1.0
Set Padding 24
Set Framerate 12

# ---- Section 1: install (faked â€” real install would be ~30s) -----------
Type "# Install with three day-1 backends"
Sleep 600ms
Enter
Type `pip install "agent-memory-protocol[sqlite-vec,mem0,letta]"`
Sleep 400ms
Enter
# Skip the real install. Show only the success line so the demo stays focused.
Type "echo Successfully installed agent-memory-protocol-0.1.0"
Sleep 200ms
Enter
Sleep 900ms

# ---- Section 2: import works -------------------------------------------
Type `python -c "from amp import Memory, MemoryType; print(Memory)"`
Sleep 400ms
Enter
Sleep 900ms

# ---- Section 3: quickstart ---------------------------------------------
Type "# Route across two backends, recall, forget"
Sleep 500ms
Enter
Type "python examples/01_quickstart.py 2>&1 | tail -10"
Sleep 400ms
Enter
Sleep 4000ms

# ---- Section 4: CLI ----------------------------------------------------
Type "# CLI: same Memory, called from the shell"
Sleep 500ms
Enter
Type `amp --quiet remember "Alice prefers email over phone" --type semantic --user alice`
Sleep 400ms
Enter
Sleep 700ms

Type `amp --quiet recall "how should I contact alice?" -k 3`
Sleep 400ms
Enter
Sleep 1500ms

# Final hold so the GIF doesn't snap back to frame 0.
Sleep 1400ms
