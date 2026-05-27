# Tasks — the five governance-UI scenarios

> All tasks run against the seeded demo database produced by
> `docs/demos/seed_demo_db.py`. That seed creates:
>
> - `agent_id = customer-bot`, `user_id = alice@acme.com`
> - 2 **approved** semantic memories about Alice (order history,
>   plan tier).
> - 2 **pending** memories — one semantic (Alice prefers email over
>   phone), one episodic (Alice reported a billing issue with order
>   #7821 on 2026-05-27).
> - 1 historical audit-log row (a prior approval from 2 hours
>   earlier) so `/audit` is not empty.
>
> Tasks T3 and T5 require additional rows beyond the base seed. Each
> task's "Setup" section calls out the SQL or seeder amendment the
> researcher should apply before the task begins. Researchers should
> apply the augmentation to a **copy** of `demo-ui.db` so the base
> seed is never mutated.

---

## T1. Approve a routine pending memory (warm-up)

**Task ID:** T1
**Time budget:** 3 min
**Difficulty:** Low — designed as a warm-up so the participant gets
familiar with the screen mechanics before higher-stakes tasks.

### Setup

Base seed only. No augmentation needed.

### Task statement (read to participant)

> You are an operations engineer reviewing memory writes for a
> customer-support bot. A new pending memory has come in saying
> "Customer alice@acme.com prefers email over phone." Take a look at
> the pending approvals queue, decide whether to approve or reject
> that memory, and click the button. Tell me out loud what made you
> pick the action you picked.

### Expected interaction

Participant navigates to `/`, finds the pending semantic memory
"Customer alice@acme.com prefers email over phone." in the queue,
reads the diff (which shows it does not contradict any existing
memory under `entity_name=alice@acme.com`), and clicks Approve.

### Success criterion

Participant clicks **Approve** on the pending memory whose content
contains "prefers email over phone" within the time budget. (Reject is
defensible if the participant articulates a specific concern; record
as "soft-success" with the reasoning verbatim in notes.)

### Signal collected

- Time to first approve click.
- Did they read the diff before clicking? (Note from think-aloud.)
- Confidence in their decision (post-task Likert Q1).

---

## T2. Reject a memory because it contradicts an existing one

**Task ID:** T2
**Time budget:** 3 min
**Difficulty:** Medium — the diff must be **read carefully** for the
participant to notice the contradiction.

### Setup

Augment the base seed by inserting a **third pending memory** under
`customer-bot / alice@acme.com` with content that directly contradicts
the existing approved row "Alice's plan tier is Pro." The contradicting
content is: "Alice's plan tier is Free." Same `entity_name`,
`source=billing_sync`, `confidence=0.78`, `approval_required=True`.

Add this row by running, from the repo root:

```python
# Augmentation snippet for T2 — copy demo-ui.db first, then run
import asyncio
from amp.models import MemoryType, RememberRequest
from amp.store.sqlite_vec import SqliteVecStore

async def main():
    store = SqliteVecStore(db_path="docs/demos/demo-ui-T2.db",
                           embedder=lambda t: [0.0]*16, embedding_dim=16)
    await store.remember(RememberRequest(
        agent_id="customer-bot",
        user_id="alice@acme.com",
        type=MemoryType.SEMANTIC,
        content="Alice's plan tier is Free.",
        metadata={"entity_name": "alice@acme.com", "source": "billing_sync"},
        confidence=0.78,
        source="billing_sync",
        approval_required=True,
    ))
    store.close()

asyncio.run(main())
```

Point the UI at `docs/demos/demo-ui-T2.db` for this task.

### Task statement (read to participant)

> Three pending memories are in the queue. Review each one and act on
> the one you think should not be approved. If you think a memory
> conflicts with what's already known, reject it and tell me why.

### Expected interaction

Participant scans all three pending rows. On the "Alice's plan tier
is Free" row, the diff view shows the existing approved row "Alice's
plan tier is Pro" under the same `entity_name`. Participant identifies
the contradiction, clicks Reject, and (ideally) leaves a reason in the
reason field.

### Success criterion

Participant clicks **Reject** on the "plan tier is Free" pending row,
and articulates the contradiction with the existing "plan tier is Pro"
row within the time budget. Approving the row, or rejecting a
different row, counts as failure for this task.

### Signal collected

- Time to reject.
- Did the participant verbalize the contradiction explicitly?
- Did they fill in a reason? (Counts as evidence the field is
  discoverable.)

---

## T3. Bulk co-memorize — review 5 forget candidates

**Task ID:** T3
**Time budget:** 3 min
**Difficulty:** Medium-high — requires reading 5 rows and making
distinct decisions per row.

### Setup

After the base seed, insert 5 additional **approved** memories under
`customer-bot / alice@acme.com`, with timestamps spread between 30
and 180 days ago, that the co-memorize panel will flag as forget
candidates. Specifically: 2 obviously stale ("Alice was traveling on
2025-12-03"), 2 stale-but-borderline ("Alice's preferred timezone is
PST" — still plausibly relevant), and 1 not actually stale ("Alice's
account-tier upgrade date is 2026-04-12"). The co-memorize panel ranks
these by staleness score; the task is to disagree with the panel on at
least one row.

The augmentation script lives at `docs/paper/user-study/scripts/seed_T3.py`
(create alongside this file if it does not yet exist; or run the SQL
inserts inline).

### Task statement (read to participant)

> Navigate to the co-memorize panel. The system has flagged five
> memories as candidates for being forgotten. Review each one. For
> each, decide whether to forget, keep, or merge (when the option is
> offered). Tell me your reasoning for each row.

### Expected interaction

Participant clicks "co-memorize" in the top nav, reads each of the 5
candidate rows along with the system-generated reasoning, makes a
per-row decision. The expected pattern: forget the 2 obviously stale,
keep the 1 not-actually-stale, and reason carefully about the 2
borderline ones.

### Success criterion

Participant **makes a deliberate per-row decision for all 5 rows**
within the time budget (action taken or explicit "keep" — not just
scrolling past). The PI does not pre-define a "correct" answer for
this task; the signal is decision quality, captured via think-aloud.

### Signal collected

- Number of rows decisioned (out of 5).
- Did the participant disagree with the system's recommendation on at
  least one row? (Indicates they read the reasoning rather than
  rubber-stamping.)
- Time to clear all 5 rows.

---

## T4. Audit-log triage — find when a specific memory was last modified

**Task ID:** T4
**Time budget:** 3 min
**Difficulty:** Medium — tests the audit log's filtering / search
discoverability.

### Setup

Base seed plus one extra `audit_log` row 30 minutes ago for a
`forget` operation on a fake memory id `mem_alice_history_v0`. The
historical-approval row from the base seed plus this forget row gives
the participant two `alice@acme.com`-related audit rows to find among
distractors.

Insert via:

```sql
INSERT INTO audit_log (ts, operation, agent_id, user_id, memory_id,
                       payload, result, approved_by, approval_at)
VALUES (strftime('%s','now') * 1000 - 30*60*1000, 'forget', 'customer-bot',
        'alice@acme.com', 'mem_alice_history_v0',
        '{"reason":"superseded by crm_sync"}',
        '{"forgotten":true}', 'ops@acme.com',
        strftime('%s','now') * 1000 - 30*60*1000);
```

### Task statement (read to participant)

> Your manager wants to know when Alice's order-history memory was
> last modified. Use the audit log to find any modifications related
> to Alice's data in the past 24 hours, and tell me the most recent
> one and what time it happened.

### Expected interaction

Participant navigates to `/audit`, filters by `user_id=alice@acme.com`
(or by date range, or scrolls), identifies the `forget` row from 30
minutes ago as the most recent.

### Success criterion

Participant identifies the **30-minutes-ago `forget` row** as the most
recent Alice-related audit event within the time budget. Identifying
the 2-hours-ago approval row instead counts as partial success.

### Signal collected

- Did they find a filter mechanism, or did they scroll?
- Time to first correct identification.
- Did they notice the operation type (`forget` vs `remember`) on the
  rows?

---

## T5. Approval-pattern recommendation — accept or decline an auto-allow

**Task ID:** T5
**Time budget:** 3 min
**Difficulty:** High — requires understanding the implications of
delegating future approvals to an automated rule.

### Setup

Augment the base seed by inserting an `approval_patterns` row that
recommends auto-allowing memories where `source = "crm_sync" AND
type = "semantic"` based on 12 consistent approve decisions across the
past 30 days, with 0 rejects. Provide the supporting count so the
participant can see the basis.

Insert via:

```sql
INSERT INTO approval_patterns (pattern_key, predicate_json,
                               approve_count, reject_count,
                               recommendation_state, created_at,
                               updated_at, agent_id)
VALUES ('crm_sync_semantic',
        '{"source":"crm_sync","type":"semantic"}',
        12, 0, 'recommended', strftime('%s','now')*1000,
        strftime('%s','now')*1000, 'customer-bot');
```

(Confirm the exact column names against
`ui/src/amp_ui/services.py` before running; the example above is the
shape, names may vary.)

### Task statement (read to participant)

> Navigate to the patterns panel. The system is recommending that you
> auto-allow a class of memory writes based on your past decisions.
> Look at the recommendation. Decide whether to accept it, decline
> it, or do nothing. Tell me your reasoning.

### Expected interaction

Participant clicks "patterns" in the top nav. Reads the recommendation:
"You've approved 12 of 12 semantic memories from source `crm_sync`
over the past 30 days. Auto-allow this pattern going forward?" The
participant should ideally consider: how representative are 12
samples? What if `crm_sync` is compromised in the future? Does
auto-allow have a kill-switch? Then makes a decision.

### Success criterion

Participant **makes a deliberate decision** (accept or decline) and
articulates a reason that engages with the trade-off — sample size,
revocability, future risk — within the time budget. Either decision
is acceptable. Failure looks like clicking "accept" with no thought,
or wandering away from the panel without deciding.

### Signal collected

- Did the participant verbalize a trade-off explicitly?
- Time to decision.
- If they accepted, did they notice / ask whether the rule could be
  revoked?
- Decision (accept / decline / skipped).

---

## Task ordering

The fixed order is **T1 → T2 → T3 → T4 → T5**, increasing in
difficulty. We do not counterbalance — at n = 15 the statistical
benefit of counterbalancing is outweighed by the cost in researcher
overhead and the loss of the "first impression on T1" warm-up signal.
This is a limitation noted in §5.5.5 (threats to validity).

---

## What can be lifted directly into §5.5.1 of the paper

The "Setup", "Task statement", "Success criterion", and "Signal
collected" subsections of each task are deliberately written in a
form that can be lifted verbatim — minus the researcher's notes — into
the paper's method section. The total task copy is ~600 words,
appropriate for a single subsection.
