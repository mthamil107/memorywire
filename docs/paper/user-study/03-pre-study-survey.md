# Pre-study survey

> Administered electronically (Google Forms or equivalent) **before**
> the session. Estimated completion time: 5 minutes. Used both for
> screening (eligibility check items live alongside these in the
> screening form) and for §5.5.2 participant-characteristics
> reporting.

---

**Participant code:** `P____` (assigned by researcher after receipt;
the participant does not see this).

---

## Q1. Years of professional software experience

> Counts professional / full-time-equivalent years writing software for
> employers or clients. Does not count purely academic coursework.

- [ ] Less than 1 year
- [ ] 1-2 years
- [ ] 3-5 years
- [ ] 6-10 years
- [ ] 11-15 years
- [ ] More than 15 years

---

## Q2. Familiarity with AI agents

> "AI agent" here means a piece of software that uses an LLM (or
> similar) and takes actions — calls tools, reads/writes external
> state, or runs in a loop with feedback. Not just one-shot prompting.

How familiar are you with building, reviewing, or debugging AI agents?

- [ ] 1 — Not at all familiar (haven't worked with them)
- [ ] 2 — Slightly familiar (read about them; one or two toy experiments)
- [ ] 3 — Moderately familiar (built or shipped one; understand the
  basics of tool use, state, and prompt structure)
- [ ] 4 — Very familiar (work with them regularly; comfortable with
  loops, tool routing, evaluation)
- [ ] 5 — Expert (publish, teach, or lead engineering on agent systems)

---

## Q3. Familiarity with vector databases

> pgvector, Pinecone, Chroma, Weaviate, Qdrant, sqlite-vec, FAISS, or
> similar.

How familiar are you with vector databases?

- [ ] 1 — Not at all familiar
- [ ] 2 — Slightly familiar (read docs; never deployed one)
- [ ] 3 — Moderately familiar (used one in a project)
- [ ] 4 — Very familiar (shipped to production; tuned indexes / recall)
- [ ] 5 — Expert (build them, contribute to one, or publish on the
  underlying retrieval methods)

---

## Q4. Audit / review experience with agent-generated content

Have you ever audited, reviewed, or moderated content that an AI agent
generated or wrote into a system (RAG outputs, memory writes, tool
calls, automated PRs)?

- [ ] Yes — regularly, as part of my job.
- [ ] Sometimes — occasionally, e.g. for spot-checks or incident review.
- [ ] No — I have not done this.

---

## Q5. Prior exposure to memory frameworks

Which of the following AI-memory frameworks or libraries have you used?
(Multi-select; check all that apply.)

- [ ] mem0
- [ ] Letta (formerly MemGPT)
- [ ] Cognee
- [ ] Zep
- [ ] LangChain Memory
- [ ] LlamaIndex memory modules
- [ ] MemoryOS
- [ ] AMP (Agent Memory Protocol)
- [ ] Other: ______
- [ ] None of the above

---

## Q6. Importance of governance / audit for AI systems

In the work you do, how important is governance — auditability,
approval workflows, and human review — for AI systems?

- [ ] 1 — Not important at all
- [ ] 2 — Slightly important
- [ ] 3 — Moderately important
- [ ] 4 — Very important
- [ ] 5 — Critical / a hard requirement

---

## Q7. Current job role

> Free text. Use your own words; we'll normalize for reporting.

`__________________________________________________________________`

Example responses: "Senior Software Engineer at a fintech startup",
"Staff ML Engineer, recommendation systems", "Postdoc researcher in
NLP".

---

## Q8. Years working with LLMs / RAG systems

> Free text.

`__________________________________________________________________`

Example responses: "About 2 years, since GPT-3.5 came out",
"~6 months, mostly RAG prototypes", "I worked on retrieval pre-LLMs
since 2018; LLM-era for ~3 years".

---

## Reporting

For §5.5.2 of the paper, the PI will report:

- **Q1 distribution** as a histogram (years of experience).
- **Q2-Q3** as means with 95% CIs.
- **Q4-Q5** as counts and proportions.
- **Q6** as a mean with 95% CI.
- **Q7-Q8** narratively summarized.

No individual participant's responses will be reported in a way that
makes them identifiable.
