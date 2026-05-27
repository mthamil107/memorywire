# Study protocol — researcher session script

> The researcher reads or paraphrases this script for every session.
> Italicised text is direction for the researcher (do not read aloud);
> non-italicised text is the verbatim script.

---

## Pre-session setup (researcher, 10 min before)

*Before the participant joins:*

1. Reset the demo database to its seeded state:
   `.venv/Scripts/python.exe docs/demos/seed_demo_db.py` (or the
   equivalent path on your system). This produces a deterministic
   `docs/demos/demo-ui.db` with 2 approved memories + 2 pending memories
   under `agent_id=customer-bot`, plus one historical audit-log row.
2. Start the governance UI pointed at that DB:
   `AMP_UI_DB_PATH=docs/demos/demo-ui.db .venv/Scripts/python.exe -m amp_ui`.
3. Open the UI in a fresh browser window. Confirm `/`, `/audit`,
   `/co-memorize`, `/patterns`, and `/health-dashboard` all render.
4. Open the pre-study survey response for this participant; have
   their `P##` code ready.
5. Start Zoom in a private room. Open this protocol document on your
   second monitor.
6. Have ready: a stopwatch app or per-task timer; a notes document
   keyed by `P##` and task ID; the NASA-TLX and post-task survey
   forms ready to share.

---

## 0. Welcome (0:00 - 0:03, 3 min)

> Hi `[participant first name]`, thank you for joining. I'm
> `[PI name]`, and as the recruitment email mentioned I'm the author
> of the project we're going to be looking at — please don't hold
> back on critical feedback, that's exactly what I'm here for.
>
> Today's session will take about 40 minutes. We'll start with a
> consent form, do five short tasks in the UI, fill out two short
> questionnaires, and finish with a quick debrief. Sound okay?

*Wait for confirmation.*

> Before we start recording, let me walk through the consent form.

*Share screen showing `01-consent-form.md`. Read the four bullets
under "What participation involves," the recording disclosure, the
voluntary-withdrawal paragraph, and the COI disclosure. Pause for
questions after each.*

> Do you consent to participate, and to being recorded?

*If yes — start Zoom recording, ask participant to type "I consent"
in the chat. Note the participant code and timestamp in your notes.*

*If no to recording — proceed without recording; take written notes
only.*

---

## 1. Pre-study survey verification (0:03 - 0:08, 5 min)

> You filled out a short survey before the session — I want to make
> sure I have your answers right. `[Confirm key answers verbally;
> ask Q7 (job role) and Q8 (years with LLMs/RAG) again if responses
> were terse.]`

*If the participant didn't complete the survey before the session, run
through `03-pre-study-survey.md` now. Don't proceed to tasks until it's
done.*

---

## 2. UI orientation (0:08 - 0:13, 5 min)

> Let me give you a quick tour of the interface before we start the
> tasks. *Share the UI screen.*
>
> This is the AMP governance UI. The context is: there's an AI agent
> running somewhere — let's call it a customer-support bot — and
> every time it wants to write something to its memory store, the
> write can be flagged as "needs human approval." When that happens,
> the write shows up here, in this Pending Approvals queue. *Point at
> `/`.*
>
> Each pending row shows the proposed content, the memory type
> (semantic, episodic, procedural, or emotional), the agent's
> confidence, and a structured diff against existing memories under
> the same `agent_id`. There are Approve and Reject buttons on each
> row.
>
> Across the top you'll see four other tabs: the audit log of every
> governance decision the system has ever taken; co-memorize, which
> is bulk review of "should we forget or merge these"; patterns,
> which is auto-allow recommendations after you've made consistent
> decisions; and health dashboard, which is meta-statistics on memory
> staleness and contradictions.
>
> The data you'll see is fictional — a seeded demo database
> simulating a customer-service bot. Nothing you do here affects any
> real system.

*Ask: "Any questions about the interface before we start the tasks?"*

> One more thing: I'd like you to **think aloud** while you work —
> talk through what you're looking at, what you're considering,
> what's confusing, what makes sense. It feels weird at first but
> after the first task it's normal. There are no wrong answers —
> I'm evaluating the interface, not you.

---

## 3. Tasks (0:13 - 0:28, 15 min total, ~3 min each)

*Hand off control to `05-tasks.md`. For each task:*

1. *Reset the DB to seeded state if a prior task perturbed it (T3
   and T5 do; T1, T2, T4 don't).*
2. *Read the task statement to the participant.*
3. *Start the timer.*
4. *Stay silent except to remind them to think aloud if they go quiet
   for more than ~15 seconds, or to reassure them if they get stuck.
   If a task hits the 3-minute soft cut-off and the participant is
   still stuck, ask: "How would you like to proceed if I told you we
   had to move on — would you give up, or guess?" Record the response
   as the outcome.*
5. *Stop the timer when the participant says "done" or hits the
   success criterion in `05-tasks.md`.*
6. *In your notes, record: time elapsed, success y/n, what they got
   stuck on, any quote worth keeping verbatim.*

Per-task timing budget: ~3 minutes each. Five tasks × 3 min = 15 min.
If a task ends quickly, do not "pad" — proceed to the next one.

---

## 4. NASA-TLX (0:28 - 0:31, 3 min)

> Now I'm going to ask you to fill out a standard cognitive-workload
> questionnaire called NASA-TLX. It's six questions about how the
> task session felt overall, plus a quick pairwise comparison at the
> end. Think about all five tasks combined, not any one task.

*Share the NASA-TLX form (`06-nasa-tlx.md`). The participant fills it
out on screen-share. The pairwise weighting (15 comparisons) is also
done verbally — read each pair, the participant says which contributed
more to workload.*

*If the participant prefers, send the form via Google Forms link and
let them fill it independently in 2-3 minutes while you stay on the
call.*

---

## 5. Post-task survey (0:31 - 0:36, 5 min)

> A few more questions specific to the UI.

*Share `07-post-task-survey.md`. Read each item; record the Likert
response. Allow the participant to elaborate on the two open-ended
questions at the end — these are the highest-signal moments of the
session.*

---

## 6. Debrief (0:36 - 0:41, 5 min)

*Read `08-debrief.md` aloud. Then:*

> Two final open-ended questions before we wrap up.
>
> 1. If you could change one thing about this UI, what would it be?
> 2. Anything else you want me to know that I didn't ask about?

*Take notes. Thank the participant. Confirm gift-card email address.*

> Thanks `[name]`. I'll send the gift card to `[email]` within 48
> hours. If anything comes up later that you wish you'd mentioned,
> reply to my recruitment email any time.

*Stop the recording. Save the recording with filename `P##-YYYY-MM-DD.mp4`
(or .webm). Move it to the encrypted study directory immediately.
Update the session log with: P##, date, duration, any anomalies.*

---

## Session-end checklist

- [ ] Zoom recording saved with `P##-YYYY-MM-DD` filename.
- [ ] Recording moved to encrypted study directory.
- [ ] Quantitative responses entered into the study spreadsheet matching
      `synthetic-data.csv` schema.
- [ ] Notes saved with task-by-task timestamps and quotes.
- [ ] Gift card scheduled / sent.
- [ ] Demo DB reset (`seed_demo_db.py`) ready for next participant.
