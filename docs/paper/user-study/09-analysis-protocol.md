# Analysis protocol â€” pre-registered

> Locked **before** any real participant data is collected. Treat this
> as the analysis pre-registration: deviations from this plan must be
> reported as exploratory in the paper. Synthetic data
> (`synthetic-data.csv`) was used only to verify that `analyze.py`
> produces the expected output schema; no statistical decisions were
> calibrated against it.

---

## 1. Outcomes

### 1.1 Primary outcome

**NASA-TLX weighted overall workload score** (0-100; lower is better).

Computed per the procedure in `06-nasa-tlx.md Â§3`: each of the six
dimensions is rated 0-100 on a 20-step bipolar scale, the Performance
dimension is reversed (`100 - raw`), each dimension is weighted by the
count of times it was selected in the 15 pairwise comparisons (weight
range 0-5, sum = 15), and the weighted sum divided by 15 gives the
overall score.

Reported as: mean, median, IQR, 95% CI (bootstrap, 10 000 resamples)
across the n = 15 participants.

### 1.2 Secondary outcomes

- **Per-task success rate** â€” fraction of participants meeting each
  task's success criterion in `05-tasks.md` within the 3-minute budget.
  Reported per task with 95% CI (Wilson interval).
- **Per-task completion time** â€” seconds from task start (researcher
  starts timer) to task end (success or timeout). Reported as mean,
  median, IQR, 95% CI per task. Time-to-timeout (180 s) is recorded
  for failures.
- **Per-task Likert confidence (L1)** â€” mean and 95% CI per task on
  the 1-7 scale.
- **Overall Likert items (L2-L7)** â€” mean and 95% CI per item.
- **NASA-TLX per-dimension** â€” mean and 95% CI per dimension; also
  reported as Raw TLX (unweighted average across the six dimensions
  with Performance reversed).

### 1.3 Tertiary / exploratory

- Correlation between **prior agent / vector-DB familiarity** (Q2, Q3
  on the pre-study survey) and per-task success rate. Reported as
  Spearman Ï with 95% CI.
- Correlation between **L4 production-trust** and **mental-demand
  NASA-TLX**. Hypothesis (directional, but not pre-confirmatory):
  participants reporting higher mental demand will report lower
  production trust. Reported as Spearman Ï with 95% CI.

These are exploratory because n = 15 cannot reliably resolve a
correlation between two noisy variables; they are reported for future
hypothesis generation rather than as conclusions.

---

## 2. Statistical approach

We do **not** perform null-hypothesis significance testing. With
n = 10-20 the statistical power to detect realistic effects is too low
for NHST to be meaningful; reporting p-values invites
mis-interpretation as confirmatory evidence. Instead we report
**descriptive statistics with 95% confidence intervals** throughout.

- **Means with 95% CIs:** parametric (t-distribution) when n â‰¥ 15 and
  the dimension is roughly continuous (Likert, time, TLX score);
  bootstrap (BCa, 10 000 resamples) as a robustness check for any
  dimension where the t-CI assumption is in doubt.
- **Proportions with 95% CIs:** Wilson interval (more conservative
  than Wald for small n).
- **Correlations:** Spearman Ï with bootstrap 95% CIs.

The paper will explicitly state in Â§5.5.3 that the sample size is too
small for confirmatory inference and that all numbers are
descriptive / exploratory.

### 2.1 Sample-size justification

n = 10-20 per Nielsen (2000): *"5 users are enough to find the major
usability problems; additional users find diminishing-return
problems."* We target n = 15 â€” well past the Nielsen elbow at 5,
roughly the point at which the cumulative-problem-discovery curve
plateaus across studies in the Nielsen Norman Group corpus, and small
enough to be feasible for a single researcher on an 8-week timeline.
Range 10-20 is the acceptable band: we stop early if recruitment
stalls at 10, and at most run 20 before declaring the budget exhausted.

We are explicit that this n cannot support claims about absolute
population-level effect sizes; it can support relative comparisons
within the sample and qualitative theme saturation.

---

## 3. Qualitative analysis

### 3.1 Transcription

Audio is auto-transcribed using OpenAI Whisper (or equivalent). The PI
manually corrects errors against the recording. Real names, employer
names, and any other potentially identifying details are replaced with
generic tokens (`[NAME]`, `[EMPLOYER]`) during the cleanup pass.

### 3.2 Coding method

**Inductive thematic analysis** per Braun & Clarke (2006):

1. Each coder reads all 15 transcripts cover-to-cover before coding
   begins (familiarization pass).
2. Each coder independently generates initial codes for one
   transcript, then meets with the other coder to align on coding
   conventions.
3. Each coder independently codes all 15 transcripts.
4. Codes are organized into candidate themes.
5. Themes are reviewed across the two coders and consolidated.
6. Final themes are named and defined.

### 3.3 Inter-rater reliability

**Cohen's kappa** computed on theme assignments to coding units
(roughly: each substantive utterance or screen-action sequence) across
the 15 transcripts.

**Acceptance threshold:** kappa â‰¥ **0.61** ("substantial agreement"
per Landis & Koch, 1977). McHugh (2012) argues 0.61 is the floor for
serious use, with 0.81 ("almost perfect") preferred for high-stakes
decisions. Because this is exploratory usability work and not a
high-stakes decision, 0.61 is the pre-registered floor.

**If kappa < 0.61:** a third coder joins; the three coders convene a
consensus-coding pass; final themes are accepted only on three-way
agreement. Kappa is recomputed and reported transparently in Â§5.5.4.

### 3.4 Coder selection

- **Coder 1:** the PI.
- **Coder 2:** `[NAME OR ROLE â€” e.g., a colleague external to the memwire
  project, recruited specifically for this study to mitigate the PI's
  COI]`.
- **Coder 3 (only if needed):** `[NAME OR ROLE]`.

---

## 4. Reporting plan

The paper's Â§5.5 is structured as:

- **Â§5.5.1 Method** â€” lifted from `04-study-protocol.md` and
  `05-tasks.md`.
- **Â§5.5.2 Participants** â€” n; aggregate stats from
  `03-pre-study-survey.md`.
- **Â§5.5.3 Quantitative results** â€” TLX table; per-task table; Likert
  table; figure with bar chart + radar from `analyze.py`.
- **Â§5.5.4 Qualitative themes** â€” 3-7 themes with representative
  de-identified quotes; kappa reported.
- **Â§5.5.5 Threats to validity** â€” sample size; remote-only; lack of
  comparison condition; PI's role; convenience sample.

### 4.1 What gets published as supplementary material

- The fully de-identified quantitative CSV (same schema as
  `synthetic-data.csv` but with real responses).
- The codebook (final theme list with definitions).
- Anonymized representative quotes per theme.
- This protocol document (locked at study start).
- `analyze.py` (frozen at submission time).

**Not** published: raw transcripts, recordings, real participant
identifiers, anything an IRB review of the supplementary material would
flag.

---

## 5. Pre-commitment to publishing negative results

The PI commits to reporting the study findings regardless of outcome.
If the UI scores poorly on TLX, has low per-task success, or surfaces
serious usability problems, those results appear in Â§5.5 with the same
prominence as positive results. The paper will not be re-framed around
the components that worked while burying the components that did not.

---

## 6. Deviations log

Any deviations from this protocol â€” e.g. recruitment cut short at
n = 10, a task modified mid-study, an additional analysis performed â€”
will be logged here at the time they happen, with a note explaining
why. The deviations log is reported in Â§5.5.5.

| Date | Deviation | Rationale |
|---|---|---|
| `[YYYY-MM-DD]` | `[describe]` | `[why]` |

---

## 7. References

- Braun, V., & Clarke, V. (2006). *Using thematic analysis in
  psychology.* Qualitative Research in Psychology, 3(2), 77-101.
- Landis, J. R., & Koch, G. G. (1977). *The measurement of observer
  agreement for categorical data.* Biometrics, 33(1), 159-174.
- McHugh, M. L. (2012). *Interrater reliability: the kappa statistic.*
  Biochemia Medica, 22(3), 276-282.
- Nielsen, J. (2000). *Why you only need to test with 5 users.* Nielsen
  Norman Group.
