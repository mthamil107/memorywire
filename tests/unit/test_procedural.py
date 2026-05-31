"""Tests for :mod:`memwire.procedural` â€” Procedure / ProcedureRunner / validation.

These tests cover the Phase-5 FSM procedural-memory backend:

* Static validation (states/transitions consistency, wildcard handling,
  duplicate-trigger detection).
* Conformance to the ``procedural.json`` content schema.
* Lossless JSON roundtripping (in-memory dict and via ``json.dumps`` to
  prove wire-format compatibility).
* Runtime FSM behaviour driven through :class:`transitions.Machine`
  (advance, invalid-source rejection, wildcard expansion, replay,
  available-triggers reflection, snapshot semantics).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import transitions
from jsonschema import Draft202012Validator

from memwire.procedural import Procedure, ProcedureRunner, validate_procedure_dict

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
PROCEDURAL_SCHEMA_PATH = REPO_ROOT / "src" / "memwire" / "schemas" / "types" / "procedural.json"


def _book_flight() -> Procedure:
    """Construct the canonical book-flight procedure used across tests."""
    return Procedure(
        name="book-flight",
        states=[
            "searching",
            "comparing",
            "selecting",
            "paying",
            "confirmed",
            "cancelled",
        ],
        transitions=[
            {"trigger": "found_options", "source": "searching", "dest": "comparing"},
            {"trigger": "picked", "source": "comparing", "dest": "selecting"},
            {"trigger": "paid", "source": "selecting", "dest": "paying"},
            {"trigger": "receipt", "source": "paying", "dest": "confirmed"},
            {"trigger": "cancel", "source": "*", "dest": "cancelled"},
        ],
        initial="searching",
        metadata={"version": "1.0.0"},
    )


# ---------------------------------------------------------------------------
# Static validation
# ---------------------------------------------------------------------------


def test_validate_passes_on_simple_procedure() -> None:
    proc = _book_flight()
    # No exception â†’ pass.
    proc.validate()


def test_validate_raises_when_dest_not_in_states() -> None:
    proc = Procedure(
        name="broken",
        states=["a", "b"],
        transitions=[{"trigger": "go", "source": "a", "dest": "c"}],
        initial="a",
    )
    with pytest.raises(ValueError, match=r"transition\[0\]\.dest 'c' is not declared"):
        proc.validate()


def test_validate_raises_when_source_not_in_states() -> None:
    proc = Procedure(
        name="broken",
        states=["a", "b"],
        transitions=[{"trigger": "go", "source": "x", "dest": "b"}],
        initial="a",
    )
    with pytest.raises(ValueError, match=r"transition\[0\]\.source 'x' is not declared"):
        proc.validate()


def test_validate_raises_on_duplicate_trigger_from_same_source() -> None:
    proc = Procedure(
        name="dup",
        states=["a", "b", "c"],
        transitions=[
            {"trigger": "go", "source": "a", "dest": "b"},
            {"trigger": "go", "source": "a", "dest": "c"},
        ],
        initial="a",
    )
    with pytest.raises(ValueError, match="duplicate transition"):
        proc.validate()


def test_validate_raises_when_initial_not_in_states() -> None:
    proc = Procedure(
        name="bad-initial",
        states=["a", "b"],
        transitions=[{"trigger": "go", "source": "a", "dest": "b"}],
        initial="z",
    )
    with pytest.raises(ValueError, match=r"'initial' 'z' is not declared"):
        proc.validate()


# ---------------------------------------------------------------------------
# Schema conformance
# ---------------------------------------------------------------------------


def _load_content_schema() -> dict[str, Any]:
    """Return the inline ``content`` sub-schema from procedural.json."""
    with PROCEDURAL_SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        schema: dict[str, Any] = json.load(fh)
    content_schema = schema["properties"]["content"]
    assert isinstance(content_schema, dict)
    return content_schema


def test_to_dict_matches_procedural_content_schema() -> None:
    proc = _book_flight()
    blob = proc.to_dict()
    content_schema = _load_content_schema()
    Draft202012Validator(content_schema).validate(blob)


def test_from_dict_roundtrip_preserves_equality() -> None:
    proc = _book_flight()
    blob = proc.to_dict()
    proc2 = Procedure.from_dict(blob)
    assert proc2 == proc


def test_json_string_roundtrip_proves_wire_compat() -> None:
    proc = _book_flight()
    # Serialize to a JSON string (the wire format), parse it back, and
    # rebuild the Procedure. Field-by-field equality is the assertion.
    wire = json.dumps(proc.to_dict())
    parsed = json.loads(wire)
    assert isinstance(parsed, dict)
    proc2 = Procedure.from_dict(parsed)
    assert proc2 == proc


def test_metadata_roundtrips_when_present() -> None:
    proc = Procedure(
        name="with-meta",
        states=["a", "b"],
        transitions=[{"trigger": "go", "source": "a", "dest": "b"}],
        initial="a",
        metadata={"agent_id": "travel-agent-v2", "version": "1.2.3"},
    )
    proc2 = Procedure.from_dict(proc.to_dict())
    assert proc2.metadata == {"agent_id": "travel-agent-v2", "version": "1.2.3"}
    assert proc2 == proc


# ---------------------------------------------------------------------------
# Runner behaviour
# ---------------------------------------------------------------------------


def test_runner_trigger_advances_state() -> None:
    runner = ProcedureRunner(_book_flight())
    assert runner.current == "searching"
    runner.trigger("found_options")
    assert runner.current == "comparing"


def test_runner_trigger_from_invalid_source_raises_machine_error() -> None:
    runner = ProcedureRunner(_book_flight())
    # ``paid`` is only valid from ``selecting``; firing it from
    # ``searching`` must raise.
    with pytest.raises(transitions.MachineError):
        runner.trigger("paid")


def test_runner_unknown_trigger_raises_machine_error() -> None:
    runner = ProcedureRunner(_book_flight())
    with pytest.raises(transitions.MachineError):
        runner.trigger("does_not_exist")


def test_runner_wildcard_source_works_from_any_state() -> None:
    runner = ProcedureRunner(_book_flight())
    # ``cancel`` declares source="*" â€” must work from initial.
    runner.trigger("cancel")
    assert runner.current == "cancelled"

    # And from a mid-flow state.
    runner2 = ProcedureRunner(_book_flight())
    runner2.trigger("found_options")
    runner2.trigger("picked")
    assert runner2.current == "selecting"
    runner2.trigger("cancel")
    assert runner2.current == "cancelled"


def test_runner_replay_walks_through_happy_path() -> None:
    runner = ProcedureRunner(_book_flight())
    runner.replay(["found_options", "picked", "paid", "receipt"])
    assert runner.current == "confirmed"


def test_runner_replay_restarts_from_initial() -> None:
    runner = ProcedureRunner(_book_flight())
    runner.trigger("cancel")  # move off initial
    runner.replay(["found_options"])
    # After replay we expect to be at the state reached from initial.
    assert runner.current == "comparing"


def test_snapshot_returns_procedure_with_runner_state() -> None:
    proc = _book_flight()
    runner = ProcedureRunner(proc)
    runner.trigger("found_options")
    runner.trigger("picked")
    snap = runner.snapshot()
    assert isinstance(snap, Procedure)
    assert snap.current == "selecting"
    # Other fields preserved.
    assert snap.name == proc.name
    assert snap.states == proc.states
    assert snap.transitions == proc.transitions
    assert snap.metadata == proc.metadata


def test_available_triggers_reflects_current_state() -> None:
    runner = ProcedureRunner(_book_flight())
    # From the initial 'searching' state: ``found_options`` and ``cancel``
    # (wildcard) are available.
    assert sorted(runner.available_triggers) == sorted(["found_options", "cancel"])
    runner.trigger("found_options")
    assert sorted(runner.available_triggers) == sorted(["picked", "cancel"])


# ---------------------------------------------------------------------------
# Module-level validation helper
# ---------------------------------------------------------------------------


def test_validate_procedure_dict_raises_on_malformed_input() -> None:
    with pytest.raises(ValueError, match="missing required key 'name'"):
        validate_procedure_dict({"initial": "a", "states": ["a"], "transitions": []})


def test_validate_procedure_dict_rejects_non_mapping() -> None:
    with pytest.raises(ValueError, match="must be a mapping"):
        validate_procedure_dict("not a dict")  # type: ignore[arg-type]


def test_from_dict_accepts_procedure_without_current_and_defaults_to_initial() -> None:
    blob: dict[str, Any] = {
        "name": "no-current",
        "initial": "a",
        "states": ["a", "b"],
        "transitions": [{"trigger": "go", "source": "a", "dest": "b"}],
    }
    proc = Procedure.from_dict(blob)
    assert proc.current == "a"


# ---------------------------------------------------------------------------
# Security: pytransitions callback keys are an RCE vector â€” reject them.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_key", ["before", "after", "prepare", "on_enter", "on_exit"])
def test_validate_rejects_disallowed_transition_keys(bad_key: str) -> None:
    """Reject pytransitions callback keys â€” they accept dotted strings that
    the engine resolves via ``__import__`` (arbitrary code execution).
    """
    blob: dict[str, Any] = {
        "name": "pwn",
        "initial": "a",
        "states": ["a", "b"],
        "transitions": [
            {"trigger": "go", "source": "a", "dest": "b", bad_key: "os.system"},
        ],
    }
    with pytest.raises(ValueError, match=r"disallowed key"):
        validate_procedure_dict(blob)


def test_validate_rejects_conditions_string_with_dot() -> None:
    """``conditions: "os.system"`` would let pytransitions resolve an import.

    pytransitions only resolves dotted strings to imports for callback keys,
    but defence-in-depth: ban dotted strings in ``conditions``/``unless``
    too. Bare identifiers (resolved against the model) remain allowed.
    """
    blob: dict[str, Any] = {
        "name": "pwn",
        "initial": "a",
        "states": ["a", "b"],
        "transitions": [
            {
                "trigger": "go",
                "source": "a",
                "dest": "b",
                "conditions": "os.system",
            }
        ],
    }
    with pytest.raises(ValueError, match=r"must not contain '\.'"):
        validate_procedure_dict(blob)


def test_validate_rejects_unless_list_with_dotted_string() -> None:
    """``unless`` accepts a list â€” every string element is still constrained."""
    blob: dict[str, Any] = {
        "name": "pwn",
        "initial": "a",
        "states": ["a", "b"],
        "transitions": [
            {
                "trigger": "go",
                "source": "a",
                "dest": "b",
                "unless": ["ok", "shutil.rmtree"],
            }
        ],
    }
    with pytest.raises(ValueError, match=r"must not contain '\.'"):
        validate_procedure_dict(blob)


def test_validate_accepts_conditions_bare_identifier() -> None:
    """Bare identifiers in ``conditions`` are allowed â€” they resolve to
    model attributes, not arbitrary imports.
    """
    blob: dict[str, Any] = {
        "name": "guarded",
        "initial": "a",
        "states": ["a", "b"],
        "transitions": [
            {
                "trigger": "go",
                "source": "a",
                "dest": "b",
                "conditions": "is_authorized",
            }
        ],
    }
    # No exception â†’ allow-listed.
    validate_procedure_dict(blob)


def test_runner_strips_disallowed_keys_from_directly_built_procedure() -> None:
    """``ProcedureRunner._expand_transitions`` defensively strips disallowed
    keys so a :class:`Procedure` built directly (bypassing
    :func:`validate_procedure_dict`) cannot smuggle ``before``/``after``
    callback strings into the underlying pytransitions Machine.

    We can't construct the runner with the bad keys directly because
    ``Procedure.__post_init__`` doesn't run validation â€” that's the path
    the defensive strip is guarding. After construction the runner must
    behave normally and not have wired any extra callbacks.
    """
    proc = Procedure(
        name="bypass",
        states=["a", "b"],
        transitions=[
            # ``before`` / ``after`` would normally be flagged by
            # validate_procedure_dict â€” but Procedure() itself does not
            # validate. The runner's expand step must strip them.
            {
                "trigger": "go",
                "source": "a",
                "dest": "b",
                "before": "os.system",
                "after": "shutil.rmtree",
            }
        ],
        initial="a",
    )
    # The runner constructor calls procedure.validate() which now rejects
    # the disallowed keys â€” so construction itself raises. That is the
    # primary defence; the strip is belt-and-braces. Document the behaviour
    # we observe by asserting the validate-time error.
    with pytest.raises(ValueError, match=r"disallowed key"):
        ProcedureRunner(proc)


def test_expand_transitions_drops_disallowed_keys_when_invoked_directly() -> None:
    """Direct test of the defensive strip in :meth:`ProcedureRunner._expand_transitions`.

    Even if a caller side-steps both validate() and the runner constructor
    and calls the static helper directly, the disallowed keys must not
    survive into the output that would be handed to pytransitions.
    """
    proc = Procedure(
        name="bypass",
        states=["a", "b"],
        transitions=[
            {
                "trigger": "go",
                "source": "a",
                "dest": "b",
                "before": "os.system",
                "after": "shutil.rmtree",
                "prepare": "subprocess.run",
            }
        ],
        initial="a",
    )
    expanded = ProcedureRunner._expand_transitions(proc)
    assert len(expanded) == 1
    out = expanded[0]
    assert "before" not in out
    assert "after" not in out
    assert "prepare" not in out
    assert out == {"trigger": "go", "source": "a", "dest": "b"}
