# IRB Application â€” memorywire Governance UI Usability Study

> Template targeting **minimum-risk / expedited review** classification.
> Fill every `[BRACKETED]` field before submission. The investigator is
> responsible for confirming that the local IRB's category 7 (research
> on individual or group characteristics or behavior, including software
> usability) covers this protocol â€” most U.S. R1 university IRBs do.

---

## 1. Investigator statement

- **Principal Investigator:** `[FULL NAME]`
- **Affiliation:** `[INSTITUTION / DEPARTMENT]`
- **Email:** `[PI EMAIL]`
- **Phone:** `[PI PHONE]`
- **Faculty advisor (if PI is a student):** `[ADVISOR NAME AND EMAIL]`
- **IRB protocol number:** `[ASSIGNED BY IRB AFTER INITIAL REVIEW]`
- **Study title:** Usability evaluation of the memorywire Governance UI: a
  diff-and-approve interface for AI-agent memory writes.
- **Anticipated start date:** `[YYYY-MM-DD]`
- **Anticipated end date:** `[YYYY-MM-DD]` (estimate 8 weeks after start)

By signing below the PI affirms that (a) the study will be conducted as
described in this application, (b) any deviations or amendments will be
submitted to the IRB before implementation, (c) all study personnel
have completed required human-subjects training (e.g. CITI), and
(d) participant data will be handled per the data-storage plan in Â§7.

Signature: ______________________________  Date: ______________

---

## 2. Project summary

The memorywire is an open-source wire format for
agent-memory operations. Alongside the protocol memorywire ships a
**governance UI** â€” a web interface where a human operator reviews
pending memory writes that the agent has flagged as requiring approval.
The reviewer sees a structured diff between the proposed memory and
existing memories under the same `agent_id` and either approves or
rejects each pending row. The same UI surfaces an audit log of every
governance decision, a bulk-review screen for co-memorize forget/merge
candidates, and an "approval-patterns" screen that recommends auto-allow
rules after the operator has produced N consistent decisions.

The empirical question we want to answer: does the diff-and-approve
flow give a software engineer or ML practitioner â€” somebody who has not
previously used the UI â€” enough information to make correct approve /
reject decisions with reasonable cognitive workload? The study will be
reported as Â§5.5 of the memorywire paper. There is no comparison condition;
this is a within-subject single-arm exploratory evaluation.

The methodology is a remote think-aloud usability study. Each
participant joins a ~40-minute Zoom session, completes a pre-study
survey, performs five tasks against a seeded demonstration database,
fills out the NASA-TLX cognitive-workload questionnaire and a
task-specific Likert-scale survey, and answers debrief questions. The
researcher records video, audio, and screen with explicit consent. No
personal data is collected beyond what the participant volunteers in
the demographic survey (job role, years of experience). Participants
never see real production memory data; the database is a deterministic
seed of fictional customer-service interactions created for the demo.

---

## 3. Recruitment plan

**Target population:** software engineers and machine-learning
practitioners with experience writing or reviewing code that involves
AI agents or vector databases.

**Sample size:** n = 15 (range 10-20). Sample-size rationale per Nielsen
(2000) â€” usability studies converge on the major problems at
approximately 5 participants, and 15 captures additional minority-case
problems while remaining feasible for a single investigator on an
8-week timeline.

**Recruitment channels:**

1. The investigator's professional network on LinkedIn (one post + DMs
   to candidates who pass the screening criteria in Â§3.1).
2. The memorywire open-source project's GitHub Discussions board (one pinned
   post linking to the screening survey).
3. Two or three relevant Slack / Discord communities for ML
   practitioners (one post each, posted only in channels that allow
   research recruitment).
4. Snowball referrals from the first wave of participants.

No paid advertising. No recruitment from the investigator's own
students or direct reports.

### 3.1 Screening criteria

**Inclusion:**

- 18 years of age or older.
- Currently or recently employed as a software engineer, ML engineer,
  data scientist, or in a closely related role.
- Has written, reviewed, or audited code that uses an AI agent (e.g.
  OpenAI / Anthropic / open-weight model) or a vector database (e.g.
  pgvector, Pinecone, Chroma, Weaviate, sqlite-vec).
- Speaks English fluently enough to think aloud for ~15 minutes.
- Willing to share their screen during the session.

**Exclusion:**

- Anyone employed by the same organization as the PI in a reporting
  relationship (eliminates coercion concern).
- Anyone who has previously contributed to the memorywire repository
  (eliminates familiarity-bias concern).
- Anyone under 18.

---

## 4. Consent process

Consent is collected electronically at the start of each session before
any recording begins. The form is in `01-consent-form.md` and is
displayed via screen-share. The researcher reads the key points aloud,
asks the participant if they have questions, and asks the participant
to type "I consent" (or click an equivalent button) in the chat to
record acceptance. Electronic consent is appropriate for a minimum-risk
software-UX study per 45 CFR 46.117(c)(1)(ii) â€” the consent form is
not the only documentation of identity, and the research presents no
more than minimal risk.

Participants are explicitly told they may decline to be recorded; if
they decline, the session continues without recording and the
researcher takes notes only. (Anecdotally we expect zero such cases
given the audience, but the option is offered.) Participants may
withdraw at any time during the session by saying so; if they
withdraw, recordings to that point are deleted within 7 days and any
data already collected is destroyed.

---

## 5. Risks and mitigations

The study presents **minimal risk** in the meaning of 45 CFR 46.102(j) â€”
"the probability and magnitude of harm or discomfort anticipated in the
research are not greater in and of themselves than those ordinarily
encountered in daily life or during the performance of routine
physical or psychological examinations or tests."

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| Mild frustration with a confusing UI task | Moderate | Low | Tasks are timed at 3 minutes each with a soft cut-off; the researcher reassures participants that the UI, not the participant, is being evaluated; debrief script re-emphasizes this. |
| Time burden (~40 min) | Certain (by design) | Low | Compensation (USD 15 gift card) acknowledges the time. |
| Loss of confidentiality (recording leaks) | Very low | Moderate | Recordings stored encrypted; access limited to investigator; deleted after analysis (see Â§7). |
| Inadvertent disclosure of employer-confidential information during think-aloud | Low | Low-Moderate | Participants are reminded at session start to avoid discussing employer-confidential systems; researcher pauses recording on request. |
| Coercion / undue influence | Low | Low | Recruitment excludes investigator's reports; compensation rate is modest relative to participant earning power. |

There are no physical, legal, financial, or reputational risks beyond
the above.

---

## 6. Benefits

**To participants:** none material beyond the compensation. Participants
do gain exposure to a governance UI design pattern they may find
professionally interesting; the researcher mentions this in recruitment
but does not represent it as a benefit on the consent form.

**To science / society:** an empirical evaluation of a HITL governance
interface for AI-agent memory writes, contributing to the
human-in-the-loop AI-safety literature and to the design of future
governance interfaces. Findings will be reported in a peer-reviewed
publication and the materials in this directory will be released under
an open license so future researchers can replicate.

---

## 7. Data storage and retention

**What is collected:**

- Pre-study survey responses (8 questions; no direct identifiers).
- Audio, video, and screen recording of the ~40-minute session.
- NASA-TLX raw scores and pairwise weighting choices.
- Post-task Likert responses.
- Think-aloud transcript (auto-transcribed via Whisper, manually
  corrected).
- Researcher notes.

**What is NOT collected:** legal name (a study-assigned code `P01..P15`
is used throughout), email after recruitment is closed, IP address,
geolocation, employer name, or any other directly identifying field.

**Storage:**

- Quantitative data is stored as CSV files in an encrypted directory on
  the PI's institution-provided cloud storage (`[INSTITUTION CLOUD
  PROVIDER]`). Access limited to study personnel listed in Â§1.
- Recordings are stored encrypted in the same directory. **Recordings
  are deleted within 90 days of session completion** after transcripts
  have been verified and the auto-coded analysis is locked.
- De-identified transcripts and quantitative data are retained for
  **5 years** per `[INSTITUTION POLICY]`, then destroyed.

**Sharing:**

- Aggregate statistics and de-identified quotations appear in the memorywire
  paper.
- The fully de-identified quantitative CSV will be released as
  supplementary material on Zenodo with the paper.
- Recordings are **never** shared outside the study team. Transcripts
  are never shared in raw form; only quoted excerpts that are
  themselves de-identified appear in the paper.

---

## 8. Compensation

USD 15 Amazon gift card delivered via email within 48 hours of session
completion. Participants who withdraw mid-session still receive the
full gift card; participants who complete the pre-study survey but
cancel the session receive nothing (no work was performed). The
compensation is funded from `[FUNDING SOURCE â€” DEPARTMENTAL DISCRETIONARY
FUND / GRANT NUMBER]`.

Total compensation budget: 15 Ã— USD 15 = **USD 225**.

If a participant prefers an alternative gift-card brand (e.g. for
international participants where Amazon delivery is awkward), the
researcher may substitute an equivalent-value alternative at their
discretion.

---

## 9. Inclusion and exclusion criteria

Restated in protocol form for IRB reviewer convenience.

**Included:**

- Age â‰¥ 18.
- Self-identified software engineer / ML engineer / data scientist or
  closely related role.
- Practical experience with AI agents or vector databases.
- Sufficient English fluency for ~15 minutes of unscripted think-aloud
  speech.
- Access to a computer with Zoom installed and a stable internet
  connection.

**Excluded:**

- Under 18.
- Reports to the PI or has any other coercion-creating relationship to
  the study team.
- Previously contributed to the memorywire open-source repository (commits,
  reviews, or substantive issue comments).
- Cannot or will not share screen.

There is no exclusion based on gender, race, ethnicity, national
origin, disability status, or any other protected category. Pregnant
participants, minors, and prisoners are not separately recruited and
the protocol is not designed for those populations.

---

## 10. Conflicts of interest

The PI is the author and primary maintainer of the memorywire open-source
project being evaluated. This is disclosed in the recruitment email
(`02-recruitment.md`) and in the consent form (`01-consent-form.md`).
The PI mitigates the conflict by (a) not personally analyzing the
qualitative think-aloud transcripts as the sole coder (a second coder
participates per Â§11), (b) reporting all results â€” positive and
negative â€” in the paper without selection, and (c) releasing raw data
in de-identified form for independent re-analysis.

---

## 11. Inter-rater reliability for qualitative analysis

Two coders independently apply inductive theme analysis to the
think-aloud transcripts. Cohen's kappa is computed on theme assignments
across the 15 transcripts. Per Landis and Koch (1977), kappa â‰¥ 0.61
("substantial agreement") is the threshold for accepting the coding;
disagreements below that threshold trigger a third coder and a
consensus-coding pass. The second coder is `[NAME OR ROLE â€” e.g.
a colleague external to the memorywire project, recruited specifically for
this study]`.

---

## 12. References

- Hart, S. G., & Staveland, L. E. (1988). *Development of NASA-TLX
  (Task Load Index): Results of empirical and theoretical research.*
  In P. A. Hancock & N. Meshkati (Eds.), Human mental workload (pp.
  139-183). North-Holland.
- Landis, J. R., & Koch, G. G. (1977). *The measurement of observer
  agreement for categorical data.* Biometrics, 33(1), 159-174.
- Nielsen, J. (2000). *Why you only need to test with 5 users.* Nielsen
  Norman Group.
- 45 CFR 46 â€” U.S. Federal Policy for the Protection of Human Subjects
  ("Common Rule").

---

## 13. Attachments (submitted alongside this application)

- `01-consent-form.md` â€” informed-consent form.
- `02-recruitment.md` â€” recruitment email + screening criteria.
- `03-pre-study-survey.md` â€” pre-study demographic survey.
- `04-study-protocol.md` â€” researcher session script.
- `05-tasks.md` â€” the five governance-UI tasks.
- `06-nasa-tlx.md` â€” NASA-TLX questionnaire.
- `07-post-task-survey.md` â€” post-task survey instrument.
- `08-debrief.md` â€” debrief script.
- `09-analysis-protocol.md` â€” pre-registered analysis plan.
