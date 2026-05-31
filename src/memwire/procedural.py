"""FSM-backed procedural-memory backend for memwire (spec section 7).

This module provides a thin, JSON-serializable wrapper around the
:mod:`transitions` library so callers can author, validate, replay, and
re-serialize procedural memories (per :file:`docs/spec/v0.md` Â§7).

Two public classes:

* :class:`Procedure` â€” a JSON-friendly dataclass mirroring the
  ``content`` shape declared by
  :file:`src/memwire/schemas/types/procedural.json`. Roundtrips losslessly via
  :meth:`Procedure.to_dict` / :meth:`Procedure.from_dict`. Performs static
  validation independent of any runtime FSM engine.
* :class:`ProcedureRunner` â€” wraps a :class:`transitions.Machine` so the
  procedure can actually be driven. Resolves the spec's ``"source": "*"``
  wildcard idiom by expanding it to every declared state at construction
  time (so the underlying engine sees only fully-qualified transitions).

Both classes are deliberately framework-thin: the heavy lifting lives in
the :mod:`transitions` library, and our wrapper only enforces the
spec-level invariants (states/transitions consistency, the wildcard
contract, JSON-serialisability of the configuration).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import transitions

# The pytransitions wildcard idiom. memwire v0 spec Â§7 (Editor's note) names
# this character explicitly; we centralise it so any future change is a
# single-line edit.
_WILDCARD: str = "*"


# Keys that may appear on a procedure-content dict. Validation rejects
# missing required keys; optional keys default to None / empty.
_REQUIRED_KEYS: tuple[str, ...] = ("name", "initial", "states", "transitions")


# Keys allowed on a transition dict. ANYTHING else â€” in particular
# pytransitions' ``before`` / ``after`` / ``prepare`` callback keys â€” is
# rejected because pytransitions resolves string callbacks via
# ``__import__(module)`` + ``getattr``, which is an arbitrary-code-execution
# vector: a procedural memory with ``"before": "os.system"`` would run
# ``os.system(...)`` when the trigger fires.
#
# ``conditions`` and ``unless`` are permitted (they gate transitions) BUT
# their string values are restricted below to bare identifiers (no ``.``)
# because pytransitions only resolves dotted strings to imports for
# callback keys; ``conditions``/``unless`` strings are looked up as
# attributes on the model. Restricting to identifiers means they can only
# resolve to model attributes (which our private :class:`_ProcedureModel`
# does not expose), never to arbitrary imports.
_ALLOWED_TRANSITION_KEYS: frozenset[str] = frozenset(
    {"trigger", "source", "dest", "conditions", "unless"}
)


def validate_procedure_dict(data: dict[str, Any]) -> None:
    """Validate a procedure-content dict per spec Â§7. Raise ``ValueError`` on failure."""
    if not isinstance(data, dict):
        raise ValueError(f"procedure dict must be a mapping; got {type(data).__name__}")
    for key in _REQUIRED_KEYS:
        if key not in data:
            raise ValueError(f"procedure dict missing required key {key!r}")

    name = data["name"]
    initial = data["initial"]
    states = data["states"]
    raw_transitions = data["transitions"]

    if not isinstance(name, str) or not name:
        raise ValueError("procedure 'name' must be a non-empty string")
    if not isinstance(initial, str) or not initial:
        raise ValueError("procedure 'initial' must be a non-empty string")
    if not isinstance(states, list) or not states:
        raise ValueError("procedure 'states' must be a non-empty list")
    for st in states:
        if not isinstance(st, str) or not st:
            raise ValueError("every entry in 'states' must be a non-empty string")
    if not isinstance(raw_transitions, list):
        raise ValueError("procedure 'transitions' must be a list")

    state_set = set(states)
    if initial not in state_set:
        raise ValueError(
            f"procedure 'initial' {initial!r} is not declared in 'states' {sorted(state_set)!r}"
        )

    current = data.get("current")
    if current is not None:
        if not isinstance(current, str) or not current:
            raise ValueError("procedure 'current' must be a non-empty string when set")
        if current not in state_set:
            raise ValueError(
                f"procedure 'current' {current!r} is not declared in 'states' {sorted(state_set)!r}"
            )

    seen: set[tuple[str, str]] = set()
    for idx, tr in enumerate(raw_transitions):
        if not isinstance(tr, dict):
            raise ValueError(f"transition[{idx}] must be an object; got {type(tr).__name__}")
        for key in ("trigger", "source", "dest"):
            if key not in tr:
                raise ValueError(f"transition[{idx}] missing required key {key!r}")
        # Reject any keys outside the safe allow-list. pytransitions'
        # ``before`` / ``after`` / ``prepare`` callback keys accept dotted
        # strings that the engine resolves via ``__import__`` â€” i.e. an RCE
        # vector. We refuse them outright at validation time.
        disallowed = sorted(set(tr.keys()) - _ALLOWED_TRANSITION_KEYS)
        if disallowed:
            raise ValueError(
                f"transition[{idx}] has disallowed key(s) {disallowed!r}; "
                f"allowed keys are {sorted(_ALLOWED_TRANSITION_KEYS)!r}"
            )
        # ``conditions`` and ``unless`` may be a method name (string) or a
        # list of method names. Restrict string values to bare identifiers
        # (no ``.``) so pytransitions resolves them to attributes on the
        # model and not to imported modules.
        for guard_key in ("conditions", "unless"):
            if guard_key not in tr:
                continue
            raw_guard = tr[guard_key]
            guard_values: list[Any] = (
                list(raw_guard) if isinstance(raw_guard, list) else [raw_guard]
            )
            for gv in guard_values:
                if isinstance(gv, str) and "." in gv:
                    raise ValueError(
                        f"transition[{idx}].{guard_key} {gv!r} must not contain '.': "
                        f"only bare identifiers (resolved against the FSM model) are "
                        f"permitted, to avoid pytransitions importing arbitrary modules"
                    )
        trigger = tr["trigger"]
        source = tr["source"]
        dest = tr["dest"]
        if not isinstance(trigger, str) or not trigger:
            raise ValueError(f"transition[{idx}].trigger must be a non-empty string")
        if not isinstance(source, str) or not source:
            raise ValueError(f"transition[{idx}].source must be a non-empty string")
        if not isinstance(dest, str) or not dest:
            raise ValueError(f"transition[{idx}].dest must be a non-empty string")
        if dest not in state_set:
            raise ValueError(
                f"transition[{idx}].dest {dest!r} is not declared in 'states' {sorted(state_set)!r}"
            )
        # Source: "*" is the spec wildcard; otherwise must be a declared state.
        sources = list(state_set) if source == _WILDCARD else [source]
        if source != _WILDCARD and source not in state_set:
            raise ValueError(
                f"transition[{idx}].source {source!r} is not declared in 'states' "
                f"{sorted(state_set)!r}"
            )
        for src in sources:
            pair = (src, trigger)
            if pair in seen:
                raise ValueError(
                    f"duplicate transition: trigger {trigger!r} already defined from source {src!r}"
                )
            seen.add(pair)


@dataclass
class Procedure:
    """A JSON-serializable procedural-memory definition (spec Â§7)."""

    name: str
    initial: str
    states: list[str]
    transitions: list[dict[str, Any]]
    current: str | None = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """Default ``current`` to ``initial`` when unset; defensively copy mutables."""
        # Copy mutables so external mutation of the source lists doesn't
        # silently corrupt the procedure's invariants.
        self.states = list(self.states)
        self.transitions = [dict(t) for t in self.transitions]
        if self.metadata is not None:
            self.metadata = dict(self.metadata)
        if self.current is None:
            self.current = self.initial

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict matching the procedural content schema."""
        out: dict[str, Any] = {
            "name": self.name,
            "initial": self.initial,
            "states": list(self.states),
            "transitions": [dict(t) for t in self.transitions],
            "current": self.current if self.current is not None else self.initial,
        }
        if self.metadata is not None:
            out["metadata"] = dict(self.metadata)
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Procedure:
        """Build a :class:`Procedure` from a procedure-content dict."""
        if not isinstance(data, dict):
            raise ValueError(f"procedure dict must be a mapping; got {type(data).__name__}")
        for key in _REQUIRED_KEYS:
            if key not in data:
                raise ValueError(f"procedure dict missing required key {key!r}")

        # Build, then validate, so the validate() call sees a fully-formed
        # Procedure (matches the in-process construction path).
        proc = cls(
            name=data["name"],
            initial=data["initial"],
            states=list(data["states"]),
            transitions=[dict(t) for t in data["transitions"]],
            current=data.get("current"),
            metadata=dict(data["metadata"]) if data.get("metadata") is not None else None,
        )
        proc.validate()
        return proc

    def validate(self) -> None:
        """Assert all spec Â§7 invariants. Raise ``ValueError`` on failure."""
        validate_procedure_dict(self.to_dict())

    def __eq__(self, other: object) -> bool:
        """Field-by-field equality (ignores transient runtime state)."""
        if not isinstance(other, Procedure):
            return NotImplemented
        return (
            self.name == other.name
            and self.initial == other.initial
            and self.states == other.states
            and self.transitions == other.transitions
            and self.current == other.current
            and self.metadata == other.metadata
        )

    def __hash__(self) -> int:  # pragma: no cover - dataclass with lists is unhashable by design
        """Procedures contain mutable lists/dicts so they are not hashable."""
        raise TypeError("Procedure is mutable and not hashable")


@dataclass
class _ProcedureModel:
    """Private model object that holds the FSM's ``state`` attribute.

    The :mod:`transitions` library mutates ``model.state`` as transitions
    fire. We use a dedicated tiny holder rather than ``self`` so the
    runner stays a plain wrapper without inheriting the engine's dynamic
    attributes.
    """

    state: str = field(default="")


class ProcedureRunner:
    """A thin :class:`transitions.Machine` wrapper that drives a :class:`Procedure`."""

    def __init__(self, procedure: Procedure) -> None:
        """Build a :class:`transitions.Machine` from ``procedure``; expand ``"*"`` sources."""
        # Validate up front so a malformed procedure fails before the FSM
        # engine sees it (and so the wildcard expansion below is safe).
        procedure.validate()
        self._procedure = procedure
        self._model = _ProcedureModel()

        expanded = self._expand_transitions(procedure)

        # auto_transitions=False keeps the public trigger surface clean: no
        # implicit ``to_<state>`` triggers crowd the spec-defined names.
        self._machine = transitions.Machine(
            model=self._model,
            states=list(procedure.states),
            transitions=expanded,
            initial=procedure.current or procedure.initial,
            auto_transitions=False,
            send_event=False,
            ignore_invalid_triggers=False,
        )

    @staticmethod
    def _expand_transitions(procedure: Procedure) -> list[dict[str, Any]]:
        """Expand ``"source": "*"`` rows to one row per declared state.

        Defensively drops any keys outside :data:`_ALLOWED_TRANSITION_KEYS`
        before forwarding to :class:`transitions.Machine`. This is
        belt-and-braces: :func:`validate_procedure_dict` should already
        have rejected disallowed keys, but a caller can build a
        :class:`Procedure` directly without going through ``from_dict``.
        Forwarding e.g. ``before="os.system"`` to pytransitions would
        execute arbitrary code at trigger time, so we strip it here as
        well as rejecting it at validation.
        """

        def _safe(tr: dict[str, Any]) -> dict[str, Any]:
            return {k: v for k, v in tr.items() if k in _ALLOWED_TRANSITION_KEYS}

        out: list[dict[str, Any]] = []
        for tr in procedure.transitions:
            sanitized = _safe(tr)
            if sanitized.get("source") == _WILDCARD:
                # Emit one transition per state. Only the allow-listed keys
                # (trigger/source/dest/conditions/unless) are forwarded.
                for state in procedure.states:
                    expanded_row = dict(sanitized)
                    expanded_row["source"] = state
                    out.append(expanded_row)
            else:
                out.append(sanitized)
        return out

    @property
    def current(self) -> str:
        """The runner's current state name."""
        return str(self._model.state)

    @property
    def available_triggers(self) -> list[str]:
        """The triggers callable from the runner's current state."""
        return list(self._machine.get_triggers(self._model.state))

    def trigger(self, name: str) -> None:
        """Fire the named transition; raise :class:`transitions.MachineError` if invalid."""
        # Dispatch via Machine.dispatch so the model doesn't need any
        # specific trigger methods bound to it. If the trigger name isn't
        # configured the engine raises AttributeError; translate that to
        # MachineError to keep the public contract consistent.
        try:
            fired = self._machine.dispatch(name)
        except AttributeError as exc:
            raise transitions.MachineError(
                f"Unknown trigger {name!r} for procedure {self._procedure.name!r}"
            ) from exc
        if not fired:
            # dispatch() returns False when the trigger exists but is not
            # valid from the current state and ignore_invalid_triggers is
            # truthy. We always set it False above, but defensively raise.
            raise transitions.MachineError(
                f"Trigger {name!r} not valid from state {self.current!r}"
            )

    def do(self, name: str) -> None:
        """Alias for :meth:`trigger` to match the spec's verb-first phrasing."""
        self.trigger(name)

    def snapshot(self) -> Procedure:
        """Return a new :class:`Procedure` with ``current`` set to the runner's state."""
        return Procedure(
            name=self._procedure.name,
            initial=self._procedure.initial,
            states=list(self._procedure.states),
            transitions=[dict(t) for t in self._procedure.transitions],
            current=self.current,
            metadata=(
                dict(self._procedure.metadata) if self._procedure.metadata is not None else None
            ),
        )

    def replay(self, triggers: list[str]) -> None:
        """Apply ``triggers`` in order starting from the procedure's ``initial`` state."""
        # Reset to initial so callers can replay a run from the top.
        self._machine.set_state(self._procedure.initial)
        for name in triggers:
            self.trigger(name)


__all__ = ["Procedure", "ProcedureRunner", "validate_procedure_dict"]
