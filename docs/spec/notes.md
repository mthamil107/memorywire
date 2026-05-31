# memwire v0 Ã¢â‚¬â€ Schema authoring notes

This file records the judgment calls made while transcribing
`docs/kickoff/memwire-SPEC-v0.md` into JSON Schema files under
`src/memwire/schemas/`. It is intended for the spec maintainers; it is not
itself normative.

## Conventions

- All schemas declare Draft 2020-12 via `$schema`.
- `$id` follows the pattern `https://memwire.dev/schemas/v0/<directory>/<name>`
  where `<directory>` is `operations` or `types`, e.g.
  `https://memwire.dev/schemas/v0/operations/remember` or
  `https://memwire.dev/schemas/v0/types/episodic`. Response schemas use the
  same convention with a `.response` suffix in the trailing path segment
  (e.g. `operations/remember.response`).
- Field names are transcribed verbatim from the spec doc. Where the spec
  enumerates a field by name only (e.g. `created_at`, `expires_at`) we
  type it as `integer` (Unix epoch ms) to match the explicit ms-based
  fields in section 3.1 (`expires_at`) and the response example in
  section 3.1 (`stored_at: 1716700000000`).

## Request schemas (operations)

Direct verbatim transcriptions from spec sections 3.1Ã¢â‚¬â€œ3.5. No semantic
changes. Only additions are the meta keys (`$schema`, `$id`, `title`,
`description`) required by the deliverable contract; field shapes and
defaults match the spec exactly.

## Memory-type schemas (types)

The spec doc does not pin down the on-disk shape of a memory record;
section 2 only lists the type tag. The deliverable requires record
schemas that include the common fields `id`, `agent_id`, `user_id`,
`type`, `content`, `metadata`, `confidence`, `source`, `created_at`,
`updated_at`, `expires_at`, plus type-specific fields.

- **Common fields.** `id`, `agent_id`, `type`, `content`, `created_at`
  are `required`. The other common fields are optional because the spec
  treats `user_id`, `metadata`, `source`, `confidence`, `expires_at` as
  optional on the request side (section 3.1) and updates may not have
  occurred yet for `updated_at`. `additionalProperties: true` keeps
  records forward-compatible with future fields (consistent with section
  9 evolution policy "new optional fields: allowed at any time").
- **`type` discrimination.** Each type schema fixes `type` to a `const`
  matching the file (`semantic`, `episodic`, `procedural`, `emotional`)
  so a single record can be validated against the right type schema.
- **`semantic`.** No extra fields beyond the common set; the spec
  example is a plain string fact.
- **`episodic` (event-time / location).** Added `event_time` (epoch ms
  when the event actually happened Ã¢â‚¬â€ distinct from `created_at`, which
  is when the record was written), `location` (free-form string), and
  `participants` (array of identifiers). All optional. These names are
  not pinned in the spec doc; flagged below as a follow-up.
- **`procedural` (FSM).** `content` is constrained to the section-7 FSM
  shape with required `name`, `initial`, `states`, `transitions`,
  `current`. `transitions[]` items require `trigger`, `source`, `dest`
  with `additionalProperties: true` so backends can carry pytransitions
  extras (`before`, `after`, `conditions`, `unless`, Ã¢â‚¬Â¦).
- **`emotional` (sentiment/affect).** Added `sentiment`
  (`positive`/`negative`/`neutral`/`mixed`), `valence` (-1..1),
  `arousal` (0..1), `emotion` (free-form discrete label), and `target`.
  These names are not pinned in the spec doc; flagged below.

## Response schemas

### `remember` response
Verbatim from the example object in section 3.1. `id`, `stored_at`,
`stores`, `pending_approval` made required; `approval_url` is nullable
because the example shows `null` when no approval is pending.
`additionalProperties: false` Ã¢â‚¬â€ the spec example is a closed shape.

### `recall` response
Verbatim from the example object in section 3.2. Required:
`results`, `fusion_used`, `stores_queried`, `latency_ms`. Each result
requires `id`, `type`, `content`, `score`. `content` is typed
`["string", "object"]` because procedural memories use an FSM object as
content; the rest are strings. `additionalProperties: true` on each hit
to keep room for backend-specific diagnostics.

### `forget` response (inferred)
The spec doc does **not** define a response shape for `forget`. The
section-3.3 text says "Soft delete marks `deleted_at` but retains the
record Ã¢â‚¬Â¦ the audit log keeps the operation either way." Section 5 says
forget "fans out to all stores; aggregates per-store responses." From
that I inferred a response with:

- `forgotten_ids`: array of ids actually forgotten (callers may pass
  a `filter` instead of explicit `ids`, so they need to know what was
  matched).
- `stores`: per-store breakdown `{store, count, error?}` to match the
  "aggregates per-store responses" wording.
- `hard_delete`: echo of the request flag so the caller can confirm.
- `pending_approval` / `approval_url`: optional governance fields,
  parallel to `remember.response`, since section 6 lists `forget` as a
  governance-eligible operation.

### `merge` / `expire` responses Ã¢â‚¬â€ deliberately omitted
The deliverable lists response schemas only for `remember`, `recall`,
`forget`. The spec doc does not provide example response shapes for
`merge` or `expire`, so we leave those unspecified at v0 rather than
guess. Adapters returning per-store result aggregates will conform once
v0.x adds them.

## Spec ambiguities / bugs noticed in `docs/kickoff/memwire-SPEC-v0.md`

These were not modified (the kickoff doc is read-only for this phase);
flagging only.

1. **Operation request schemas in sections 3.2Ã¢â‚¬â€œ3.5 omit `$schema`.**
   Only section 3.1's `remember` request schema declares
   `"$schema": "https://json-schema.org/draft/2020-12/schema"`. The other
   four operation request blocks declare `$id` but no `$schema`. The
   prose says "Schemas use JSON Schema Draft 2020-12" so the intent is
   clear, but the inline blocks are inconsistent. (Our authored files
   all declare `$schema`.)
2. **Section 5 typo: "RRF" formula uses ÃŽÂ£ but unbalanced parens are
   fine; however the prose says "k=60" and then writes `60 + rank_i`
   instead of `k + rank_i`.** Minor Ã¢â‚¬â€ the constant equals k Ã¢â‚¬â€ but the
   variable name would aid reading.
3. **Governance schema in section 6 references the request via
   `"$ref": "https://memwire.dev/schemas/v0/remember"`** but the operation
   field is an enum including `forget` and `merge`. The `$ref` should
   probably be conditional on `operation` (oneOf / if-then-else) rather
   than hard-coded to `remember`.
4. **Section 9 evolution policy** says new memory types are a "minor
   version bump", but the `type` enum is hard-coded in multiple schemas
   (`remember`, `recall.types`, `expire.policy.type`). Adding a fifth
   type would require editing each schema; a shared `$defs.MemoryType`
   referenced by all five would be tidier. Not a bug, just maintenance
   surface area.
5. **Section 7 procedural example** uses `"source": "*"` as a wildcard
   in one transition. pytransitions accepts this, but it's not called
   out in prose Ã¢â‚¬â€ adapters that re-validate transitions against the
   `states` list need to special-case it. Our procedural schema accepts
   any non-empty string for `source` so this is permitted, but the spec
   should mention the wildcard convention.
6. **Section 3.1 response example** is shown as a bare JSON object (no
   surrounding JSON Schema), unlike requests which are presented as
   schemas. Sections 3.3Ã¢â‚¬â€œ3.5 give no response example at all. This is
   the gap that forced the inferred `forget.response.json` shape above.
