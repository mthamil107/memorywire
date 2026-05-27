# AMP and MCP — Composing, Not Competing

> Version: v0 — 2026-05-27
> Audience: prospective adopters, MCP working group, paper reviewers.
> One-line summary: AMP is what MCP would be if MCP had a memory
> primitive; we built it as a standalone spec so the design can
> stabilize without blocking on MCP-WG governance, with intent to
> propose adoption as an MCP extension at v0.5.

---

## 1. The question every reader asks first

> "Why didn't you just add memory operations to MCP?"

Because memory is not a tool, not a resource, and not a prompt — it is
a distinct primitive with its own lifecycle (write, recall, forget,
merge, expire), its own taxonomy (semantic, episodic, procedural,
emotional), and its own governance surface (diff-and-approve, audit).
You can *wrap* memory inside MCP's existing primitives, and we show
how below — but the wrapping leaks. The five operations end up
flattened into one opaque tool; the four memory types end up encoded
as a string field; the governance channel ends up living outside the
protocol entirely. AMP exists to give memory the same first-class
treatment MCP gave tool-use, and to keep iterating on that design at
the speed an unblocked draft allows. We expect to propose AMP as an
MCP extension once the wire format has stabilized; until then,
standalone is the path that lets the design be honest about what
memory actually needs.

---

## 2. What MCP does today

The Model Context Protocol (https://modelcontextprotocol.io) is a
JSON-RPC protocol — running over stdio or HTTP — that standardizes
how an agent runtime exchanges *context* with a server process. As of
2026-05-27 its public surface is five primitives:

- **Tools** — server-exposed functions an agent can call. Each tool
  has a JSON-Schema input shape and a free-form output.
- **Resources** — server-exposed read-only documents (text or
  binary) the agent can list and fetch by URI.
- **Prompts** — parameterized prompt templates the server offers to
  the client.
- **Sampling** — a reverse-direction primitive: the server asks the
  client to invoke its model on a payload.
- **Roots / elicitation** — scoping the filesystem (roots) the
  server is allowed to see, and structured user-input requests
  (elicitation) that pause a tool call to ask the human a question.

MCP has been adopted broadly through 2025-2026 — Anthropic shipped
it, OpenAI added MCP-compatible clients, Google's Gemini ecosystem
integrated it, Cloudflare ships MCP gateways, and the list keeps
growing. It is the de-facto cross-vendor wire format for *tool-use*
and *context attachment*.

What MCP does **not** define, as of this writing, is a memory
primitive. There is no `remember` verb, no `recall` verb, no built-in
notion of memory types, no governance channel for memory writes, no
audit primitive. MCP can absolutely *wrap* a memory backend — you
expose `remember` / `recall` / `forget` as three tools and you are
done in fifteen minutes — but that wrapping puts memory on the same
footing as "send a Slack message" or "list a directory." The protocol
itself remains memory-blind. AMP is the layer that names memory as
its own thing.

---

## 3. The overlap table

| Concern | MCP today | AMP v0 |
|---|---|---|
| Wire format | JSON-RPC over stdio/HTTP | JSON Schema 2020-12 (REST-friendly) |
| Tool / resource discovery | yes (first-class) | not the focus |
| Memory operations (remember / recall / forget / merge / expire) | not native (wrap as tool) | first-class |
| Memory type taxonomy (semantic / episodic / procedural / emotional) | none | first-class |
| Cross-backend fusion (router) | none | first-class (RRF k=60) |
| HITL governance for memory writes | none | first-class (diff-and-approve UI) |
| Audit-log primitive | none | first-class |
| Procedural-memory FSM format | none | first-class (`pytransitions`-compatible JSON) |
| TTL / expiry semantics | none | first-class (`expire` op with policy DSL) |
| Per-record confidence + provenance | up to tool author | first-class fields on every record |
| Standards body | Anthropic + community | not yet (intent: MCP-WG -> IETF -> W3C) |
| Versioning posture | stable, in production | draft, breaking changes allowed through v0.5 |

Where the rows show "first-class" on the AMP side and "none" on the
MCP side, that is the gap AMP fills. Where the rows show "yes" on
the MCP side and "not the focus" on the AMP side, AMP defers — we
have no intention of reinventing tool discovery, sampling, or
resource listing. The two protocols address adjacent concerns, and
the right composition story (next section) treats them as
complementary layers in the same agent stack rather than rivals.

---

## 4. Three composition modes

### 4.1 AMP-as-MCP-tool (works today)

The simplest composition. Wrap an AMP `Memory` facade as an MCP
server that exposes five tools — one per operation — and route the
JSON-Schema-validated payload straight into the AMP request models:

```python
# ~10-line sketch; production code lives in examples/mcp_adapter.py
from mcp.server import Server
from amp import Memory, MemoryType

mem = Memory(agent_id="bot", stores=["sqlite-vec://./mem.db", "mem0://default"])
server = Server("amp-memory")

@server.tool("amp.remember")
async def remember(content: str, type: str, user_id: str | None = None):
    return await mem.remember(content, type=MemoryType(type), user_id=user_id)

@server.tool("amp.recall")
async def recall(query: str, k: int = 5, types: list[str] | None = None):
    return await mem.recall(query, k=k, types=types)

# forget / merge / expire follow the same pattern
```

Pros: zero new infrastructure; any MCP-aware agent can use AMP
through its existing client. Cons: the five operations show up as
five generic tools, the type taxonomy is just a string parameter,
the governance channel sits outside MCP entirely and the agent has
to be taught about it separately.

### 4.2 AMP-as-MCP-resource (works today)

For agents that prefer to *read* memory rather than call it, expose
`recall()` results as MCP resources. The resource URI carries the
query; the resource body is the structured `RecallResponse`:

```
amp-memory://recall?agent_id=bot&query=what%20do%20I%20know%20about%20alice&k=10
```

The MCP client lists this resource (parameterized via elicitation if
needed), fetches it, and feeds the body into the model context. This
mode plays nicely with MCP clients that already treat resources as
the canonical context-attachment surface. Writes still need the tool
mode from §4.1.

### 4.3 AMP-as-MCP-extension (proposed, v0.5 timeline)

The future state. AMP becomes a published MCP extension —
`mcp.memory.v0` or similar — with the five operations and four memory
types lifted into MCP's own type system. JSON-Schema definitions get
re-expressed as JSON-RPC method signatures; the governance channel
becomes an MCP sub-protocol; clients that support the extension know
how to surface memory operations distinctly in their UI (versus
treating them as opaque tools). This is the path we expect to propose
once the wire format has settled — see §6.

---

## 5. Why the standalone-spec-first approach

Three reasons, in priority order.

**Iteration speed.** A v0 draft of a wire format goes through
breaking changes. The AMP spec explicitly reserves the right to
break things until v0.5 (see [`docs/spec/v0.md`](spec/v0.md) §9 —
"Breaking changes allowed until v0.5"). Pushing those changes
through a working-group governance cycle before the design has
stabilized would slow the iteration the design needs right now.
Once v0.5 is frozen, working-group governance becomes a help rather
than a brake.

**Multi-protocol portability.** Memory matters in places MCP
doesn't reach. The web platform (W3C) is going to need an agent
memory primitive when browsers ship on-device models capable of
multi-session reasoning. Cross-language ports (Rust, Go,
TypeScript) want a JSON-Schema spec they can codegen against, not a
JSON-RPC method signature tied to one transport. The IETF
Internet-Draft route — by analogy to Cloudflare's Web Bot Auth —
needs a spec document that stands on its own. Designing AMP as a
standalone wire format keeps all three doors open. Folding it into
MCP first would close two of them.

**Layered protocols.** The recent precedent that worked best is
Cloudflare's Web Bot Auth: ship the spec early as a standalone, get
real implementations, *then* propose adoption upstream. Trying to
land a new primitive directly inside a popular existing protocol
typically gets you slow consensus or polite deferral. Trying to ship
something useful in parallel and then propose adoption once the
field has tested the design gets you a much shorter path.

---

## 6. Roadmap to MCP-WG adoption

The arc, lifted from
[`docs/kickoff/FUTURE.md`](kickoff/FUTURE.md):

- **v0.2 (Aug 2026)** — File an MCP RFC proposing memory extensions;
  cite AMP as a candidate reference implementation. Begin
  conversations with the working group on what shape an MCP-native
  memory primitive should take.
- **v0.5 (Q3 2026)** — Submit a memory-extension proposal to the
  MCP-WG with the spec frozen against breaking changes. In parallel,
  submit AMP v0.5 as an IETF Internet-Draft
  (`draft-<name>-agent-memory-protocol-00`).
- **v1.0 (Q1 2027)** — Either accepted as an MCP extension and
  shipped under MCP's namespace, or stabilized as a parallel
  standard that bridges into MCP through the composition modes in
  §4. Either outcome is acceptable.

Mechanical alignment work happening behind the scenes from now until
v0.5: keep AMP's JSON-Schema 2020-12 definitions translatable to
MCP's JSON-RPC type system; keep operation names and field shapes
identifier-clean; avoid AMP-specific transport assumptions in the
schemas themselves. The goal is to make the eventual MCP extension a
formatting transformation, not a redesign.

We make no claims about how the MCP working group will receive the
proposal — that is their call to make. The plan above describes our
own intent to engage. Final shape of any MCP-native memory primitive
will be whatever the working group decides; AMP's role is to bring
the design work, reference implementation, benchmark data, and
governance-channel pattern to that conversation.

---

## 7. Why this isn't a fork

AMP is not an alternative to MCP. The two protocols address adjacent
problems — tool-use (MCP) and memory (AMP) — and the agents we
build use both at the same time. A realistic agent loop looks like
this:

```python
# Tool-use over MCP, memory over AMP, in one agent loop
async def step(user_message: str):
    # Recall relevant memory via AMP
    context = await mem.recall(user_message, k=5, hops=1)

    # Run the model with the recalled context
    response = await model.complete(
        system=render_system_prompt(context),
        messages=[{"role": "user", "content": user_message}],
        tools=mcp_client.list_tools(),   # MCP tools
    )

    # If the model called a tool, dispatch via MCP
    if response.tool_calls:
        for call in response.tool_calls:
            result = await mcp_client.call_tool(call.name, call.arguments)
            # ...feed result back into the loop

    # If the model produced something worth remembering, write via AMP
    if response.should_remember:
        await mem.remember(
            response.fact,
            type=MemoryType.SEMANTIC,
            user_id=user_message.user_id,
            approval_required=is_sensitive(response.fact),  # routes to governance
        )
```

The two protocols never overlap in this code — MCP handles tool
invocation, AMP handles memory operations. Adopting AMP does not
mean dropping MCP. Adopting MCP does not preclude adopting AMP. The
acknowledgment line in the AMP README is sincere: AMP is *modelled
on* MCP's cross-vendor protocol shape, not in competition with it.

---

## 8. Open questions

Genuine unknowns we'd welcome external input on:

- **JSON-RPC vs REST shape.** AMP's schemas are written against
  JSON Schema 2020-12 with a REST-friendly request/response idiom.
  MCP is JSON-RPC. Bridging the two is mechanical but not free —
  there is real design space in how to express AMP operations as
  JSON-RPC methods while keeping JSON-Schema as the source of truth
  for validation. We do not yet have a definitive answer.
- **Core vs extension.** Should memory live in core MCP, as one of
  the primitives, or always as an extension? The argument for core:
  memory is becoming as universal as tool-use. The argument for
  extension: not every MCP server hosts memory, and forcing the
  primitive on every implementer raises the floor for trivial
  servers. We lean toward "extension first, core later if usage
  warrants" but the working group's read on this matters more than
  ours.
- **Mapping the type taxonomy.** AMP's four-type taxonomy
  (semantic / episodic / procedural / emotional) is drawn from the
  human-memory cognitive-science literature. MCP's discovery model
  has no equivalent. Should the types surface as separate resource
  schemas? As tags? As filter parameters on a unified recall verb?
  Unclear.
- **Governance plane.** The AMP governance channel (diff-and-
  approve, audit log, approval-learning loop) does not map cleanly
  onto any current MCP primitive. Elicitation is the closest but is
  designed for synchronous user-input mid-tool-call, not
  asynchronous review of pending writes. A future MCP-WG memory
  extension may need a new sub-protocol for governance — or may
  delegate it back to the application layer entirely.

---

## 9. Calls to action

**MCP working-group members.** If you are evaluating where a memory
primitive should live in MCP, the AMP spec and reference
implementation are intended as input material. Spec is at
[`docs/spec/v0.md`](spec/v0.md); reference impl is in `src/amp/`.
We are reachable through GitHub issues for protocol-level
conversations and we will file a formal RFC at v0.2 (target
August 2026). If you want to engage earlier, open an issue tagged
`mcp-wg` and we will treat it as a working-group-track conversation.

**Protocol users picking a composition mode today.**

- If you already run an MCP server and want memory now: §4.1
  (AMP-as-MCP-tool). Fifteen-minute integration, no new client
  required.
- If your agent reads from resources rather than calls tools:
  §4.2 (AMP-as-MCP-resource).
- If you can wait until v0.5 for tighter integration: track this
  doc and the MCP RFC; the extension path lands then.

**Paper reviewers positioning AMP against MCP in related work.**
AMP and MCP are non-overlapping in their primitives. The honest
positioning is "AMP is to memory what MCP is to tool-use; the two
compose in production agents." If you need a citation for that
framing, this document and [`docs/spec/v0.md`](spec/v0.md) §1
("AMP is to agent memory what MCP is to agent tool-use") are the
references.

---

## 10. References

- AMP wire-format spec v0 — [`docs/spec/v0.md`](spec/v0.md)
- AMP roadmap and standards-engagement plan —
  [`docs/kickoff/FUTURE.md`](kickoff/FUTURE.md) (see
  "Standards-body engagement strategy")
- Original AMP kickoff draft —
  [`docs/kickoff/AMP-SPEC-v0.md`](kickoff/AMP-SPEC-v0.md)
- AMP architecture, RRF semantics, FSM format —
  [`docs/kickoff/ARCHITECTURE.md`](kickoff/ARCHITECTURE.md)
- Model Context Protocol specification — https://modelcontextprotocol.io
- JSON Schema 2020-12 — https://json-schema.org/draft/2020-12/release-notes
- Cloudflare Web Bot Auth Internet-Draft precedent —
  `draft-meunier-web-bot-auth-architecture` (IETF). The
  ship-spec-then-propose-upstream pattern AMP follows.
- "Governed Memory" (arXiv 2603.17787) — the Co-memorize HITL
  pattern that informs AMP's governance channel.
