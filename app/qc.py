"""
Bikeshare dispatch quality control: the statistics, and nothing else.

No web framework here. The API only calls these functions and returns what they give.
Every formula below is written out in SPEC.md section 4, with hand-worked answers that
tests/test_qc.py reproduces.

Vocabulary
- reading: bikes docked at one station at one 15-minute time.
- net flow: change in bikes since the last reading minus what the van moved (riders only).
- x: net flow minus the station's usual (historical mean) net flow for that 15-minute slot.
- out of spec: bikes < LSL (4) or bikes > USL (16) at a 20-dock station.
"""

import math

D2 = 1.128          # d2 for moving ranges of 2 consecutive points
LSL, USL = 4, 16    # spec limits, bikes per 20-dock station (= spec_limits(20))
LOW_SHARE, HIGH_SHARE = 0.20, 0.80   # spec limits as a share of docks, for any station size
VAN_MAX = 10        # most bikes the van moves in one stop

RULE_NAMES = {
    1: "1 point beyond 3 sigma",
    2: "2 of 3 beyond 2 sigma",
    3: "4 of 5 beyond 1 sigma",
    4: "8 in a row on one side",
}


def _round_half_up(v):
    return int(math.floor(v + 0.5))


# ---- I-MR chart ------------------------------------------------------------

def imr_limits(x):
    """Individuals and moving-range limits for one series.

    sigma = MR-bar / d2; limits x-bar +/- 3 sigma (= +/- 2.66 MR-bar); MR UCL = 3.267 MR-bar.
    """
    return imr_limits_days([list(x)])


def imr_limits_days(days):
    """I-MR limits from several days of x. Moving ranges never cross from one day to the next."""
    days = [list(d) for d in days]
    values = [v for d in days for v in d]
    if any(v is None or (isinstance(v, float) and math.isnan(v)) for v in values):
        raise ValueError("x has missing values; drop or fill them first")
    mrs = [abs(d[i] - d[i - 1]) for d in days for i in range(1, len(d))]
    if len(values) < 2 or not mrs:
        raise ValueError("an I-MR chart needs at least 2 consecutive values")
    xbar = sum(values) / len(values)
    mrbar = sum(mrs) / len(mrs)
    sigma = mrbar / D2
    out = {
        "xbar": xbar, "mrbar": mrbar, "sigma": sigma,
        "ucl": xbar + 2.66 * mrbar, "lcl": xbar - 2.66 * mrbar, "mr_ucl": 3.267 * mrbar,
        "message": "",
    }
    if mrbar == 0:
        out.update(ucl=None, lcl=None, mr_ucl=None,
                   message="no variation (all moving ranges are 0): sigma is 0, so there are no limits "
                           "and run rules cannot be applied")
    return out


def clean_baseline(flows, max_passes=10):
    """Slot means and I-MR limits from several days of rider net flow, with the course's revised
    limits: readings beyond 3 sigma are removed and everything is recomputed until none remain.

    flows: one list per day, one value per slot (index 0 may be None: no flow into the first reading).
    mu_k = mean of the kept flows at slot k (all of them if none is kept there); x = f - mu;
    x-bar, MR-bar and sigma = MR-bar / d2 come from the kept x, with moving ranges only between
    consecutive kept readings of the same day. Returns {"mu", "imr", "removed", "passes"}.
    """
    S = max(len(f) for f in flows)
    keep = [[f[k] is not None for k in range(len(f))] for f in flows]
    removed = 0
    for passes in range(1, max_passes + 1):
        mu = []
        for k in range(S):
            kept = [f[k] for f, m in zip(flows, keep) if k < len(f) and m[k]]
            every = [f[k] for f in flows if k < len(f) and f[k] is not None]
            vals = kept or every
            mu.append(sum(vals) / len(vals) if vals else 0.0)
        runs = []                                    # unbroken runs of kept x, so MR never jumps a gap
        for f, m in zip(flows, keep):
            cur = []
            for k, v in enumerate(f):
                if m[k]:
                    cur.append(v - mu[k])
                elif cur:
                    runs.append(cur)
                    cur = []
            if cur:
                runs.append(cur)
        imr = imr_limits_days(runs)
        if not imr["sigma"]:
            break
        drop = 0
        for f, m in zip(flows, keep):
            for k, v in enumerate(f):
                if m[k] and abs(v - mu[k] - imr["xbar"]) > 3 * imr["sigma"]:
                    m[k] = False
                    drop += 1
        removed += drop
        if not drop:
            break
    return {"mu": mu, "imr": imr, "removed": removed, "passes": passes}


def run_rules(x, xbar, sigma):
    """Western Electric rules 1-4 on the latest point of x (all on the same side of x-bar).

    1: the point is beyond 3 sigma; 2: 2 of the last 3 beyond 2 sigma; 3: 4 of the last 5
    beyond 1 sigma; 4: the last 8 on one side. As in Montgomery (section 5.3), rules 2 and 3 need
    the latest point itself to be one of the points beyond the zone, so a rule fires on the
    point that completes the pattern and not afterwards. Returns {"rule", "side", "name"} for the first
    rule that fires (side -1 = below x-bar: draining faster than usual; +1 = filling), or None.
    """
    if not sigma or sigma <= 0:
        raise ValueError("sigma must be positive to apply run rules")
    x = list(x)
    if not x:
        return None
    if any(v is None or (isinstance(v, float) and math.isnan(v)) for v in x):
        raise ValueError("x has missing values; drop or fill them first")
    z = [(v - xbar) / sigma for v in x]
    last = z[-1]
    if abs(last) > 3:
        return _sig(1, 1 if last > 0 else -1)
    for side in (1, -1):
        t3, t5, t8 = z[-3:], z[-5:], z[-8:]
        if len(t3) == 3 and sum(v * side > 2 for v in t3) >= 2 and last * side > 2:
            return _sig(2, side)
        if len(t5) == 5 and sum(v * side > 1 for v in t5) >= 4 and last * side > 1:
            return _sig(3, side)
        if len(t8) == 8 and all(v * side > 0 for v in t8):
            return _sig(4, side)
    return None


def _sig(rule, side):
    return {"rule": rule, "side": side, "name": RULE_NAMES[rule]}


# ---- dispatch --------------------------------------------------------------

def spec_limits(capacity, low=LOW_SHARE, high=HIGH_SHARE):
    """Spec limits in bikes for a station: below LSL it is nearly empty, above USL nearly full.

    LSL = round(low x capacity), USL = round(high x capacity), halves rounded up.
    20 docks -> (4, 16); 12 docks -> (2, 10); 31 docks -> (6, 25).
    """
    if not isinstance(capacity, int) or capacity <= 0:
        raise ValueError(f"capacity must be a positive whole number of docks (got {capacity})")
    if not 0 <= low < high <= 1:
        raise ValueError("need 0 <= low share < high share <= 1")
    return _round_half_up(low * capacity), _round_half_up(high * capacity)


def out_of_spec(bikes, lsl=LSL, usl=USL):
    return bikes < lsl or bikes > usl


def dispatch_trigger(signal, bikes, lsl=LSL, usl=USL):
    """Why the van should go, or None: a chart signal first, else out of spec (the safety net)."""
    if signal:
        return f"rule {signal['rule']}"
    if out_of_spec(bikes, lsl, usl):
        return "out of spec"
    return None


def van_move(expected, bikes, capacity, max_move=VAN_MAX):
    """Bikes to move to put a station back on its expected path.

    + = bring bikes, - = take bikes. At most max_move, and never below 0 or above capacity.
    """
    if not (0 <= bikes <= capacity):
        raise ValueError(f"bikes {bikes} is outside 0..{capacity}")
    move = _round_half_up(expected - bikes)
    move = max(-max_move, min(max_move, move))
    return max(-bikes, min(capacity - bikes, move))


def van_priority(candidates):
    """Order stations that need the van: furthest from the expected path first.

    candidates: list of (station_id, expected, bikes). Returns the station ids in order.
    """
    return [c[0] for c in sorted(candidates, key=lambda c: (-abs(c[1] - c[2]), c[0]))]


# ---- night plan ------------------------------------------------------------

def start_plan(C, lsl=LSL, usl=USL):
    """Tomorrow's 06:00 start from the cumulative usual net flow C (C[0] = 0).

    Allowed starts keep lsl <= s + C[k] <= usl for every k: s from lsl - min C to usl - max C.
    The plan is the middle of that range, rounded; the expected path is s + C[k].
    """
    C = list(C)
    if not C:
        raise ValueError("C is empty")
    lo, hi = lsl - min(C), usl - max(C)
    if lo > hi:
        return {"start": None, "feasible": False, "lo": lo, "hi": hi, "path": None,
                "message": f"normal swing {max(C) - min(C):g} is wider than {usl - lsl}: no start keeps the "
                           "station in spec all day; it needs a planned visit"}
    s = _round_half_up((lo + hi) / 2)
    return {"start": s, "feasible": True, "lo": lo, "hi": hi, "path": [s + c for c in C], "message": ""}


def rush_slots(means, factor=1.5):
    """0-based indexes of slots whose mean rentals are at least factor x the mean of all slots."""
    means = list(means)
    if not means:
        raise ValueError("no slots")
    avg = sum(means) / len(means)
    if avg == 0:
        return []
    return [i for i, m in enumerate(means) if m >= factor * avg]


# ---- weekly review ---------------------------------------------------------

def p_chart_phase(d_phase1, d_phase2, n):
    """p-chart, one point per day: Phase I days set the limits, Phase II days are judged.

    pbar = sum(d1) / (n * days1); limits pbar +/- 3 sqrt(pbar (1 - pbar) / n), LCL >= 0.
    Each day is "in control", "worse" (above UCL) or "improved" (below LCL).
    """
    d1, d2 = list(d_phase1), list(d_phase2)
    if n <= 0:
        raise ValueError("n must be positive")
    if len(d1) < 2:
        raise ValueError("Phase I needs at least 2 days")
    if any(d < 0 or d > n for d in d1 + d2):
        raise ValueError("each day's count must be between 0 and n")
    pbar = sum(d1) / (n * len(d1))
    s = math.sqrt(pbar * (1 - pbar) / n)
    ucl, lcl = pbar + 3 * s, max(0.0, pbar - 3 * s)

    flat = pbar in (0.0, 1.0)

    def judge(d):
        p = d / n
        if flat:
            return {"d": d, "p": p, "status": "no Phase I variation"}
        return {"d": d, "p": p, "status": "worse" if p > ucl else "improved" if p < lcl else "in control"}

    warnings = []
    if flat:
        warnings.append("no variation in Phase I: the limits equal the centre line, so days are not judged")
    elif n * pbar < 5 or n * (1 - pbar) < 5:
        warnings.append(f"n*pbar = {n * pbar:.1f}, n*(1-pbar) = {n * (1 - pbar):.1f}: below 5 the limits are rough")
    return {"pbar": pbar, "sigma": s, "ucl": ucl, "lcl": lcl,
            "phase1": [judge(d) for d in d1], "phase2": [judge(d) for d in d2], "warnings": warnings}
