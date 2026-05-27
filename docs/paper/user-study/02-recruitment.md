# Recruitment — email template + screening criteria

> Two artifacts:
> 1. The recruitment email the PI sends to candidates.
> 2. The screening criteria the PI applies to responses.

---

## 1. Recruitment email template

**Subject:** Paid 40-minute remote study — usability of an AI-agent
memory governance UI (USD 15)

**Body:**

> Hi `[NAME]`,
>
> I'm `[PI NAME]` at `[INSTITUTION]`. I'm running a short remote
> usability study for an open-source governance interface I built for
> AI-agent memory writes — the Agent Memory Protocol (AMP) governance
> UI. I'm looking for 15 software engineers or ML practitioners who
> have experience reviewing or writing code that touches AI agents or
> vector databases.
>
> The session is ~40 minutes over Zoom: you'll do five short tasks in
> the UI, think aloud, fill out a workload questionnaire, and chat with
> me about what you saw. Compensation is a USD 15 Amazon gift card.
>
> A 90-second screening questionnaire is here: `[SCREENING LINK —
> Google Form or equivalent that mirrors `03-pre-study-survey.md`]`.
>
> Conflict of interest disclosure: I'm the author of the open-source
> project being evaluated, so I'm genuinely interested in honest
> negative feedback — there's no wrong answer.
>
> Happy to answer any questions. Reply to this email or DM me.
>
> Thanks,
> `[PI NAME]`
> IRB protocol `[IRB-#####]` · `[INSTITUTION]`

Word count: ~155 words (target was ~120; the COI disclosure pushes it
over but is non-negotiable per IRB protocol).

---

## 2. Screening criteria

Applied to responses on the screening questionnaire. A candidate
**passes** screening if **all** of the inclusion items are true and
**none** of the exclusion items are true.

### Inclusion (all must be true)

1. **Age ≥ 18.**
2. **Current or recent role** as software engineer, ML engineer, data
   scientist, applied researcher, or closely related role.
3. **Hands-on experience** with at least one of:
   - Writing code that calls an AI agent (OpenAI, Anthropic,
     open-weight model via an SDK or HTTP API).
   - Reviewing code or output produced by an AI agent (PRs, generated
     content, automated decisions).
   - Working with a vector database (pgvector, Pinecone, Chroma,
     Weaviate, Qdrant, sqlite-vec, FAISS, or similar).
4. **English fluency** sufficient to think aloud for ~15 minutes
   without difficulty.
5. **Equipment:** computer with Zoom, working microphone, willingness
   to share screen during the session.

### Exclusion (any one disqualifies)

1. Under 18.
2. Currently a direct report of the PI or otherwise in a reporting
   relationship that could create perceived coercion.
3. Has previously contributed to the AMP repository
   (`github.com/mthamil107/agent-memory-protocol`). This is checked by
   asking the candidate directly on the screening form and by spot-
   checking GitHub usernames against the commit log.
4. Already participated in a prior pilot session of this study.

### Diversity of the participant pool

The PI explicitly does not recruit by demographic category, but does
try to ensure the n = 15 sample spans:

- A range of **seniority** (target: ~3 participants each at junior /
  mid / senior / staff+ levels by self-report).
- A range of **AI-agent familiarity** (1-5 scale on the pre-study
  survey; target at least 3 participants in each of the bottom two
  categories so the study captures the "first-time governance reviewer"
  experience accurately).
- A range of **organization types** (FAANG, startup, academic /
  research lab, freelance / consultant). Not strictly stratified but
  noted in §5.5.2 of the paper.

---

## 3. Workflow

1. PI posts recruitment message in the channels listed in
   `00-irb-application.md §3`.
2. Candidates fill out the screening questionnaire (mirror of
   `03-pre-study-survey.md`, plus inclusion/exclusion check items).
3. PI reviews responses within 24-48 hours.
4. Passing candidates receive a follow-up email with the consent form
   (`01-consent-form.md`) and a Calendly / scheduling link.
5. Candidates pick a session slot.
6. Day-of: session proceeds per `04-study-protocol.md`.
7. Gift card delivered within 48 hours of session completion.
