# Governance UI

> **WIP** Ã¢â‚¬â€ ships in Phase 6 as the `ui/` sub-package.

The governance UI implements the diff-and-approve workflow described in
[`spec/v0.md`](spec/v0.md) Ã‚Â§6. It is a Starlette + HTMX + Tailwind application
running alongside an memorywire-using agent and providing:

1. **Pending Approvals** Ã¢â‚¬â€ queue of `remember()` calls awaiting human review,
   with structured diff against current memory state.
2. **Memory Health Dashboard** Ã¢â‚¬â€ staleness, drift, contradictions surfaced,
   coverage by memory type.
3. **Audit Log** Ã¢â‚¬â€ every `remember`/`recall`/`forget`/`merge`/`expire`
   operation, filterable, exportable as JSON or CSV.
4. **Co-memorize Bulk Review** Ã¢â‚¬â€ periodic batch view of forget/merge candidates
   with model-generated reasoning.
5. **Approval Patterns** Ã¢â‚¬â€ learned approve/reject rules with "auto-allow?"
   recommendations after N consistent decisions.

The protocol and reference implementation in `src/memorywire/` are Apache-2.0. The UI
in `ui/` is source-available under a Functional Source License (FSL) Ã¢â‚¬â€ see
`ui/LICENSE` once published.
