# Contributing to memwire

Thank you for considering a contribution. memwire is in early v0 development; the
spec and reference implementation are both moving fast. This guide covers the
mechanics of contributing code, spec edits, and adapters.

## Getting started

```bash
# Install uv (https://docs.astral.sh/uv/)
pip install uv

# Clone and set up
git clone https://github.com/mthamil107/memwire.git
cd memwire
uv venv
uv pip install -e ".[sqlite-vec,ui]" --group dev
```

Run the checks:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
uv run pytest -m "not integration"
```

## Branches and commits

- Branch from `main`. Name branches `<type>/<short-summary>` (e.g. `feat/letta-adapter`).
- Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`,
  `docs:`, `chore:`, `refactor:`, `test:`, `perf:`.
- Do **not** add `Co-Authored-By` trailers to commit messages.

## Pull requests

- One concern per PR. A new adapter, a spec edit, and a bug fix should be three
  PRs, not one.
- Every PR adds or updates tests. Mock backends for unit tests
  (`tests/unit/`); real backends only in `tests/integration/`.
- For spec edits, the implementation must follow within the same PR set, not
  the same PR Ã¢â‚¬â€ but reference the spec change in the implementation PR.

## Spec edits

The spec is the source of truth. If the implementation does something the spec
doesn't describe, that's a spec bug Ã¢â‚¬â€ fix the spec first. See `docs/spec/v0.md`
for the current draft and `docs/kickoff/memwire-SPEC-v0.md` for original draft history.

Operation schemas live in `src/memwire/schemas/operations/`. Type schemas live in
`src/memwire/schemas/types/`. Every change there must add or update a worked example
in `docs/spec/examples/` and pass `python scripts/verify_spec.py`.

## Adding a new backend adapter

See `docs/adapters.md`. The short version:

1. Implement `memwire.store.base.MemoryStore` for your backend in
   `src/memwire/store/<your_backend>.py`.
2. Declare your `capabilities` set.
3. Add the dependency to `[project.optional-dependencies]` in `pyproject.toml`
   under a matching extra name.
4. Add unit tests with a mocked backend in `tests/unit/store/`.
5. Add integration tests in `tests/integration/store/` marked
   `@pytest.mark.integration`.

## Reporting bugs and security issues

- General bugs: open an issue on GitHub.
- Security: see [`SECURITY.md`](SECURITY.md).

## Code of Conduct

Participation in this project is governed by the
[Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).
