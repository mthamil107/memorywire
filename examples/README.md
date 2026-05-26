# Examples

Runnable end-to-end demos for AMP. These ship in **Phase 5**:

| File | What it shows |
|---|---|
| `01_quickstart.py` | Ingest 50 snippets, recall via router, dump one FSM |
| `02_multi_backend.py` | Mix sqlite-vec + mem0 + Letta through the router |
| `03_procedural_fsm.py` | Author and replay a book-flight FSM procedure |
| `04_governance_ui.py` | Pipe writes through the diff-and-approve flow |

Run any example with:

```bash
uv run python examples/01_quickstart.py
```
