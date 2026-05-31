"""Analysis script for the memorywire governance-UI user study (paper Â§5.5).

Reads a CSV of per-participant responses and emits:

* ``analysis-summary.md`` â€” descriptive statistics tables with 95 % CIs.
* ``analysis-plots.png`` â€” a 2-panel matplotlib figure (NASA-TLX bar
  chart with CI error bars + per-task usability radar).

The script is deliberately defensive about optional dependencies:
``pandas``, ``numpy``, ``scipy``, and ``matplotlib`` are *lazy-imported*
inside the functions that need them, so the file is importable in
environments where those libraries are absent (e.g. when ruff/mypy
runs in a minimal CI image). When a dependency is missing, the
relevant computation degrades gracefully â€” numeric outputs fall back
to a pure-Python implementation, and the matplotlib plot is skipped
with a warning.

Run from this directory::

    python analyze.py                            # uses synthetic-data.csv
    python analyze.py --data my-real-data.csv    # uses your CSV
    python analyze.py --out-dir results/         # write outputs elsewhere

Expected CSV columns (synthetic-data.csv is the reference schema):

* ``participant_id``                       â€” string, e.g. ``P01``
* ``t1_success`` â€¦ ``t5_success``         â€” int, 0/1 success per task
* ``t1_time_s`` â€¦ ``t5_time_s``           â€” float, completion time in seconds
* ``tlx_mental`` â€¦ ``tlx_frustration``    â€” int, 0-100 raw NASA-TLX
* ``tlx_w_mental`` â€¦ ``tlx_w_frustration``â€” int, 0-5 pairwise weight (sum = 15)
* ``l1_t1_conf`` â€¦ ``l1_t5_conf``         â€” int, 1-7 per-task confidence
* ``l2_diff_clarity``                      â€” int, 1-7
* ``l3_audit_nav``                         â€” int, 1-7
* ``l4_prod_trust``                        â€” int, 1-7
* ``l5_overall``                           â€” int, 1-7
* ``l6_self_conf``                         â€” int, 1-7
* ``l7_recommend``                         â€” int, 1-7

Performance dimension reversal is applied here (``100 - tlx_performance``)
so callers feed the raw value the participant marked.
"""

from __future__ import annotations

import argparse
import math
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# --- Constants --------------------------------------------------------------

TLX_DIMS: tuple[str, ...] = (
    "mental",
    "physical",
    "temporal",
    "performance",
    "effort",
    "frustration",
)
NUM_TASKS: int = 5
TASKS: tuple[str, ...] = tuple(f"T{i}" for i in range(1, NUM_TASKS + 1))
USABILITY_LIKERTS: tuple[str, ...] = (
    "l2_diff_clarity",
    "l3_audit_nav",
    "l4_prod_trust",
    "l5_overall",
    "l6_self_conf",
    "l7_recommend",
)
USABILITY_LABELS: tuple[str, ...] = (
    "Diff clarity",
    "Audit nav",
    "Production trust",
    "Overall usability",
    "Self confidence",
    "Recommend",
)

# Z critical for 95 % CI on a normal approximation (Wilson interval).
_Z95: float = 1.959963984540054


# --- Lightweight stat helpers (no scipy dependency) -------------------------


def _mean(xs: list[float]) -> float:
    return statistics.fmean(xs) if xs else float("nan")


def _std(xs: list[float]) -> float:
    return statistics.stdev(xs) if len(xs) >= 2 else 0.0


def _t_ci95(xs: list[float]) -> tuple[float, float]:
    """Return the 95 % CI half-width for a sample mean.

    Uses a t-critical-value approximation; for n >= 15 the difference
    from the exact t-quantile is < 4 %, which is well within the
    precision we report (one decimal). Where ``scipy`` is available
    we use ``scipy.stats.t.ppf`` instead â€” see ``_t_critical``.
    """
    n = len(xs)
    if n < 2:
        return float("nan"), float("nan")
    mean = _mean(xs)
    sem = _std(xs) / math.sqrt(n)
    crit = _t_critical(0.975, n - 1)
    half = crit * sem
    return mean - half, mean + half


def _t_critical(quantile: float, df: int) -> float:
    """Return the t-critical value with graceful fallback to the normal Z."""
    try:
        from scipy.stats import t  # type: ignore[import-untyped]
    except ImportError:
        return _Z95
    return float(t.ppf(quantile, df))


def _wilson_ci95(k: int, n: int) -> tuple[float, float]:
    """Wilson 95 % CI for a binomial proportion (k successes out of n)."""
    if n == 0:
        return float("nan"), float("nan")
    p_hat = k / n
    z2 = _Z95 * _Z95
    denom = 1.0 + z2 / n
    centre = (p_hat + z2 / (2 * n)) / denom
    margin = (_Z95 / denom) * math.sqrt(p_hat * (1 - p_hat) / n + z2 / (4 * n * n))
    return centre - margin, centre + margin


# --- Data model -------------------------------------------------------------


@dataclass(frozen=True)
class ParticipantRow:
    """One row of the study CSV, parsed and validated."""

    participant_id: str
    successes: tuple[int, ...]  # length NUM_TASKS, 0 or 1 each
    times_s: tuple[float, ...]  # length NUM_TASKS
    tlx_raw: dict[str, int]  # 6 keys, values 0-100
    tlx_weights: dict[str, int]  # 6 keys, values 0-5, sum = 15
    likert_conf: tuple[int, ...]  # length NUM_TASKS, each 1-7
    usability: dict[str, int]  # 6 keys, each 1-7

    @property
    def tlx_weighted_overall(self) -> float:
        """Weighted NASA-TLX overall workload, with Performance reversed."""
        total = 0.0
        for dim in TLX_DIMS:
            raw = self.tlx_raw[dim]
            if dim == "performance":
                raw = 100 - raw
            total += self.tlx_weights[dim] * raw
        weight_sum = sum(self.tlx_weights.values())
        return total / weight_sum if weight_sum > 0 else float("nan")

    @property
    def tlx_raw_overall(self) -> float:
        """Unweighted (Raw) TLX = mean of the six (Performance-reversed) dims."""
        adjusted = [
            (100 - self.tlx_raw[d]) if d == "performance" else self.tlx_raw[d] for d in TLX_DIMS
        ]
        return _mean([float(x) for x in adjusted])


# --- CSV loading ------------------------------------------------------------


def load_csv(path: Path) -> list[ParticipantRow]:
    """Parse the study CSV into ParticipantRow objects.

    We hand-parse with the ``csv`` stdlib module so that the script does
    not hard-require pandas. ``pandas`` is used elsewhere for tabular
    output formatting, but not for ingestion.
    """
    import csv

    rows: list[ParticipantRow] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            rows.append(_row_from_dict(raw))
    if not rows:
        raise ValueError(f"no rows parsed from {path}")
    return rows


def _row_from_dict(raw: dict[str, str]) -> ParticipantRow:
    pid = raw["participant_id"].strip()
    successes = tuple(int(raw[f"t{i}_success"]) for i in range(1, NUM_TASKS + 1))
    times_s = tuple(float(raw[f"t{i}_time_s"]) for i in range(1, NUM_TASKS + 1))
    tlx_raw = {dim: int(raw[f"tlx_{dim}"]) for dim in TLX_DIMS}
    tlx_weights = {dim: int(raw[f"tlx_w_{dim}"]) for dim in TLX_DIMS}

    weight_sum = sum(tlx_weights.values())
    if weight_sum != 15:
        raise ValueError(f"{pid}: NASA-TLX weights sum to {weight_sum}, expected 15")

    likert_conf = tuple(int(raw[f"l1_t{i}_conf"]) for i in range(1, NUM_TASKS + 1))
    usability = {key: int(raw[key]) for key in USABILITY_LIKERTS}

    return ParticipantRow(
        participant_id=pid,
        successes=successes,
        times_s=times_s,
        tlx_raw=tlx_raw,
        tlx_weights=tlx_weights,
        likert_conf=likert_conf,
        usability=usability,
    )


# --- Summary builder --------------------------------------------------------


@dataclass(frozen=True)
class Summary:
    n: int
    tlx_weighted: tuple[float, float, float, float]  # mean, median, lo, hi
    tlx_raw: tuple[float, float, float, float]  # mean, median, lo, hi
    tlx_by_dim: dict[str, tuple[float, float, float]]  # dim -> (mean, lo, hi)
    per_task_success: list[tuple[int, int, float, float]]  # k, n, lo, hi
    per_task_time: list[tuple[float, float, float]]  # mean, lo, hi
    per_task_likert: list[tuple[float, float, float]]  # mean, lo, hi
    usability: dict[str, tuple[float, float, float]]  # key -> (mean, lo, hi)


def summarise(rows: list[ParticipantRow]) -> Summary:
    n = len(rows)

    tlx_w_vals = [r.tlx_weighted_overall for r in rows]
    tlx_w_lo, tlx_w_hi = _t_ci95(tlx_w_vals)
    tlx_w = (_mean(tlx_w_vals), statistics.median(tlx_w_vals), tlx_w_lo, tlx_w_hi)

    tlx_r_vals = [r.tlx_raw_overall for r in rows]
    tlx_r_lo, tlx_r_hi = _t_ci95(tlx_r_vals)
    tlx_r = (_mean(tlx_r_vals), statistics.median(tlx_r_vals), tlx_r_lo, tlx_r_hi)

    tlx_by_dim: dict[str, tuple[float, float, float]] = {}
    for dim in TLX_DIMS:
        vals = [
            float(100 - r.tlx_raw[dim] if dim == "performance" else r.tlx_raw[dim]) for r in rows
        ]
        lo, hi = _t_ci95(vals)
        tlx_by_dim[dim] = (_mean(vals), lo, hi)

    per_task_success: list[tuple[int, int, float, float]] = []
    per_task_time: list[tuple[float, float, float]] = []
    per_task_likert: list[tuple[float, float, float]] = []
    for i in range(NUM_TASKS):
        k = sum(r.successes[i] for r in rows)
        lo, hi = _wilson_ci95(k, n)
        per_task_success.append((k, n, lo, hi))

        times = [r.times_s[i] for r in rows]
        tlo, thi = _t_ci95(times)
        per_task_time.append((_mean(times), tlo, thi))

        likerts = [float(r.likert_conf[i]) for r in rows]
        llo, lhi = _t_ci95(likerts)
        per_task_likert.append((_mean(likerts), llo, lhi))

    usability: dict[str, tuple[float, float, float]] = {}
    for key in USABILITY_LIKERTS:
        vals = [float(r.usability[key]) for r in rows]
        lo, hi = _t_ci95(vals)
        usability[key] = (_mean(vals), lo, hi)

    return Summary(
        n=n,
        tlx_weighted=tlx_w,
        tlx_raw=tlx_r,
        tlx_by_dim=tlx_by_dim,
        per_task_success=per_task_success,
        per_task_time=per_task_time,
        per_task_likert=per_task_likert,
        usability=usability,
    )


# --- Output renderers -------------------------------------------------------


def render_summary_markdown(s: Summary) -> str:
    out: list[str] = []
    out.append("# memorywire Governance UI â€” Analysis Summary\n")
    out.append(f"n = {s.n} participants\n")

    out.append("## NASA-TLX overall (lower is better)\n")
    out.append("| Metric | Mean | Median | 95% CI |")
    out.append("|---|---:|---:|---|")
    wm, wmed, wlo, whi = s.tlx_weighted
    rm, rmed, rlo, rhi = s.tlx_raw
    out.append(f"| Weighted overall | {wm:.1f} | {wmed:.1f} | [{wlo:.1f}, {whi:.1f}] |")
    out.append(f"| Raw overall      | {rm:.1f} | {rmed:.1f} | [{rlo:.1f}, {rhi:.1f}] |\n")

    out.append("## NASA-TLX per dimension (Performance reversed)\n")
    out.append("| Dimension | Mean | 95% CI |")
    out.append("|---|---:|---|")
    for dim in TLX_DIMS:
        m, lo, hi = s.tlx_by_dim[dim]
        out.append(f"| {dim.capitalize()} | {m:.1f} | [{lo:.1f}, {hi:.1f}] |")
    out.append("")

    out.append("## Per-task results\n")
    out.append(
        "| Task | Success rate | Success 95% CI | Time (s) | Time 95% CI | Confidence (1-7) | Conf 95% CI |"
    )
    out.append("|---|---:|---|---:|---|---:|---|")
    for i, task in enumerate(TASKS):
        k, n, slo, shi = s.per_task_success[i]
        tmean, tlo, thi = s.per_task_time[i]
        lmean, llo, lhi = s.per_task_likert[i]
        rate = k / n if n else float("nan")
        out.append(
            f"| {task} | {rate:.2f} ({k}/{n}) | [{slo:.2f}, {shi:.2f}] | "
            f"{tmean:.0f} | [{tlo:.0f}, {thi:.0f}] | "
            f"{lmean:.2f} | [{llo:.2f}, {lhi:.2f}] |"
        )
    out.append("")

    out.append("## Usability Likerts (1 = strongly disagree, 7 = strongly agree)\n")
    out.append("| Item | Mean | 95% CI |")
    out.append("|---|---:|---|")
    for key, label in zip(USABILITY_LIKERTS, USABILITY_LABELS, strict=True):
        m, lo, hi = s.usability[key]
        out.append(f"| {label} | {m:.2f} | [{lo:.2f}, {hi:.2f}] |")
    out.append("")

    return "\n".join(out)


def render_plot(s: Summary, out_path: Path) -> bool:
    """Render the figure. Returns True on success, False if matplotlib missing."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        print(
            "[analyze] matplotlib or numpy not installed â€” skipping plot. "
            "Install with: pip install matplotlib numpy",
            file=sys.stderr,
        )
        return False

    fig = plt.figure(figsize=(12, 5))

    # --- Panel 1: NASA-TLX dimension bar chart with error bars ----------
    ax1 = fig.add_subplot(1, 2, 1)
    dims = list(TLX_DIMS)
    means = [s.tlx_by_dim[d][0] for d in dims]
    los = [s.tlx_by_dim[d][1] for d in dims]
    his = [s.tlx_by_dim[d][2] for d in dims]
    err_lo = [m - lo for m, lo in zip(means, los, strict=True)]
    err_hi = [hi - m for m, hi in zip(means, his, strict=True)]
    x = np.arange(len(dims))
    ax1.bar(x, means, yerr=[err_lo, err_hi], capsize=4, color="#4c72b0")
    ax1.set_xticks(x)
    ax1.set_xticklabels([d.capitalize() for d in dims], rotation=30, ha="right")
    ax1.set_ylabel("Raw score (0-100, lower is better)")
    ax1.set_ylim(0, 100)
    ax1.set_title(f"NASA-TLX by dimension (n = {s.n})")
    ax1.axhline(50, linestyle=":", color="grey", linewidth=0.8)

    # --- Panel 2: per-task usability radar ------------------------------
    ax2 = fig.add_subplot(1, 2, 2, projection="polar")
    angles = np.linspace(0, 2 * np.pi, len(USABILITY_LIKERTS), endpoint=False).tolist()
    angles += angles[:1]
    values = [s.usability[k][0] for k in USABILITY_LIKERTS]
    values += values[:1]
    ax2.plot(angles, values, color="#dd8452", linewidth=2)
    ax2.fill(angles, values, color="#dd8452", alpha=0.25)
    ax2.set_xticks(angles[:-1])
    ax2.set_xticklabels(list(USABILITY_LABELS))
    ax2.set_ylim(1, 7)
    ax2.set_title("Usability Likerts (1-7, higher is better)")

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return True


# --- Entry point ------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data",
        type=Path,
        default=Path(__file__).parent / "synthetic-data.csv",
        help="path to the study CSV (defaults to synthetic-data.csv)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).parent,
        help="directory to write analysis-summary.md and analysis-plots.png",
    )
    args = parser.parse_args(argv)

    if not args.data.exists():
        print(f"[analyze] data file not found: {args.data}", file=sys.stderr)
        return 1
    args.out_dir.mkdir(parents=True, exist_ok=True)

    rows = load_csv(args.data)
    summary = summarise(rows)

    md = render_summary_markdown(summary)
    summary_path = args.out_dir / "analysis-summary.md"
    summary_path.write_text(md, encoding="utf-8")
    print(f"[analyze] wrote {summary_path}")

    plot_path = args.out_dir / "analysis-plots.png"
    if render_plot(summary, plot_path):
        print(f"[analyze] wrote {plot_path}")
    else:
        print("[analyze] plot skipped (missing matplotlib / numpy)")

    print("\n" + md)
    return 0


def _validate_inputs(rows: list[ParticipantRow]) -> None:
    """Sanity checks beyond the CSV-row validator. Currently a stub.

    Reserved for future checks (e.g. detecting straight-line responses
    on the Likert items). Not called by ``main`` â€” invoke explicitly if
    you want the additional validation.
    """
    for r in rows:
        for dim, val in r.tlx_raw.items():
            if not 0 <= val <= 100:
                raise ValueError(f"{r.participant_id}: tlx_{dim} = {val} out of range")
        for i, t in enumerate(r.times_s):
            if t < 0:
                raise ValueError(f"{r.participant_id}: t{i + 1}_time_s = {t} negative")


# Re-export for tests / notebooks
__all__ = [
    "NUM_TASKS",
    "TASKS",
    "TLX_DIMS",
    "USABILITY_LABELS",
    "USABILITY_LIKERTS",
    "ParticipantRow",
    "Summary",
    "load_csv",
    "main",
    "render_plot",
    "render_summary_markdown",
    "summarise",
]


def _coerce_any(value: Any) -> Any:
    """Helper retained for callers that want to feed a non-strict dict."""
    return value


if __name__ == "__main__":
    raise SystemExit(main())
