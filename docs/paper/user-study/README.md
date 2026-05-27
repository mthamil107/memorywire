# AMP Governance UI — User Study Materials

> Version: v0 — 2026-05-27
> Audience: the AMP project author preparing the §5.5 user study
> reported in the AMP paper.
> Status: **IRB-ready templates**, not yet filed.

This directory holds every document, form, script, and analysis template
needed to (a) file a minimum-risk IRB application, (b) recruit
participants, (c) run a remote think-aloud usability session against the
AMP governance UI, and (d) analyze the resulting data for the paper's
§5.5. Nothing here has been submitted to an IRB or run against real
participants — the materials are templates with placeholders for the
fields a specific institution will require.

The study question reported in §5.5 of the paper is:

> *Can a software engineer or ML practitioner who has not seen the AMP
> governance UI before complete five realistic diff-and-approve tasks
> with low cognitive workload (NASA-TLX), reasonable per-task success
> rates, and self-reported confidence that the UI is suitable for gating
> production memory writes?*

The study is **exploratory** — n is small (target 15, range 10-20 per
Nielsen 2000) and we do not pre-register null-hypothesis significance
tests. The output is descriptive statistics with 95% confidence intervals
plus qualitative themes from the think-aloud transcripts.

---

## File list

| File | Purpose |
|---|---|
| `README.md` | This document — orientation, runbook, budget, timeline. |
| `00-irb-application.md` | Minimum-risk IRB application template with `[BRACKETED]` fields the investigator fills in. |
| `01-consent-form.md` | Informed-consent form for electronic acceptance at session start. |
| `02-recruitment.md` | Recruitment email template + screening criteria. |
| `03-pre-study-survey.md` | 8-question demographics + technical-background survey. |
| `04-study-protocol.md` | Researcher session script with per-segment timing. |
| `05-tasks.md` | The five governance-UI tasks participants perform. |
| `06-nasa-tlx.md` | Standard NASA-TLX 6-dimension form + 15-pair weighting procedure. |
| `07-post-task-survey.md` | Task-specific 7-point Likert questions + open-ended prompts. |
| `08-debrief.md` | Post-session debrief script (~150 words) the researcher reads aloud. |
| `09-analysis-protocol.md` | Pre-registered analysis plan: outcomes, statistics, qualitative coding. |
| `analyze.py` | Python script that ingests CSV data and emits a summary + plots. |
| `synthetic-data.csv` | 15-participant synthetic dataset for pipeline testing. |

---

## Runbook

The end-to-end flow from "we want to run this study" to "we have a §5.5
ready for the paper" is roughly eight weeks. The steps below are
sequential; each links to the file that contains the actual artifact.

### Step 1. File the IRB application (week 1)

1. Open `00-irb-application.md`.
2. Fill every `[BRACKETED PLACEHOLDER]` with institution-specific
   details (PI name, affiliation, contact, protocol number once
   assigned, etc.).
3. Attach `01-consent-form.md`, `02-recruitment.md`, `03-pre-study-survey.md`,
   `04-study-protocol.md`, `05-tasks.md`, `06-nasa-tlx.md`,
   `07-post-task-survey.md`, and `08-debrief.md` as appendices.
4. Submit via the institution's IRB portal.
5. Expected review time: **1-2 weeks expedited** at a typical R1 university
   (minimum-risk classification — no PII, no health data, software UX
   evaluation only), or **4-6 weeks if full board** review is required.

### Step 2. Recruit participants (weeks 2-3)

1. Use the email template in `02-recruitment.md`.
2. Apply the screening criteria in the same file (software engineer or
   ML practitioner; has reviewed AI-agent output or worked with vector
   DBs; English-fluent for think-aloud).
3. Target n = 15 with rolling enrollment until full.
4. Schedule sessions at ~40 minutes each plus 10-minute buffer.

### Step 3. Run sessions (weeks 4-5)

1. The researcher follows `04-study-protocol.md` exactly.
2. The participant completes `01-consent-form.md` electronically before
   the session begins.
3. Recording (video + audio + screen) starts only after consent.
4. Participants think aloud while completing the five tasks in
   `05-tasks.md`.
5. After tasks: `06-nasa-tlx.md`, then `07-post-task-survey.md`.
6. Researcher reads `08-debrief.md`. Compensation gift card sent within
   48 hours.

### Step 4. Analyze (weeks 6-7)

1. Transcribe think-aloud recordings (or use auto-transcription with
   manual cleanup).
2. Compile responses into a CSV matching the schema of
   `synthetic-data.csv`.
3. Run `python analyze.py --data <your-data>.csv`.
4. The script writes `analysis-summary.md` and `analysis-plots.png`.
5. Two independent coders apply inductive theme analysis to the
   transcripts per `09-analysis-protocol.md`. Report Cohen's kappa.

### Step 5. Write up (week 8)

1. The descriptive statistics from `analyze.py` go into §5.5 of the
   paper.
2. Qualitative themes go into §5.5's "Lessons" subsection.
3. All raw data is archived in the supplemental materials with
   participant identifiers replaced by `P01..P15`.

---

## Budget

| Item | Cost |
|---|---|
| Participant compensation | 15 × USD 15 Amazon gift card = **USD 225** |
| IRB filing fee | **USD 0-200** (typical: free at academic institutions; up to USD 200 at some private IRBs) |
| Recording / transcription tools | **USD 0** if using Zoom + free Whisper transcription; ~USD 50-100 if using a paid transcription service |
| Researcher time | Out of scope (assumed in-kind) |
| **Total cash budget** | **USD 225 - 525** |

Compensation rate (USD 30/hour effective) is consistent with norms for
remote 30-40 minute UX studies of professional software engineers and
above the U.S. federal minimum wage.

---

## Expected timeline (calendar)

| Week | Activity |
|---|---|
| 1 | File IRB application; begin participant recruitment list (without contact) |
| 2 | Receive IRB approval (expedited); begin contacting candidates |
| 3 | Continue recruitment; schedule first sessions |
| 4 | Run sessions 1-8 |
| 5 | Run sessions 9-15; close recruitment |
| 6 | Transcribe think-aloud recordings; clean quantitative data |
| 7 | Run `analyze.py`; qualitative coding (two coders) |
| 8 | Write §5.5; integrate into paper draft |

Slippage on this timeline is normal — IRB queues can stretch from 2 to
6 weeks even for minimum-risk protocols at busy R1 institutions, and
participant scheduling rarely runs ahead of plan.

---

## Where the analysis output lands in the paper

The `analyze.py` outputs map onto §5.5 of the AMP paper as follows:

- **§5.5.1 — Method.** Lift from `04-study-protocol.md` and `05-tasks.md`.
- **§5.5.2 — Participants.** Aggregate stats from `03-pre-study-survey.md`
  responses (years experience, role distribution, prior familiarity).
- **§5.5.3 — Quantitative results.** `analysis-summary.md`
  TLX-overall and per-task success / time / Likert tables;
  `analysis-plots.png` for the figures.
- **§5.5.4 — Qualitative themes.** Coder-agreed themes from
  `09-analysis-protocol.md`'s coding output, with representative quotes.
- **§5.5.5 — Threats to validity.** Sample size; remote-only; lack of
  comparison condition; researcher's involvement in tool design.

---

## Constraints

- The study evaluates the **AMP governance UI as shipped at commit
  `c828d76`**. Future UI changes invalidate the §5.5 results unless
  re-run.
- The synthetic data in `synthetic-data.csv` exists solely to verify
  that `analyze.py` runs end-to-end before any real data is collected.
  It must never appear in the paper. The CSV is plausibility-calibrated
  (success ≈ 0.85, mental load 40-60, frustration 20-40) but is not a
  prediction of what the real numbers will be.
- Materials are public-domain or original work for the AMP project:
  NASA-TLX (Hart & Staveland 1988) is in the public domain; the consent
  form is adapted from the standard NIH electronic-consent template;
  every other file in this directory is original.
