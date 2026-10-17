"""The statistic: a slot-adjusted Individuals and Moving Range (I-MR) chart with the eight tests for
special causes, as in the course (SYSEN 5300, lesson 5: https://timothyfraser.com/sigma/). Plain
lists in, plain numbers out; no web code, no dataset objects.

Bike flow swings every day (stations drain at the morning rush and refill in the evening), so each
reading is compared with what is usual for that 15-minute slot on comparable days, and the chart
is drawn on that difference:

  m_s      = mean of the measure at slot s over the baseline days        (the usual for that slot)
  e_t      = x_t - m_slot(t)                                             (the charted value)
  CL       = mean of the baseline e                                      (x-bar, the centre line)
  MR_t     = |e_t - e_(t-1)|, consecutive slots of the same day only
  sigma    = MR-bar / d2,  d2 = 1.128                                    (sigma_short, n = 2)
  UCL/LCL  = CL +/- 3 sigma  (= CL +/- 2.66 MR-bar)
  MR chart:  centre MR-bar, LCL 0, UCL = D4 * MR-bar, D4 = 3.267

Zones (each side of CL): C = within 1 sigma, B = 1 to 2 sigma, A = 2 to 3 sigma. The eight tests,
worded as in the course; a test fires on the point that completes it:
  rule1  one point beyond zone A                              (beyond 3 sigma)
  rule2  two out of three points in a row beyond zone B       (beyond 2 sigma, same side)
  rule3  four out of five points in a row beyond zone C       (beyond 1 sigma, same side)
  rule4  eight points in a row on the same side of the centre line
  rule5  six points in a row steadily increasing or decreasing
  rule6  fifteen points in a row in zone C (above and below the centre line)
  rule7  eight points in a row on both sides of the centre line with none in zone C
  rule8  fourteen points in a row alternating up and down
  mr     a moving range above the MR chart's UCL
Runs never cross a missing reading or a day boundary.

sigma="sd" (sample standard deviation of the baseline e instead of MR-bar/d2) exists for values that
accumulate, like inventory, where MR-bar understates the spread; the dashboard's control chart is on
net flow, which uses the course's MR-bar/d2.
"""

from __future__ import annotations

import math
from statistics import mean
from typing import List, Optional, Sequence

D2 = 1.128
D4 = 3.267

ALL_RULES = ("rule1", "rule2", "rule3", "rule4", "rule5", "rule6", "rule7", "rule8", "mr")
RULE_TEXT = {
    "rule1": "Test 1: one point beyond zone A (beyond 3 sigma)",
    "rule2": "Test 2: two out of three points in a row beyond zone B (2 sigma), same side",
    "rule3": "Test 3: four out of five points in a row beyond zone C (1 sigma), same side",
    "rule4": "Test 4: eight points in a row on the same side of the centre line",
    "rule5": "Test 5: six points in a row steadily increasing or decreasing",
    "rule6": "Test 6: fifteen points in a row in zone C, above and below the centre line",
    "rule7": "Test 7: eight points in a row on both sides of the centre line with none in zone C",
    "rule8": "Test 8: fourteen points in a row alternating up and down",
    "mr": "Moving range above the MR chart's upper limit (a sudden jump)",
}

Day = Sequence[Optional[float]]     # one day's values, aligned by slot, None where missing


def slot_means(days: Sequence[Day], width: int) -> List[Optional[float]]:
    """Mean of each slot over the days that have a value there (None if none do)."""
    out = []
    for s in range(width):
        vals = [d[s] for d in days if s < len(d) and d[s] is not None]
        out.append(mean(vals) if vals else None)
    return out


def residuals(day: Day, means: Sequence[Optional[float]]) -> List[Optional[float]]:
    return [None if x is None or s >= len(means) or means[s] is None else x - means[s]
            for s, x in enumerate(day)]


def moving_ranges(res: Sequence[Optional[float]]) -> List[Optional[float]]:
    """|e_t - e_(t-1)|; None for the first slot and wherever either side is missing."""
    return [None] + [None if a is None or b is None else abs(b - a) for a, b in zip(res, res[1:])]


def clean_baseline(baseline: Sequence[Day], max_passes: int = 10) -> tuple:
    """The course's revised limits: compute slot means, CL and sigma = MR-bar / d2 from the baseline,
    remove readings beyond 3 sigma, and repeat until none remain. Returns (the baseline with the
    removed readings set to None, how many were removed). Same method as app/qc.py clean_baseline."""
    days = [list(d) for d in baseline]
    if not days:
        return days, 0
    width = max(len(d) for d in days)
    removed = 0
    for _ in range(max_passes):
        means = slot_means(days, width)
        res = [residuals(d, means) for d in days]
        vals = [e for r in res for e in r if e is not None]
        mrs = [m for r in res for m in moving_ranges(r) if m is not None]
        if len(vals) < 2 or not mrs:
            break
        cl, sig = mean(vals), mean(mrs) / D2
        if sig == 0:
            break
        drop = [(i, k) for i, r in enumerate(res) for k, e in enumerate(r) if e is not None and abs(e - cl) > 3 * sig]
        if not drop:
            break
        for i, k in drop:
            days[i][k] = None
        removed += len(drop)
    return days, removed


def tests_fired(z: Sequence[float]) -> List[str]:
    """Which of tests 1-8 the LAST point of a run completes. z: the run so far in sigma units from
    the centre line (no gaps), oldest first."""
    fired = []
    last = z[-1]
    side = (last > 0) - (last < 0)
    if abs(last) > 3:
        fired.append("rule1")
    if side and abs(last) > 2 and sum(1 for v in z[-3:] if v * side > 2) >= 2:
        fired.append("rule2")
    if side and abs(last) > 1 and sum(1 for v in z[-5:] if v * side > 1) >= 4:
        fired.append("rule3")
    if side and len(z) >= 8 and all(v * side > 0 for v in z[-8:]):
        fired.append("rule4")
    if len(z) >= 6:
        steps = [b - a for a, b in zip(z[-6:], z[-5:])]
        if all(d > 0 for d in steps) or all(d < 0 for d in steps):
            fired.append("rule5")
    if len(z) >= 15 and all(abs(v) < 1 for v in z[-15:]):
        fired.append("rule6")
    if len(z) >= 8 and all(abs(v) > 1 for v in z[-8:]) and any(v > 0 for v in z[-8:]) \
            and any(v < 0 for v in z[-8:]):
        fired.append("rule7")
    if len(z) >= 14:
        steps = [b - a for a, b in zip(z[-14:], z[-13:])]
        if all(d != 0 for d in steps) and all(a * b < 0 for a, b in zip(steps, steps[1:])):
            fired.append("rule8")
    return fired


def imr_slot_adjusted(baseline: Sequence[Day], chart: Sequence[Day], sigma: str = "mr",
                      rules: Sequence[str] = ALL_RULES) -> dict:
    """Limits from the baseline days, signals on the chart days.

    sigma: "mr" (MR-bar/d2, the course's sigma_short) or "sd" (sample standard deviation of the
    baseline residuals). rules: which signals to report, from ALL_RULES.

    Returns {"slot_means", "limits", "points", "warnings"}. limits is None (with a warning) when it
    cannot be estimated: fewer than 2 baseline days, no back-to-back readings, or no variation.
    Each point: day (index into chart), slot, x, expected (= m_s + CL), residual, z (sigma units
    from CL), mr, signals.
    """
    if sigma not in ("mr", "sd"):
        raise ValueError("sigma must be 'mr' or 'sd'")
    bad = [r for r in rules if r not in ALL_RULES]
    if bad:
        raise ValueError(f"unknown rule(s) {bad}; choose from {list(ALL_RULES)}")
    if not chart or all(v is None for d in chart for v in d):
        raise ValueError("no readings to chart")
    warnings = []
    width = max(len(d) for d in list(baseline) + list(chart))
    means = slot_means(baseline, width)

    limits = None
    base_res = [residuals(d, means) for d in baseline]
    base_vals = [e for d in base_res for e in d if e is not None]
    base_mrs = [m for d in base_res for m in moving_ranges(d) if m is not None]
    if len(baseline) < 2:
        warnings.append("fewer than 2 comparable baseline days: slot averages and control limits "
                        "cannot be estimated, so no special-cause signals are shown")
    elif not base_mrs:
        warnings.append("the baseline has no back-to-back readings, so no moving range: "
                        "control limits are undefined")
    else:
        cl, mr_bar = mean(base_vals), mean(base_mrs)
        sig = mr_bar / D2 if sigma == "mr" else (
            math.sqrt(sum((e - cl) ** 2 for e in base_vals) / (len(base_vals) - 1))
            if len(base_vals) > 1 else 0.0)
        if sig == 0:
            warnings.append("the baseline never varies from its slot averages: control limits are "
                            "undefined (not zero), so no signals are shown")
        else:
            limits = {"cl": cl, "sigma": sig, "sigma_basis": sigma,
                      "ucl": cl + 3 * sig, "lcl": cl - 3 * sig, "mr_bar": mr_bar,
                      "mr_ucl": D4 * mr_bar, "mr_lcl": 0.0,
                      "baseline_days": len(baseline), "baseline_points": len(base_vals)}

    points = []
    for di, day in enumerate(chart):
        res = residuals(day, means)
        mrs = moving_ranges(res)
        run: List[float] = []                    # z of the current unbroken run, this day
        for s, x in enumerate(day):
            if x is None:
                run = []
                continue
            e, mr = res[s], mrs[s]
            signals, z = [], None
            if limits is not None and e is not None:
                z = (e - limits["cl"]) / limits["sigma"]
                run.append(z)
                signals = [r for r in tests_fired(run) if r in rules]
                if "mr" in rules and mr is not None and mr > limits["mr_ucl"]:
                    signals.append("mr")
            else:
                run = []
            points.append({"day": di, "slot": s, "x": x,
                           "expected": None if means[s] is None else means[s] + (limits["cl"] if limits else 0.0),
                           "residual": e, "z": z, "mr": mr, "signals": signals})
    if any(p["residual"] is None for p in points):
        warnings.append("some slots have no baseline average, so those readings are shown without limits")
    return {"slot_means": means, "limits": limits, "points": points, "warnings": warnings}
