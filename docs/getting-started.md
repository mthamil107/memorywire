# Getting started

> **WIP** â€” full quickstart lands with `examples/01_quickstart.py` in Phase 5.

## Install

Once published to PyPI:

```bash
pip install memwire
# with sqlite-vec backend
pip install "memwire[sqlite-vec]"
# with everything
pip install "memwire[all]"
```

From source (until first release):

```bash
git clone https://github.com/mthamil107/memwire.git
cd memwire
uv venv
uv pip install -e ".[sqlite-vec]"
```

## Minimal usage

```python
import asyncio
from memwire import Memory, MemoryType

async def main() -> None:
    mem = Memory(
        agent_id="my-agent",
        stores=["sqlite-vec://./mem.db"],
    )
    await mem.remember(
        "Alice is allergic to peanuts",
        type=MemoryType.SEMANTIC,
        user_id="alice@example.com",
    )
    hits = await mem.recall("what should I avoid feeding alice?", k=5)
    for h in hits:
        print(h.score, h.content)

asyncio.run(main())
```

See [`spec/v0.md`](spec/v0.md) for the full protocol surface.
