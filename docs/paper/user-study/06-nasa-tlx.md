# NASA-TLX questionnaire

> Standard NASA Task Load Index (Hart & Staveland, 1988). Public-domain
> instrument. This is the **raw** form (six 20-step bipolar ratings)
> plus the 15-comparison pairwise weighting procedure to compute the
> weighted overall workload score. The Raw TLX variant (unweighted)
> may also be reported alongside the weighted score; see Â§3 below.

---

## Instructions to the participant

> The next form asks you to rate the workload of the session you just
> finished. Think about all five tasks combined, not any one task in
> isolation. For each of the six dimensions below, mark the point on
> the scale that best represents how you experienced the session.
> The scale runs from "Very Low" to "Very High" in 20 steps â€” pick
> the step that matches your experience.
>
> There are no right answers. The goal is to capture how the work
> felt to you, not to score how well you did.

---

## Part 1 â€” Raw ratings (6 items, 20-step bipolar scale each)

For each item, mark **one** value from 0 (Very Low) to 100 (Very High)
in 5-point increments â€” i.e. one of {0, 5, 10, 15, 20, 25, 30, 35, 40,
45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100}.

### M1. Mental demand

> How mentally demanding was the task? How much thinking, deciding,
> calculating, remembering, looking, searching, etc.?

`Very Low  |0|5|10|15|20|25|30|35|40|45|50|55|60|65|70|75|80|85|90|95|100|  Very High`

Score: ____

### M2. Physical demand

> How physically demanding was the task? How much pushing, pulling,
> turning, controlling, activating, etc.? (Usually low for desk-bound
> UI tasks â€” captured anyway for completeness.)

`Very Low  |0|5|10|15|20|25|30|35|40|45|50|55|60|65|70|75|80|85|90|95|100|  Very High`

Score: ____

### M3. Temporal demand

> How hurried or rushed was the pace of the task? Did you feel under
> time pressure?

`Very Low  |0|5|10|15|20|25|30|35|40|45|50|55|60|65|70|75|80|85|90|95|100|  Very High`

Score: ____

### M4. Performance

> How successful were you in accomplishing what you were asked to do?
> How satisfied were you with your performance?
>
> NOTE: the scale here is **reversed** â€” "Very Low" means "very
> successful / very satisfied" and "Very High" means "very
> unsuccessful / dissatisfied". `analyze.py` reverses this dimension
> before summing.

`Perfect  |0|5|10|15|20|25|30|35|40|45|50|55|60|65|70|75|80|85|90|95|100|  Failure`

Score: ____

### M5. Effort

> How hard did you have to work to accomplish your level of
> performance?

`Very Low  |0|5|10|15|20|25|30|35|40|45|50|55|60|65|70|75|80|85|90|95|100|  Very High`

Score: ____

### M6. Frustration

> How insecure, discouraged, irritated, stressed, or annoyed were you
> during the task?

`Very Low  |0|5|10|15|20|25|30|35|40|45|50|55|60|65|70|75|80|85|90|95|100|  Very High`

Score: ____

---

## Part 2 â€” Pairwise weighting (15 comparisons)

For each pair below, **circle the item that contributed more to the
workload** during the session you just finished. The 15 pairs cover
every unique combination of the six dimensions (C(6,2) = 15).

The number of times each dimension is circled across the 15 pairs is
its **weight** (0-5). Weights are then multiplied by the raw score
and divided by 15 (the sum of all weights) to give the weighted
overall score. See `analyze.py` for the computation.

> The researcher reads each pair aloud and records the participant's
> choice. Estimated time for all 15 pairs: 90-120 seconds.

| Pair # | Dimension A | Dimension B | Choice (circle one) |
|---:|---|---|---|
| 1  | Mental demand    | Physical demand   | M / P |
| 2  | Mental demand    | Temporal demand   | M / T |
| 3  | Mental demand    | Performance       | M / P |
| 4  | Mental demand    | Effort            | M / E |
| 5  | Mental demand    | Frustration       | M / F |
| 6  | Physical demand  | Temporal demand   | P / T |
| 7  | Physical demand  | Performance       | P / Perf |
| 8  | Physical demand  | Effort            | P / E |
| 9  | Physical demand  | Frustration       | P / F |
| 10 | Temporal demand  | Performance       | T / Perf |
| 11 | Temporal demand  | Effort            | T / E |
| 12 | Temporal demand  | Frustration       | T / F |
| 13 | Performance      | Effort            | Perf / E |
| 14 | Performance      | Frustration       | Perf / F |
| 15 | Effort           | Frustration       | E / F |

Researcher: tally the chosen-counts here for sanity:

- Mental: ____
- Physical: ____
- Temporal: ____
- Performance: ____
- Effort: ____
- Frustration: ____

Sum should equal 15. If it does not, recount.

---

## 3. Scoring

The **weighted overall workload** score is:

```
weighted_overall = sum(weight[i] * raw_score[i]) / sum(weight[i])
                 = sum(weight[i] * raw_score[i]) / 15
```

â€¦where `raw_score[i]` for the Performance dimension is **first
reversed**: `raw_score_perf = 100 - raw_marked_perf`.

The **raw (unweighted) TLX** is the simple average of the six raw
scores (with Performance again reversed). Many recent papers report
Raw TLX as it correlates strongly with weighted TLX and reduces
session time. We report both.

Both scores range 0-100; lower is better.

### Interpretation thresholds (for context only)

These come from Grier (2015), *How High Is High? A Meta-Analysis of
NASA-TLX Global Workload Scores* â€” meta-analytic norms across 1,173
NASA-TLX administrations:

- 0-9: very low workload (uncommon outside trivial tasks).
- 10-29: low.
- 30-49: medium.
- 50-79: high.
- 80-100: very high.

Software-interface evaluations typically land in the 30-50 range. Our
target for the memwire governance UI is **< 50** (medium), and ideally
**< 40**.

---

## References

- Hart, S. G., & Staveland, L. E. (1988). *Development of NASA-TLX
  (Task Load Index): Results of empirical and theoretical research.*
  In P. A. Hancock & N. Meshkati (Eds.), Human mental workload
  (pp. 139-183). North-Holland.
- Hart, S. G. (2006). *NASA-Task Load Index (NASA-TLX); 20 years
  later.* Proceedings of the Human Factors and Ergonomics Society
  Annual Meeting, 50(9), 904-908.
- Grier, R. A. (2015). *How High Is High? A Meta-Analysis of NASA-TLX
  Global Workload Scores.* Proceedings of the Human Factors and
  Ergonomics Society Annual Meeting, 59(1), 1727-1731.
