"""Author, drive, serialize, and reload a procedural FSM (spec section 7).

Runnable demo of the Phase-5 :mod:`memwire.procedural` backend:

1. Build the canonical ``book-flight`` procedure from spec Â§7.
2. Statically validate the procedure.
3. Drive it through the happy path:
   ``found_options â†’ picked â†’ paid â†’ receipt``.
4. Demonstrate the ``"source": "*"`` wildcard idiom by ``cancel`` from a
   mid-flow state.
5. Roundtrip through ``to_dict()`` / JSON / ``from_dict()`` and assert
   field-by-field equality with the original.

Run with::

    .venv/Scripts/python.exe examples/03_procedural_fsm.py
"""

from __future__ import annotations

import json

from memwire.procedural import Procedure, ProcedureRunner


def build_book_flight() -> Procedure:
    """Construct the spec Â§7 ``book-flight`` procedure."""
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
        metadata={"version": "1.0.0", "agent_id": "travel-agent-v2"},
    )


def main() -> None:
    """Run the procedural-FSM walkthrough."""
    proc = build_book_flight()
    proc.validate()
    print(
        f"[validate] {proc.name!r} ok ({len(proc.states)} states, "
        f"{len(proc.transitions)} transitions)"
    )

    # ----- Happy path -----------------------------------------------------
    runner = ProcedureRunner(proc)
    print(f"[start]   current={runner.current!r}")
    for trigger in ("found_options", "picked", "paid", "receipt"):
        runner.trigger(trigger)
        print(f"[do]      trigger={trigger!r:<18} current={runner.current!r}")

    assert runner.current == "confirmed", "happy path should end at 'confirmed'"

    # ----- Wildcard cancel from mid-flow ---------------------------------
    runner2 = ProcedureRunner(proc)
    runner2.replay(["found_options", "picked"])
    print(f"[mid]     current={runner2.current!r}, available={runner2.available_triggers}")
    runner2.trigger("cancel")
    print(f"[do]      trigger={'cancel'!r:<18} current={runner2.current!r}")
    assert runner2.current == "cancelled", "wildcard cancel should reach 'cancelled'"

    # ----- JSON roundtrip -------------------------------------------------
    blob = proc.to_dict()
    wire = json.dumps(blob, indent=2)
    print("[serialize] procedure content JSON:")
    print(wire)
    proc2 = Procedure.from_dict(json.loads(wire))
    assert proc2 == proc, "JSON roundtrip must preserve field-by-field equality"
    print("[roundtrip] from_dict(to_dict(p)) == p  -> True")

    # ----- Snapshot after running ----------------------------------------
    runner3 = ProcedureRunner(proc)
    runner3.trigger("found_options")
    snap = runner3.snapshot()
    assert snap.current == "comparing"
    print(f"[snapshot] current={snap.current!r}")


if __name__ == "__main__":
    main()
