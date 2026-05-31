# memorywire Threat Model

> Version: v0 (draft) Ã¢â‚¬â€ 2026-05-27
> Scope: the memorywire protocol, reference implementation in `src/memorywire/`,
> and governance UI in `ui/`.
> Out of scope: third-party backend security (mem0, Letta, Cognee,
> Postgres) Ã¢â‚¬â€ those have their own threat models.

This document enumerates the adversaries we considered when shaping the
v0 protocol, points to the lines of code that mitigate each one, and is
honest about residual risk. It is descriptive, not prescriptive Ã¢â‚¬â€ the
"v0.2 hardening" entries are roadmap, not commitments.

---

## 1. System assumptions and trust boundaries

```
agent process (trusted)
  Ã¢â€â€Ã¢â€â‚¬ in-process Ã¢â€ â€™ memorywire SDK (Memory facade)
        Ã¢â€â€Ã¢â€â‚¬ in-process Ã¢â€ â€™ router (src/memorywire/router.py)
              Ã¢â€â€Ã¢â€â‚¬ per-adapter (may cross network) Ã¢â€ â€™ sqlite-vec | mem0 |
                                                   Letta | Cognee | pgvector
                                                          Ã¢â€â€š
                            shared SQLite file Ã¢â€”â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€Ëœ
                                    Ã¢â€â€š
                                    Ã¢â€“Â¼
                           governance UI (ui/, separate process)
                             - BearerAuthMiddleware (opt-in MEMORYWIRE_UI_TOKEN)
                             - CSRFMiddleware (double-submit, HMAC-SHA256)
```

Trust assumptions:

- **Agent process: trusted.** Whatever calls `Memory.remember()` is
  authoritative for its own `agent_id`. Spec delegates caller auth to
  the host application (`docs/spec/v0.md Ã‚Â§1`).
- **Router: in-process.** No network between SDK and router; the
  network boundary, if any, lives in individual adapters.
- **Backends: partially trusted.** Per-store failures cannot crash the
  router (`return_exceptions=True` fan-out at `src/memorywire/router.py:261-264,
  353-356`), but a malicious backend *can* influence fused recall (Ã‚Â§2.3).
- **Governance UI: separate trust zone** with opt-in bearer auth +
  CSRF. Without `MEMORYWIRE_UI_TOKEN` it is unauthenticated Ã¢â‚¬â€ fine for a
  single operator on localhost, not for a public bind.
- **Audit log: append-only by convention.** Schema in
  `docs/kickoff/ARCHITECTURE.md Ã‚Â§3`; sole writer is
  `SqliteVecStore._audit` (`src/memorywire/store/sqlite_vec.py:401-424`).

In v0 only the UI surface is authenticated (opt-in bearer + CSRF,
commit `c828d76`). Per-`agent_id` SDK calls, inter-store integrity, and
audit-row provenance are not.

---

## 2. Adversaries enumerated

The six adversaries below are the v0 paper-mandatory set. They map onto
established categories: OWASP A01 (Broken Access Control), A03 (Injection),
A04 (Insecure Design), A07 (Identification & Authentication Failures), and
A09 (Logging & Monitoring Failures); CWEs are noted inline.

### 2.1 Malicious memory injection

**Capability:** submits `remember()` calls Ã¢â‚¬â€ as the agent itself
(prompt-injected upstream) or as an upstream system feeding the agent.
**Motivation:** plant adversarial "facts" that subsequent `recall()`
surfaces Ã¢â‚¬â€ the memory analogue of prompt injection (OWASP LLM-01,
CWE-20). **Preconditions:** can influence any string the agent passes
through `remember()`. memorywire cannot tell a real fact from a planted one.

### 2.2 Recall exfiltration

**Capability:** issues `recall()` against an agent's router Ã¢â‚¬â€ directly
(compromised SDK caller) or indirectly (manipulating the prompt that
drives the agent's own recall calls). **Motivation:** read private
memories stored under `agent_id` / `user_id` (CWE-200, OWASP A01).
**Preconditions:** can issue `recall(query, agent_id)` for an agent
with data. `k` defaults to 5; the schema caps at 1000 (`docs/spec/v0.md Ã‚Â§3.2`).

### 2.3 Poisoned backend in RRF fusion

**Capability:** controls one of the N child stores in a `MemoryRouter`
Ã¢â‚¬â€ a compromised hosted mem0 instance, a malicious adapter fork, or a
MITM on the backend HTTP. **Motivation:** dominate the fused output of
`recall()` so the agent receives attacker-chosen results (CWE-345).
**Preconditions:** can return crafted `RecallHit` rows with high `score`
or fabricated `id`s not seen in other stores.

### 2.4 Audit log tampering

**Capability:** has write access to the SQLite file or can run arbitrary
SQL against `audit_log`. **Motivation:** hide a previous `forget()` /
`merge()` / `approve()` or fabricate one to frame an operator
(CWE-117 / CWE-778, OWASP A09). **Preconditions:** filesystem access to
the memorywire DB.

### 2.5 Cross-tenant leakage / IDOR

**Capability:** legitimate operator scoped to `agent_id = A` with a
valid UI session who guesses or harvests memory ids belonging to
`agent_id = B`. **Motivation:** approve, reject, forget, or merge
another agent's memories (CWE-639, OWASP A01). **Preconditions:** UI
session as agent A plus a memory id known to belong to agent B (ids
are 32-hex uuid4 but leak via logs, audit exports, or prior shared
sessions).

### 2.6 Approval bypass

**Capability:** writes memory with `approval_required=true` and either
(a) bypasses HITL by reaching the UI on an unauthenticated bind, or
(b) crafts the procedural-memory payload so the FSM definition itself
triggers code execution. **Motivation:** smuggle a policy-violating
memory past governance, or escape the FSM sandbox into the host process
(CWE-94, CWE-862, OWASP A04). **Preconditions:** for (a) governance UI
reachable without bearer token; for (b) ability to submit `Procedure`
JSON with `before` / `after` / `prepare` callback strings.

---

## 3. Per-threat: mitigation, residual risk, v0.2 hardening

### 3.1 Malicious memory injection

**Current mitigation:** `approval_required=true` on `RememberRequest`
(`docs/spec/v0.md Ã‚Â§3.1`) stages the row behind the
`PENDING_APPROVAL_DELETED_AT = -1` sentinel in `memories.deleted_at`
(`src/memorywire/store/sqlite_vec.py:88-98, 440`, commit `c828d76`). All recall
paths filter on `deleted_at IS NULL`, so pending rows cannot influence
retrieval until a human approves in the UI. `confidence` is a first-class
spec field; every `remember()` is journaled with the inserted `memory_id`
(`src/memorywire/store/sqlite_vec.py:505-512`), so a poisoned memory is traceable
to the call that planted it.

**Residual risk:** default `approval_required` is false; memorywire cannot tell
a real fact from a planted one Ã¢â‚¬â€ it only guarantees that what the agent
wrote is what the agent reads back. Prompt-injected calls from a trusted
agent are out of scope (Ã‚Â§5).

**v0.2 hardening:** a `privacy_intent` block on `RememberRequest`
(`docs/spec/v0.md Ã‚Â§10`) so operators can require approval by `source`,
`type`, or content predicate without instrumenting every caller.

### 3.2 Recall exfiltration

**Current mitigation:** recall is hard-bound to `agent_id` at the
adapter SQL layer Ã¢â‚¬â€ every recall path in `SqliteVecStore` filters
`WHERE agent_id = ? AND deleted_at IS NULL`, and `agent_id` is required
by the spec (`docs/spec/v0.md Ã‚Â§3.2`). `recall()` is itself audited
(`audit_log.operation = 'recall'`), so high-rate exfiltration is
observable post-hoc. The schema caps `k` at 1000 so a single call cannot
drain a store. Governance approval is **not** wired for `recall` in v0
Ã¢â‚¬â€ the governance channel covers `remember` / `forget` / `merge` only
(`docs/spec/v0.md Ã‚Â§6`).

**Residual risk:** a caller with the right `agent_id` can extract
everything that agent stored. No recall rate limit, no field-level
redaction, no approval on reads. An attacker iterating queries can
reconstruct most of the memory.

**v0.2 hardening:** per-`agent_id` recall budgets, optional
`approval_required` on `recall`, and a `redact` filter for secrets-
labelled rows.

### 3.3 Poisoned backend in RRF fusion

**Current mitigation:** RRF is **score-independent** by construction Ã¢â‚¬â€
`_fusion_contribution` uses `1 / (rrf_k + rank)` (`src/memorywire/router.py:428-429`),
so a malicious backend cannot dominate by inflating `score`; it can only
return an item at rank 0. RRF sums across stores, so a single rogue store
contributes at most `1/60 Ã¢â€°Ë† 0.0167` per item, while a two-store consensus
item scores `Ã¢â€°Â¥ 1/60 + 1/61 Ã¢â€°Ë† 0.0330`. `MAX` and `WEIGHTED` fusion *are*
score-sensitive Ã¢â‚¬â€ operators picking them accept more backend trust
(documented at `src/memorywire/router.py:415-444`). Per-store failures are logged
but do not abort the operation (`src/memorywire/router.py:361-368`).

**Residual risk:** with `fusion="max"` or `"weighted"`, one malicious
backend can dominate. Even with RRF, a backend that fabricates an
attacker-controlled `id` that *also* exists in other stores can bump it
by reporting it at rank 0. There is no cross-store identity proof Ã¢â‚¬â€
`RecallHit.id` is taken at face value.

**v0.2 hardening:** signed `RecallHit` envelopes per backend; an optional
`quorum_k` parameter requiring an item to appear in `k` distinct stores
before fusion considers it.

**Measured.** `scripts/run_adversarial.py` (driven by the harness in
`tests/benchmarks/test_adversarial.py`) sweeps a 1-of-N rogue-backend
attack against a real `MemoryRouter` and records recall@5 / leak rate /
gold-displacement rate at attacker budgets K=0,5,...,M. Headline,
measured 2026-05-27 at N=3, 1 adversarial, M=50 corpus, Q=20 queries,
seed=1337:

| K | recall@5 (RRF) | leak (RRF) | recall@5 (MAX) | leak (MAX) |
|---:|---:|---:|---:|---:|
| 0  | 1.000 | 0.000 | 1.000 | 0.000 |
| 5  | 1.000 | 0.000 | 0.500 | 0.800 |
| 50 | 1.000 | 0.000 | 0.500 | 0.800 |

The RRF curve stays flat at the no-attack baseline across the entire
sweep Ã¢â‚¬â€ the consensus of two benign rank-0 votes (`1/60 + 1/61 Ã¢â€°Ë†
0.0330`) provably dominates the single rogue rank-0 vote (`1/60 Ã¢â€°Ë†
0.0167`). `fusion="max"` collapses immediately at K=5: the attacker
ties or beats the benign rank-0 score, pulls 4 of 5 fused top-5 slots,
and halves recall. See `docs/benchmarks.md`'s "Adversarial fusion
experiment" section for the full methodology, caveats, and
machine-readable output (`docs/adversarial-results.{rrf,max,weighted}.json`).

### 3.4 Audit log tampering

**Current mitigation:** the audit log is append-only by code convention.
`SqliteVecStore._audit` is the only writer in the OSS adapter
(`src/memorywire/store/sqlite_vec.py:401-424`); it only performs `INSERT INTO
audit_log(...)`. No UPDATE or DELETE against `audit_log` exists anywhere
in `src/memorywire/` or `ui/src/amp_ui/`. Every governance action emits a
dedicated audit row with the reviewer's identity Ã¢â‚¬â€ `approve()`,
`reject()`, `apply_co_memorize()`, and `accept_pattern()` all hit
`audit_log` (`ui/src/amp_ui/services.py:512-529, 560-577, 913-930,
994-1017, 1194-1216`). Each row carries the full request payload and
response as JSON, so a `forget` that bypasses the audit path leaves a
structurally detectable gap.

**Residual risk:** SQLite is a single file with filesystem semantics Ã¢â‚¬â€
anyone with write access can `DELETE FROM audit_log` or mutate rows. memorywire
enforces append-only at the code layer, not the DB layer. No hash chain,
no external timestamping, no row signatures.

**v0.2 hardening:** Merkle-chained audit rows (`audit_log.prev_hash`
column) so tampering breaks the chain; periodic export to an
append-only object store (S3 object-lock); a read-only DB role for the
UI connection.

### 3.5 Cross-tenant leakage / IDOR

**Current mitigation:** this is the issue the security review caught
and commit `c828d76` fixed. Every state-changing UI handler is now scoped
to `(agent_id, memory_id, sentinel)`:

- `approve()` Ã¢â‚¬â€ `UPDATE memories SET deleted_at = NULL WHERE id = ? AND
  agent_id = ? AND deleted_at = ?` (`ui/src/amp_ui/services.py:502-511`).
- `reject()` Ã¢â‚¬â€ same triple-key guard (`ui/src/amp_ui/services.py:551-559`).
- `apply_co_memorize()` Ã¢â‚¬â€ both the forget branch
  (`ui/src/amp_ui/services.py:896-912`) and the merge branch
  (`ui/src/amp_ui/services.py:958-993`) require the row to belong to the
  requesting agent. The merge branch additionally verifies the canonical
  (primary) row belongs to the agent *before* touching the secondary
  (`ui/src/amp_ui/services.py:958-973`), closing the "cross-agent merge
  leaks the relationship via the audit log" sub-case.
- On any mismatch (row missing, wrong agent, already forgotten),
  `rowcount == 0` raises `NotPendingError` or returns `ApplyOpResult` with
  `skipped=True` and an *identical* opaque reason for "wrong agent" vs
  "already forgotten by a concurrent process" Ã¢â‚¬â€ the response itself does
  not leak which condition fired (`ui/src/amp_ui/services.py:902-911`).

The pending sentinel is a shared public constant
(`PENDING_APPROVAL_DELETED_AT`, `src/memorywire/store/sqlite_vec.py:91`) which
the UI imports (`ui/src/amp_ui/services.py:36, 46`); a future schema
bump cannot desync.

**Residual risk:** the UI uses a single global bearer token. There is
no per-operator role or per-`agent_id` ACL Ã¢â‚¬â€ a user with the bearer can
operate on any `agent_id` they pass in the route. The IDOR fix prevents
*cross-agent pivoting by id*, not *multi-tenant isolation by operator*.
`approved_by` records whatever the UI passes in
(`ui/src/amp_ui/services.py:487`).

**v0.2 hardening:** per-session multi-tenant `agent_id` scoping (logged
as a spec-gap in `c828d76`'s message); SSO-shaped reviewer identity;
per-operator allowed-`agent_id` ACL.

### 3.6 Approval bypass

**Current mitigation (a) UI no-auth:** `BearerAuthMiddleware` gates
every request behind a bearer token when `MEMORYWIRE_UI_TOKEN` is set
(`ui/src/amp_ui/middleware.py:74-103`), accepting either an
`Authorization: Bearer` header or an `memorywire_ui_session` cookie, with
`hmac.compare_digest` for constant-time comparison
(`ui/src/amp_ui/middleware.py:112, 116`). `CSRFMiddleware` enforces a
double-submit-cookie pattern signed with HMAC-SHA256 over `nonce.ts`
with 24-hour TTL (`ui/src/amp_ui/middleware.py:124-219`); cookies are
`HttpOnly; SameSite=Lax`. Binding a non-loopback host without a token
fires a stderr warning on boot (`ui/src/amp_ui/middleware.py:55-66`).
All landed in commit `c828d76`.

**Current mitigation (b) procedural-memory RCE:**
`validate_procedure_dict` allow-lists transition keys to exactly
`{trigger, source, dest, conditions, unless}`
(`src/memorywire/procedural.py:57-59`), explicitly rejecting `before`, `after`,
and `prepare` Ã¢â‚¬â€ the three pytransitions keys that resolve dotted-string
callbacks via `__import__` and would otherwise let
`{"before": "os.system"}` execute arbitrary code at trigger time
(`src/memorywire/procedural.py:44-56`). `conditions` and `unless` strings are
restricted to bare identifiers (no `.`) so they resolve only to
attributes on our private `_ProcedureModel`, never to imported modules
(`src/memorywire/procedural.py:122-136`). `ProcedureRunner._expand_transitions`
strips disallowed keys *at construction time* even if a caller bypasses
`from_dict` (`src/memorywire/procedural.py:283-312`). Both layers shipped in
`c828d76`.

**Residual risk:** the bearer is a single shared secret with manual
rotation. CSRF is bypassed for any `Authorization: Bearer` request
(`ui/src/amp_ui/middleware.py:151`) Ã¢â‚¬â€ a documented v0 trade-off: a
stolen bearer is already a fatal compromise. The procedural sandbox is
purely static allow-listing; if a future `transitions` release adds a
new code-execution sink under a key we currently allow, validation will
silently miss it.

**v0.2 hardening:** `MEMORYWIRE_UI_CSRF_SECRET` pinning (spec-gap in `c828d76`);
per-operator tokens with rotation; Secure cookie flag for HTTPS; a CI
snapshot of the `transitions` callback-key surface so a library upgrade
that adds a new sink fails the test rather than the sandbox.

---

## 4. Not mitigated in v0

Real threats memorywire v0 does **not** address, by design:

- **Insider attacks on the audit DB** Ã¢â‚¬â€ anyone with filesystem write
  access can rewrite history (see Ã‚Â§3.4 residual). Mitigated only by
  deployment hygiene.
- **Side-channel timing attacks on recall** Ã¢â‚¬â€ latency varies with `k`,
  fusion mode, and per-store result counts; a patient attacker can in
  principle distinguish "agent has memory matching X" from "no match"
  by observing latency.
- **Prompt injection in the calling agent** Ã¢â‚¬â€ memorywire is downstream of the
  LLM. If the agent is fooled into `remember("Alice is in the
  building", confidence=1.0)`, memorywire faithfully stores and recalls it
  (see Ã‚Â§5).
- **Supply-chain attacks on the wheel** Ã¢â‚¬â€ PyPI publishing uses OIDC
  trusted publishing per `docs/kickoff/ARCHITECTURE.md Ã‚Â§1` but there
  is no in-band signature verification at SDK load. Mitigated by
  `pip`'s standard hash-pinning.
- **Backend transport security** Ã¢â‚¬â€ `mem0` / `Letta` / `pgvector`
  adapters delegate TLS and auth to their upstream SDKs. memorywire does not
  enforce HTTPS at the router boundary.

---

## 5. Threats the protocol cannot mitigate

Threats inherent to the agent / LLM, not to memorywire. memorywire makes them
**auditable**, not preventable:

- An LLM hallucinates a `forget()` and deletes a real memory. The audit
  row captures the call exactly; recovery means inspecting
  `audit_log.payload` and restoring from backup.
- An LLM issues `recall()` with an over-broad query and leaks results
  into a user-visible response. memorywire returned the hits correctly; the
  agent leaked them.
- An LLM stores content it should not (e.g. a card number) via
  `remember()`. memorywire's `metadata` is opaque; there is no PII detector.
- An LLM picks the wrong `MemoryType`. memorywire enforces type at write time
  but cannot infer the *correct* type from `content`.

For all of these, the audit log gives the operator a complete post-hoc
record of which call was made, by whom, when, and with what arguments.
That is the v0 floor.

---

## 6. Versioning

This threat model is versioned alongside the spec. Each spec minor
(`v0.1`, `v0.2`, ...) either confirms this document still applies or
appends a delta section listing new and retired threats. New threats
discovered between minors are added to the next minor's delta, not
retroactively to v0. The `Not mitigated in v0` section may shrink as
features land Ã¢â‚¬â€ once audit-row hashing ships (v0.2 hardening Ã‚Â§3.4),
that bullet moves into Ã‚Â§3.4's "Current mitigation".

---

## 7. Reporting

Suspected vulnerabilities should be reported privately Ã¢â‚¬â€ see
[`SECURITY.md`](../SECURITY.md) at the repo root. Use the GitHub
Security tab's "Report a vulnerability" feature on the
[memorywire repository](https://github.com/mthamil107/memorywire).
We aim to acknowledge within 72 hours and provide an initial assessment
within seven days, per `SECURITY.md`.

---

## 8. References

Internal:

- The security-review agent run that surfaced the five issues fixed in
  commit `c828d76` ("fix: 5 critical findings from code-review +
  security-review"). The five were: (1) `expire()` with empty policy
  mass-deletes (correctness); (2) UI IDOR on approve / reject /
  co-memorize across `agent_id` (security, Ã‚Â§3.5); (3) UI lacks auth +
  CSRF (security, Ã‚Â§3.6a); (4) pytransitions RCE via crafted procedural
  memory before/after keys (security, Ã‚Â§3.6b); (5) UI 500 on fresh DB
  (correctness).
- [`SECURITY.md`](../SECURITY.md) Ã¢â‚¬â€ reporting policy.
- [`docs/spec/v0.md`](./spec/v0.md) Ã¢â‚¬â€ protocol surface (Ã‚Â§Ã‚Â§3, 6, 7
  cited throughout this document).
- [`docs/kickoff/ARCHITECTURE.md`](./kickoff/ARCHITECTURE.md) Ã¢â‚¬â€ storage
  schema (Ã‚Â§3) and audit-log shape.

External standards we map to:

- [OWASP Top 10 (2021)](https://owasp.org/Top10/): A01 (Broken Access
  Control, Ã‚Â§3.5), A03 (Injection, Ã‚Â§3.6b), A04 (Insecure Design, Ã‚Â§3.6),
  A07 (Auth Failures, Ã‚Â§3.6a), A09 (Logging Failures, Ã‚Â§3.4).
- [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/):
  LLM-01 (Prompt Injection, Ã‚Â§3.1 and Ã‚Â§5), LLM-03 (Training/Data
  Poisoning analogue, Ã‚Â§3.1).
- CWE references: CWE-20 (Ã‚Â§3.1), CWE-94 (Ã‚Â§3.6b), CWE-117 / CWE-778
  (Ã‚Â§3.4), CWE-200 (Ã‚Â§3.2), CWE-345 (Ã‚Â§3.3), CWE-639 (Ã‚Â§3.5), CWE-862
  (Ã‚Â§3.6a).
- MITRE ATT&CK mapping (informal): T1565.001 "Stored Data Manipulation"
  (Ã‚Â§3.4), T1078 "Valid Accounts" (Ã‚Â§3.5), T1059 "Command and Scripting
  Interpreter" (Ã‚Â§3.6b).
