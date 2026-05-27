"""Protocol-conformance scenarios for every :class:`amp.store.MemoryStore` adapter.

A :class:`ProtocolScenario` is a self-contained description of one AMP
wire-format invariant: a setup of :class:`RememberRequest` writes, an
``action`` callable that exercises the store, and a ``predicate`` that
takes the action's result and returns ``True`` on conformance.

The runner in :mod:`tests.conformance.test_conformance` parametrises this
list across every adapter id and skips scenarios whose
``required_capabilities`` are not satisfied by the candidate store.

Notes
-----
* Scenarios MUST be deterministic across re-runs. No wall-clock-driven
  values escape into predicates; backdate helpers use explicit offsets.
* Scenarios MUST be order-independent. Each one builds its own store from
  the conftest fixture so cross-pollination cannot happen.
* ``setup`` is a list of :class:`RememberRequest`. When an adapter needs
  to backdate a row (for the freshness or age scenarios) it does so via
  the ``backdate`` annotation embedded in metadata
  (``{"_conformance_backdate_ms": <ms>}``); the runner detects this and
  fixes up the per-adapter storage post-write so the scenario is honest.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from amp.models import (
    MemoryType,
    RecallResponse,
    RememberRequest,
    RememberResponse,
)
from amp.store.base import Capability

# ---------------------------------------------------------------------------
# Scenario dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProtocolScenario:
    """One protocol-conformance scenario.

    Parameters
    ----------
    name:
        Stable identifier used as the pytest parametrize id.
    description:
        Human-readable summary; surfaced in the assertion failure message.
    setup:
        A list of :class:`RememberRequest` to write before the action.
    action:
        A coroutine factory ``(store) -> Awaitable[Any]`` that exercises
        the adapter and returns whatever the predicate needs.
    predicate:
        A pure function ``(result) -> bool``. Returns True on conformance.
    required_capabilities:
        Capability strings the adapter MUST declare; otherwise the scenario
        SKIPs. Empty set means "every adapter".
    expects_exception:
        When set, the action is expected to raise this exception type;
        the predicate then receives the exception instance instead of a
        return value.
    """

    name: str
    description: str
    setup: list[RememberRequest]
    action: Callable[[Any], Awaitable[Any]]
    predicate: Callable[[Any], bool]
    required_capabilities: frozenset[str] = field(default_factory=frozenset)
    expects_exception: type[BaseException] | None = None


# ---------------------------------------------------------------------------
# Helpers — predicates and action factories.
#
# Defined at module scope (not inside SCENARIOS) so the resulting closures
# are picklable / debuggable and the dataclass stays frozen.
# ---------------------------------------------------------------------------

AGENT_A = "agent-a"
AGENT_B = "agent-b"  # never used as scope; only as foreign-data sentinel
USER_ALICE = "alice"
USER_BOB = "bob"


def _req(
    *,
    content: str,
    type: MemoryType = MemoryType.SEMANTIC,
    user_id: str | None = USER_ALICE,
    agent_id: str = AGENT_A,
    confidence: float | None = None,
    metadata: dict[str, Any] | None = None,
    approval_required: bool | None = None,
    backdate_days: int | None = None,
) -> RememberRequest:
    """Build a :class:`RememberRequest` with conformance defaults.

    ``backdate_days`` is encoded as ``metadata["_conformance_backdate_ms"]``;
    the conftest's adapter fixtures detect this marker on write and patch
    the stored ``created_at`` accordingly. The marker stays in metadata so
    its presence is observable from a mock.call_args trace too.
    """
    md: dict[str, Any] = dict(metadata or {})
    if backdate_days is not None:
        md["_conformance_backdate_ms"] = backdate_days * 86_400_000
    return RememberRequest(
        agent_id=agent_id,
        user_id=user_id,
        type=type,
        content=content,
        confidence=confidence,
        metadata=md or None,
        approval_required=approval_required,
    )


# ---------------------------------------------------------------------------
# Concrete scenario actions
# ---------------------------------------------------------------------------

from amp.models import (  # noqa: E402 — imports placed here to keep helpers above
    ExpirePolicy,
    ExpireRequest,
    ForgetRequest,
    MergeRequest,
    MergeStrategy,
    RecallRequest,
)


async def _action_basic_recall(store: Any) -> RecallResponse:
    return await store.recall(
        RecallRequest(
            agent_id=AGENT_A,
            user_id=USER_ALICE,
            query="capital France",
            k=3,
        )
    )


def _pred_basic_recall(resp: Any) -> bool:
    if not isinstance(resp, RecallResponse) or not resp.results:
        return False
    contents = " ".join(
        (h.content if isinstance(h.content, str) else "") for h in resp.results
    ).lower()
    return "paris" in contents or "france" in contents


async def _action_user_filter_recall(store: Any) -> RecallResponse:
    return await store.recall(
        RecallRequest(
            agent_id=AGENT_A,
            user_id=USER_ALICE,
            query="favorite color",
            k=5,
        )
    )


def _pred_user_filter_recall(resp: Any) -> bool:
    if not isinstance(resp, RecallResponse):
        return False
    # All returned content must NOT contain Bob's preference (purple).
    for h in resp.results:
        text = (h.content if isinstance(h.content, str) else "").lower()
        if "purple" in text:
            return False
    # And at least one hit should look like Alice's preference (blue) —
    # otherwise we can't verify the scope worked at all.
    contents = " ".join(
        (h.content if isinstance(h.content, str) else "").lower() for h in resp.results
    )
    return "blue" in contents


async def _action_type_filter_recall(store: Any) -> RecallResponse:
    return await store.recall(
        RecallRequest(
            agent_id=AGENT_A,
            user_id=USER_ALICE,
            query="meeting taxes",
            k=5,
            types=[MemoryType.SEMANTIC],
        )
    )


def _pred_type_filter_recall(resp: Any) -> bool:
    if not isinstance(resp, RecallResponse):
        return False
    if not resp.results:
        return False
    return all(h.type is MemoryType.SEMANTIC for h in resp.results)


async def _action_forget_by_ids_then_recall(store: Any) -> RecallResponse:
    # The runner stores the remember-response ids on store._conformance_ids
    # so we can read them back here. See conftest._build_*.
    ids: list[str] = list(getattr(store, "_conformance_ids", []))
    if ids:
        await store.forget(ForgetRequest(agent_id=AGENT_A, ids=ids))
    return await store.recall(
        RecallRequest(
            agent_id=AGENT_A,
            user_id=USER_ALICE,
            query="sky water tree",
            k=5,
        )
    )


def _pred_forget_by_ids(resp: Any) -> bool:
    """After forgetting all seeded ids, recall should return no hits whose id
    is in the forgotten-id list. For adapters whose id format is opaque
    (cognee no-op deletes) we relax to: nothing of the seeded text remains.
    """
    if not isinstance(resp, RecallResponse):
        return False
    # The simple invariant: every hit either is a no-op (no content from
    # this scenario) or the suite agreed-on tombstoned ids are gone. We
    # check by *content*: none of the three seed phrases should still be
    # in the top-k.
    seeds = ("sky is blue", "water is wet", "trees are green")
    for h in resp.results:
        text = (h.content if isinstance(h.content, str) else "").lower()
        if any(seed in text for seed in seeds):
            return False
    return True


async def _action_forget_no_scope(store: Any) -> Any:
    # Will raise ValueError per spec § 3.3 invariant.
    return await store.forget(ForgetRequest(agent_id=AGENT_A))


def _pred_no_scope_raise(result: Any) -> bool:
    return isinstance(result, ValueError)


async def _action_expire_empty_policy(store: Any) -> Any:
    return await store.expire(ExpireRequest(agent_id=AGENT_A))


async def _action_expire_empty_policy_with_empty_object(store: Any) -> Any:
    return await store.expire(ExpireRequest(agent_id=AGENT_A, policy=ExpirePolicy()))


async def _action_expire_by_age(store: Any) -> RecallResponse:
    # Trigger an expire that catches anything older than 180 days. The
    # setup seeds one row backdated 365 days and one row "today".
    await store.expire(
        ExpireRequest(
            agent_id=AGENT_A,
            policy=ExpirePolicy(older_than_days=180),
        )
    )
    return await store.recall(
        RecallRequest(
            agent_id=AGENT_A,
            user_id=USER_ALICE,
            query="ancient fresh fact",
            k=5,
        )
    )


def _pred_expire_by_age(resp: Any) -> bool:
    if not isinstance(resp, RecallResponse):
        return False
    # The 'ancient' phrase must be gone; the 'fresh' one should still be
    # findable (or at least not the ancient one).
    for h in resp.results:
        text = (h.content if isinstance(h.content, str) else "").lower()
        if "ancient" in text:
            return False
    return True


async def _action_merge_keep_canonical(store: Any) -> RecallResponse:
    ids: list[str] = list(getattr(store, "_conformance_ids", []))
    if len(ids) < 2:
        # Adapter didn't surface ids; treat as no-op and return whatever
        # recall does. The predicate will then SKIP-equivalent fail safe.
        return await store.recall(
            RecallRequest(agent_id=AGENT_A, user_id=USER_ALICE, query="duplicate", k=10)
        )
    canonical = ids[0]
    dupes = ids[1:]
    await store.merge(
        MergeRequest(
            agent_id=AGENT_A,
            canonical=canonical,
            duplicates=dupes,
            strategy=MergeStrategy.KEEP_CANONICAL,
        )
    )
    return await store.recall(
        RecallRequest(agent_id=AGENT_A, user_id=USER_ALICE, query="duplicate fact", k=10)
    )


def _pred_merge_keep_canonical(resp: Any) -> bool:
    if not isinstance(resp, RecallResponse):
        return False
    # Count hits that look like duplicates of "duplicate fact". After
    # merging keep_canonical, at most ONE such hit should remain.
    matches = [
        h
        for h in resp.results
        if "duplicate" in (h.content if isinstance(h.content, str) else "").lower()
    ]
    return len(matches) <= 1


async def _action_approval_required(store: Any) -> tuple[RememberResponse, RecallResponse]:
    resp = await store.remember(
        _req(content="High-risk fact pending review", approval_required=True)
    )
    recall = await store.recall(
        RecallRequest(
            agent_id=AGENT_A,
            user_id=USER_ALICE,
            query="High-risk fact pending review",
            k=5,
        )
    )
    return resp, recall


def _pred_approval_required(result: Any) -> bool:
    if not isinstance(result, tuple) or len(result) != 2:
        return False
    resp, recall = result
    if not isinstance(resp, RememberResponse):
        return False
    if resp.pending_approval is not True:
        return False
    # Pending row MUST NOT be recallable.
    if not isinstance(recall, RecallResponse):
        return False
    for h in recall.results:
        text = (h.content if isinstance(h.content, str) else "").lower()
        if "high-risk fact pending" in text:
            return False
    return True


async def _action_capabilities(store: Any) -> Any:
    return store.capabilities


def _pred_capabilities(caps: Any) -> bool:
    if not isinstance(caps, set):
        return False
    if not caps:
        return False
    if not all(isinstance(c, str) and c for c in caps):
        return False
    known = {
        Capability.SEMANTIC,
        Capability.EPISODIC,
        Capability.PROCEDURAL,
        Capability.EMOTIONAL,
        Capability.FTS,
        Capability.VECTOR,
        Capability.GRAPH,
        Capability.GOVERNANCE,
        Capability.RECALL_TRACKING,
    }
    # Every declared capability MUST be a recognised constant — the spec
    # leaves room for backends to declare more, but our reference impl
    # only knows these. Unknown strings indicate a typo.
    return caps.issubset(known)


async def _action_health(store: Any) -> Any:
    return await store.health()


def _pred_health(payload: Any) -> bool:
    return isinstance(payload, dict) and "status" in payload


async def _action_isinstance(store: Any) -> bool:
    from amp.store import MemoryStore

    return isinstance(store, MemoryStore)


def _pred_isinstance(ok: Any) -> bool:
    return ok is True


async def _action_recall_hit_fields(store: Any) -> RecallResponse:
    return await store.recall(
        RecallRequest(
            agent_id=AGENT_A,
            user_id=USER_ALICE,
            query="sun bright shines",
            k=3,
        )
    )


def _pred_recall_hit_fields(resp: Any) -> bool:
    if not isinstance(resp, RecallResponse) or not resp.results:
        return False
    hit = resp.results[0]
    # score is a float, type is a MemoryType, content non-empty,
    # source_store identifies the adapter.
    if not isinstance(hit.score, (int, float)):
        return False
    if not isinstance(hit.type, MemoryType):
        return False
    if not isinstance(hit.content, (str, dict)):
        return False
    return bool(hit.source_store)


async def _action_fresher_than_days(store: Any) -> RecallResponse:
    return await store.recall(
        RecallRequest(
            agent_id=AGENT_A,
            user_id=USER_ALICE,
            query="ancient news fresh news",
            k=5,
            fresher_than_days=30,
        )
    )


def _pred_fresher_than_days(resp: Any) -> bool:
    if not isinstance(resp, RecallResponse):
        return False
    # The 'ancient' phrase must NOT appear.
    for h in resp.results:
        text = (h.content if isinstance(h.content, str) else "").lower()
        if "ancient news" in text:
            return False
    return True


async def _action_multi_remember_recall(store: Any) -> RecallResponse:
    return await store.recall(
        RecallRequest(
            agent_id=AGENT_A,
            user_id=USER_ALICE,
            query="city fact",
            k=10,
        )
    )


def _pred_multi_remember_recall(resp: Any) -> bool:
    if not isinstance(resp, RecallResponse):
        return False
    # Bulk-write 10 facts; expect at least 1 hit (soft threshold — the
    # fake embedder is not semantic, so we cannot demand 10/10).
    return len(resp.results) >= 1


# ---------------------------------------------------------------------------
# Scenario list
# ---------------------------------------------------------------------------

SCENARIOS: list[ProtocolScenario] = [
    ProtocolScenario(
        name="basic_remember_recall",
        description="Writing a semantic fact and recalling by paraphrase returns the fact.",
        setup=[
            _req(content="The capital of France is Paris."),
        ],
        action=_action_basic_recall,
        predicate=_pred_basic_recall,
        required_capabilities=frozenset({Capability.SEMANTIC}),
    ),
    ProtocolScenario(
        name="remember_recall_by_user_filter",
        description=("Recalls scoped by user_id return only the addressed user's memories."),
        setup=[
            _req(content="Alice's favorite color is blue.", user_id=USER_ALICE),
            _req(content="Bob's favorite color is purple.", user_id=USER_BOB),
        ],
        action=_action_user_filter_recall,
        predicate=_pred_user_filter_recall,
        required_capabilities=frozenset({Capability.SEMANTIC}),
    ),
    ProtocolScenario(
        name="type_filter",
        description="Recalls with types=[SEMANTIC] return only semantic memories.",
        setup=[
            _req(
                content="Tax season is in April.",
                type=MemoryType.SEMANTIC,
            ),
            _req(
                content="Had a meeting about taxes last Tuesday.",
                type=MemoryType.EPISODIC,
            ),
        ],
        action=_action_type_filter_recall,
        predicate=_pred_type_filter_recall,
        required_capabilities=frozenset({Capability.SEMANTIC, Capability.EPISODIC}),
    ),
    ProtocolScenario(
        name="forget_by_ids",
        description="Forgetting by id removes the memories from recall results.",
        setup=[
            _req(content="The sky is blue."),
            _req(content="Water is wet."),
            _req(content="Trees are green."),
        ],
        action=_action_forget_by_ids_then_recall,
        predicate=_pred_forget_by_ids,
        required_capabilities=frozenset({Capability.SEMANTIC}),
    ),
    ProtocolScenario(
        name="forget_no_scope_raises",
        description="forget() with neither ids nor filter MUST raise ValueError (spec §3.3).",
        setup=[],
        action=_action_forget_no_scope,
        predicate=_pred_no_scope_raise,
        required_capabilities=frozenset(),
        expects_exception=ValueError,
    ),
    ProtocolScenario(
        name="expire_empty_policy_raises",
        description="expire(policy=None) MUST raise ValueError (spec §3.5).",
        setup=[],
        action=_action_expire_empty_policy,
        predicate=_pred_no_scope_raise,
        required_capabilities=frozenset(),
        expects_exception=ValueError,
    ),
    ProtocolScenario(
        name="expire_empty_policy_object_raises",
        description=(
            "expire(policy=ExpirePolicy()) — an empty policy object — MUST raise (spec §3.5)."
        ),
        setup=[],
        action=_action_expire_empty_policy_with_empty_object,
        predicate=_pred_no_scope_raise,
        required_capabilities=frozenset(),
        expects_exception=ValueError,
    ),
    ProtocolScenario(
        name="expire_by_age",
        description=("expire(older_than_days=180) removes rows backdated past the window."),
        setup=[
            _req(content="An ancient fact from a year ago.", backdate_days=365),
            _req(content="A fresh fact from today."),
        ],
        action=_action_expire_by_age,
        predicate=_pred_expire_by_age,
        required_capabilities=frozenset({Capability.SEMANTIC}),
    ),
    ProtocolScenario(
        name="merge_keep_canonical",
        description=("After merge(keep_canonical) only one of the duplicate rows survives."),
        setup=[
            _req(content="Paris is the duplicate fact one."),
            _req(content="Paris is the duplicate fact two."),
            _req(content="Paris is the duplicate fact three."),
        ],
        action=_action_merge_keep_canonical,
        predicate=_pred_merge_keep_canonical,
        required_capabilities=frozenset({Capability.SEMANTIC}),
    ),
    ProtocolScenario(
        name="approval_required_pending",
        description=(
            "remember(approval_required=True) returns pending_approval=True and is "
            "not visible to recall."
        ),
        setup=[],
        action=_action_approval_required,
        predicate=_pred_approval_required,
        required_capabilities=frozenset(),
    ),
    ProtocolScenario(
        name="capabilities_declared",
        description=("store.capabilities is a non-empty set of known Capability strings."),
        setup=[],
        action=_action_capabilities,
        predicate=_pred_capabilities,
        required_capabilities=frozenset(),
    ),
    ProtocolScenario(
        name="health_returns_status",
        description="health() returns a dict with a 'status' key.",
        setup=[],
        action=_action_health,
        predicate=_pred_health,
        required_capabilities=frozenset(),
    ),
    ProtocolScenario(
        name="isinstance_protocol",
        description="isinstance(store, MemoryStore) is True (runtime_checkable Protocol).",
        setup=[],
        action=_action_isinstance,
        predicate=_pred_isinstance,
        required_capabilities=frozenset(),
    ),
    ProtocolScenario(
        name="recall_returns_score_metadata",
        description=("Recall hits expose score/type/content/source_store fields populated."),
        setup=[
            _req(content="The sun shines bright over the field."),
        ],
        action=_action_recall_hit_fields,
        predicate=_pred_recall_hit_fields,
        required_capabilities=frozenset({Capability.SEMANTIC}),
    ),
    ProtocolScenario(
        name="fresher_than_days_filter",
        description=("Recall with fresher_than_days excludes rows backdated past the window."),
        setup=[
            _req(content="ancient news from a year ago.", backdate_days=365),
            _req(content="fresh news from today."),
        ],
        action=_action_fresher_than_days,
        predicate=_pred_fresher_than_days,
        required_capabilities=frozenset({Capability.SEMANTIC}),
    ),
    ProtocolScenario(
        name="multi_remember_then_recall",
        description=(
            "Bulk-write 10 facts; recall returns at least one hit. "
            "Soft threshold: top-k = 10, expected >= 1 hit. Adapters with a more "
            "specific guarantee can override in conftest."
        ),
        setup=[_req(content=f"city fact number {i:02d} about somewhere.") for i in range(10)],
        action=_action_multi_remember_recall,
        predicate=_pred_multi_remember_recall,
        required_capabilities=frozenset({Capability.SEMANTIC}),
    ),
]


__all__ = ["AGENT_A", "AGENT_B", "SCENARIOS", "USER_ALICE", "USER_BOB", "ProtocolScenario"]
