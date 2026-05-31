"""Cross-adapter conformance test runner.

Each cell of the matrix (5 adapters x N scenarios) is one test case:

    test_conformance[<scenario.name>-<adapter_id>]

A cell SKIPs when:
* The scenario declares ``required_capabilities`` the adapter does not
  satisfy.
* The adapter has a documented per-scenario override in
  :data:`SKIP_OVERRIDES`.

Otherwise the runner:
1. Builds a fresh store via the parametrized fixture.
2. Replays the scenario's setup remember() requests, capturing ids.
3. Awaits the scenario's action (or expects the documented exception).
4. Asserts the scenario's predicate on the result.
"""

from __future__ import annotations

import contextlib
from typing import Any

import pytest

from memorywire.store import MemoryStore
from tests.conformance.scenarios import SCENARIOS, ProtocolScenario

from .conftest import SKIP_OVERRIDES


def _check_capabilities(store: Any, scenario: ProtocolScenario) -> None:
    """Skip with a clear reason if the store doesn't declare what the scenario needs."""
    required = scenario.required_capabilities
    if not required:
        return
    declared = store.capabilities
    missing = required - declared
    if missing:
        pytest.skip(f"adapter does not declare required capabilities: {sorted(missing)}")


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
async def test_conformance(adapter_id: str, store: Any, scenario: ProtocolScenario) -> None:
    """Run one ``(adapter_id, scenario)`` cell of the conformance matrix."""
    # The fixture for ``store`` is already parametrized over adapter_id.
    overrides = SKIP_OVERRIDES.get(adapter_id, {})
    if scenario.name in overrides:
        pytest.skip(overrides[scenario.name])

    _check_capabilities(store, scenario)

    # Setup.
    setup_ids: list[str] = []
    for req in scenario.setup:
        resp = await store.remember(req)
        if resp.id and not resp.id.startswith(("pending:",)):
            setup_ids.append(resp.id)
    # Stash for action access (forget_by_ids, merge use this). Some
    # Protocol-conforming objects might be frozen; suppress AttributeError.
    with contextlib.suppress(AttributeError):
        store._conformance_ids = setup_ids

    # Action + predicate.
    if scenario.expects_exception is not None:
        with pytest.raises(scenario.expects_exception) as excinfo:
            await scenario.action(store)
        assert scenario.predicate(excinfo.value), (
            f"scenario {scenario.name!r}: predicate rejected exception "
            f"{excinfo.value!r}: {scenario.description}"
        )
    else:
        result = await scenario.action(store)
        assert scenario.predicate(result), (
            f"scenario {scenario.name!r}: predicate failed on result={result!r}: "
            f"{scenario.description}"
        )


def test_store_is_a_memory_store(store: Any) -> None:
    """Sanity check: every fixture builds a runtime-checkable MemoryStore."""
    assert isinstance(store, MemoryStore)


def test_capabilities_are_strings(store: Any) -> None:
    """Sanity check: every adapter's capabilities are a non-empty set of strings."""
    caps = store.capabilities
    assert isinstance(caps, set) and caps
    assert all(isinstance(c, str) and c for c in caps)
