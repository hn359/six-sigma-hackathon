"""Statistical Process Control (SPC) and Six Sigma (DMAIC) analytics module.

Implements Six Sigma process capability calculations (Cp, Cpk, Cpm, DPMO, Sigma Level),
Individual and Moving Range (I-MR) control charts, Shewhart control limits (UCL=18, LCL=2),
Nelson rule violations, and structured DMAIC reporting for the municipal bikeshare network.
"""
from __future__ import annotations

import math
from typing import Any


def calculate_station_spc(
    records: list[dict[str, Any]],
    capacity: int = 20,
    target: float = 10.0,
    ucl_spec: float = 18.0,
    lcl_spec: float = 2.0,
    low_warning: float = 5.0,
    high_warning: float = 15.0,
) -> dict[str, Any]:
    """Compute comprehensive Six Sigma and SPC metrics including I-MR chart parameters.

    - Upper Control Limit (UCL) = 18 (approaching full, 2 docks left)
    - Lower Control Limit (LCL) = 2 (approaching empty, 2 bikes left)
    - Target = 10 (nominal balanced 50% capacity)
    """
    if not records:
        return {
            "sample_size": 0,
            "mean": 0.0,
            "std_dev": 0.0,
            "min_bikes": 0,
            "max_bikes": 0,
            "target": target,
            "usl": float(capacity),
            "lsl": 0.0,
            "ucl": ucl_spec,
            "lcl": lcl_spec,
            "uwl": high_warning,
            "lwl": low_warning,
            "cp": 0.0,
            "cpk": 0.0,
            "cpm": 0.0,
            "sigma_level": 0.0,
            "total_defects": 0,
            "total_opportunities": 0,
            "dpmo": 0.0,
            "availability_pct": 100.0,
            "stockout_ticks": 0,
            "overflow_ticks": 0,
            "failed_rentals": 0,
            "failed_returns": 0,
            "special_cause_active": False,
            "special_cause_type": "NONE",
            "imr": {
                "individual": [],
                "moving_range": [],
                "moving_average": [],
                "mr_mean": 0.0,
                "mr_ucl": 0.0,
                "mr_lcl": 0.0,
            },
            "nelson_violations": [],
            "status": "INSUFFICIENT_DATA",
        }

    bikes_series = [float(r.get("bikes", 10)) for r in records]
    n = len(bikes_series)
    mean_val = sum(bikes_series) / n

    if n > 1:
        variance = sum((x - mean_val) ** 2 for x in bikes_series) / (n - 1)
        std_val = math.sqrt(variance)
    else:
        variance = 0.0
        std_val = 0.0

    usl = float(capacity)
    lsl = 0.0

    # Moving Range (MR) and Moving Average (MA) calculations
    moving_ranges: list[float] = [0.0]
    for i in range(1, n):
        moving_ranges.append(round(abs(bikes_series[i] - bikes_series[i - 1]), 2))

    mr_mean = (
        sum(moving_ranges[1:]) / max(1, n - 1)
        if n > 1
        else 0.0
    )
    # For n=2 sample size in Moving Range, D4 = 3.267
    mr_ucl = round(3.267 * mr_mean, 2)
    mr_lcl = 0.0

    # 5-point moving average
    moving_averages: list[float] = []
    window_size = min(5, n)
    for i in range(n):
        start_idx = max(0, i - window_size + 1)
        sub = bikes_series[start_idx : i + 1]
        moving_averages.append(round(sum(sub) / len(sub), 2))

    # Capability indices relative to spec limits
    if std_val > 1e-6:
        cp = (usl - lsl) / (6.0 * std_val)
        cpu = (usl - mean_val) / (3.0 * std_val)
        cpl = (mean_val - lsl) / (3.0 * std_val)
        cpk = max(-2.0, min(cpu, cpl))
        mean_deviation_sq = (mean_val - target) ** 2
        cpm = (usl - lsl) / (6.0 * math.sqrt(variance + mean_deviation_sq))
        sigma_level = max(0.0, round(3.0 * cpk, 2))
    else:
        cp = 99.0
        cpk = 99.0 if lsl <= mean_val <= usl else -1.0
        cpm = 99.0
        sigma_level = 6.0

    # Control Limits: UCL=18, LCL=2 (as specified by user requirements)
    ucl = ucl_spec
    lcl = lcl_spec

    # Defect and opportunity accounting
    stockout_ticks = sum(1 for b in bikes_series if b <= lcl)
    overflow_ticks = sum(1 for b in bikes_series if b >= ucl)
    unusable_ticks = sum(1 for b in bikes_series if b <= 0.0 or b >= usl)

    latest = records[-1]
    failed_rentals = int(latest.get("failed_rentals", 0))
    failed_returns = int(latest.get("failed_returns", 0))
    rentals = int(latest.get("rentals", 0))
    returns = int(latest.get("returns", 0))

    special_cause_active = bool(latest.get("special_cause_active", False))
    special_cause_type = str(latest.get("special_cause_type", "NONE"))

    # Opportunities: 2 checks per tick (below LCL or above UCL) + rentals/returns
    total_opportunities = (2 * n) + rentals + returns + failed_rentals + failed_returns
    total_defects = unusable_ticks + failed_rentals + failed_returns
    dpmo = (total_defects / max(1, total_opportunities)) * 1_000_000.0
    availability_pct = round(100.0 * (n - unusable_ticks) / max(1, n), 2)

    # Evaluate Nelson Rules
    nelson_violations = evaluate_nelson_rules(bikes_series, mean_val, std_val, ucl, lcl)

    # Health status classification
    if special_cause_active or latest.get("bikes", 10) <= lcl or latest.get("bikes", 10) >= ucl:
        health = "CRITICAL_SPECIAL_CAUSE"
    elif cpk < 1.0 or any(v["rule"] in (2, 3) for v in nelson_violations):
        health = "WARNING"
    else:
        health = "IN_CONTROL"

    return {
        "sample_size": n,
        "mean": round(mean_val, 2),
        "std_dev": round(std_val, 2),
        "min_bikes": int(min(bikes_series)),
        "max_bikes": int(max(bikes_series)),
        "target": target,
        "usl": usl,
        "lsl": lsl,
        "ucl": ucl,
        "lcl": lcl,
        "uwl": high_warning,
        "lwl": low_warning,
        "cp": round(cp, 3),
        "cpk": round(cpk, 3),
        "cpm": round(cpm, 3),
        "sigma_level": sigma_level,
        "total_defects": total_defects,
        "total_opportunities": total_opportunities,
        "dpmo": round(dpmo, 1),
        "availability_pct": availability_pct,
        "stockout_ticks": stockout_ticks,
        "overflow_ticks": overflow_ticks,
        "failed_rentals": failed_rentals,
        "failed_returns": failed_returns,
        "special_cause_active": special_cause_active,
        "special_cause_type": special_cause_type,
        "imr": {
            "individual": bikes_series,
            "moving_range": moving_ranges,
            "moving_average": moving_averages,
            "mr_mean": round(mr_mean, 2),
            "mr_ucl": mr_ucl,
            "mr_lcl": mr_lcl,
        },
        "nelson_violations": nelson_violations,
        "status": health,
    }


def evaluate_nelson_rules(
    series: list[float],
    mean: float,
    std: float,
    ucl: float = 18.0,
    lcl: float = 2.0,
) -> list[dict[str, Any]]:
    """Evaluate standard Statistical Process Control (Nelson / WECO) rules."""
    violations: list[dict[str, Any]] = []
    if len(series) < 3:
        return violations

    n = len(series)

    # Rule 1: Point beyond control limits (UCL=18, LCL=2) - Immediate Special Cause
    for idx, val in enumerate(series):
        if val > ucl or val < lcl:
            violations.append({
                "rule": 1,
                "description": f"Rule 1: Point beyond control limits (Val={val}, UCL={ucl}, LCL={lcl})",
                "tick_index": idx,
                "value": val,
                "type": "SPECIAL_CAUSE",
            })

    # Rule 2: Nine consecutive points on same side of center line (Process Shift / Run)
    if n >= 9:
        for idx in range(8, n):
            window = series[idx - 8 : idx + 1]
            if all(v > mean for v in window):
                violations.append({
                    "rule": 2,
                    "description": "Rule 2: Nine points in a row above center line (Persistent Surplus)",
                    "tick_index": idx,
                    "value": series[idx],
                    "type": "RUN_SHIFT",
                })
            elif all(v < mean for v in window):
                violations.append({
                    "rule": 2,
                    "description": "Rule 2: Nine points in a row below center line (Persistent Deficit)",
                    "tick_index": idx,
                    "value": series[idx],
                    "type": "RUN_SHIFT",
                })

    # Rule 3: Six consecutive points steadily increasing or decreasing (Trend)
    if n >= 6:
        for idx in range(5, n):
            window = series[idx - 5 : idx + 1]
            if all(window[i] > window[i - 1] for i in range(1, 6)):
                violations.append({
                    "rule": 3,
                    "description": "Rule 3: Six consecutive points increasing (Accumulation Trend)",
                    "tick_index": idx,
                    "value": series[idx],
                    "type": "TREND",
                })
            elif all(window[i] < window[i - 1] for i in range(1, 6)):
                violations.append({
                    "rule": 3,
                    "description": "Rule 3: Six consecutive points decreasing (Depletion Trend)",
                    "tick_index": idx,
                    "value": series[idx],
                    "type": "TREND",
                })

    return violations


def calculate_p_chart(
    snapshots: list[dict[str, Any]],
    n_stations: int = 5,
    ucl_spec: float = 18.0,
    lcl_spec: float = 2.0,
) -> dict[str, Any]:
    """Calculate Attribute Control Chart (Fraction Defective p-Chart & np-Chart).

    Based on Cornell SYSEN 5300 Lesson 5: Control Charts (Slides 25 & 41-46).
    Evaluates the fraction of bikeshare stations non-conforming / unusable (bikes <= 2 or bikes >= 18)
    across each 15-minute sampling interval under binomial distribution assumptions:
      p_i = x_i / n_i
      Centerline (p_bar) = (Total Defective Stations) / (Total Station Checks)
      Control Limits = p_bar +/- 3 * sqrt(p_bar * (1 - p_bar) / n)
    """
    if not snapshots:
        return {
            "ticks": [],
            "p_values": [],
            "np_values": [],
            "sample_sizes": [],
            "p_bar": 0.0,
            "ucl_p": 0.0,
            "lcl_p": 0.0,
            "np_bar": 0.0,
            "np_ucl": 0.0,
            "np_lcl": 0.0,
            "out_of_control_ticks": [],
            "formula": "p_bar +/- 3 * sqrt(p_bar * (1 - p_bar) / n)",
            "citation": "SYSEN 5300 Lesson 5 (Slides 25 & 41-46)",
        }

    # Group snapshots by tick number
    by_tick: dict[int, list[dict[str, Any]]] = {}
    for row in snapshots:
        t = int(row.get("tick", 0))
        by_tick.setdefault(t, []).append(row)

    sorted_ticks = sorted(by_tick.keys())
    ticks_list: list[int] = []
    p_values: list[float] = []
    np_values: list[int] = []
    sample_sizes: list[int] = []
    total_defective = 0
    total_inspected = 0

    for t in sorted_ticks:
        stations_at_tick = by_tick[t]
        n_t = len(stations_at_tick) if len(stations_at_tick) > 0 else n_stations
        # Defective station: out of control limits (<= 2 or >= 18) or marked special cause
        defective_count = sum(
            1
            for s in stations_at_tick
            if float(s.get("bikes", 10)) <= lcl_spec
            or float(s.get("bikes", 10)) >= ucl_spec
            or bool(s.get("special_cause_active", False))
        )
        p_t = defective_count / max(1, n_t)

        ticks_list.append(t)
        p_values.append(round(p_t, 4))
        np_values.append(defective_count)
        sample_sizes.append(n_t)
        total_defective += defective_count
        total_inspected += n_t

    # Global centerline p_bar
    p_bar = total_defective / max(1, total_inspected)

    # 3-sigma Binomial standard error for n=5
    n_nom = n_stations
    if 0.0 < p_bar < 1.0:
        se_p = math.sqrt(p_bar * (1.0 - p_bar) / n_nom)
    else:
        se_p = 0.0

    ucl_p = min(1.0, round(p_bar + 3.0 * se_p, 4))
    lcl_p = max(0.0, round(p_bar - 3.0 * se_p, 4))

    # np-chart parameters
    np_bar = round(n_nom * p_bar, 3)
    se_np = math.sqrt(n_nom * p_bar * (1.0 - p_bar)) if 0.0 < p_bar < 1.0 else 0.0
    np_ucl = min(float(n_nom), round(np_bar + 3.0 * se_np, 3))
    np_lcl = max(0.0, round(np_bar - 3.0 * se_np, 3))

    # Out of control ticks
    out_of_control = [
        {"tick": t, "p": p, "np": np_val, "ucl_p": ucl_p}
        for t, p, np_val in zip(ticks_list, p_values, np_values)
        if p > ucl_p
    ]

    return {
        "ticks": ticks_list,
        "p_values": p_values,
        "np_values": np_values,
        "sample_sizes": sample_sizes,
        "p_bar": round(p_bar, 4),
        "ucl_p": ucl_p,
        "lcl_p": lcl_p,
        "np_bar": np_bar,
        "np_ucl": np_ucl,
        "np_lcl": np_lcl,
        "total_intervals": len(sorted_ticks),
        "total_defective_station_ticks": total_defective,
        "total_station_audits": total_inspected,
        "out_of_control_ticks": out_of_control,
        "out_of_control_count": len(out_of_control),
        "formula": "p_bar +/- 3 * sqrt(p_bar * (1 - p_bar) / n)",
        "citation": "Cornell SYSEN 5300 Lesson 5 (Slides 25 & 41-46): Fraction Defective (p) Chart",
    }


def generate_dmaic_report(
    station_records: dict[str, list[dict[str, Any]]],
    station_meta: dict[str, dict[str, Any]],
    reserve_inventory: int = 50,
    fleet_size: int = 100,
) -> dict[str, Any]:
    """Compile structured DMAIC (Define-Measure-Analyze-Improve-Control) report."""
    station_spc: dict[str, dict[str, Any]] = {}
    total_defects = 0
    total_opportunities = 0
    total_ticks = 0
    active_special_causes: list[dict[str, Any]] = []

    for sid, records in station_records.items():
        spc = calculate_station_spc(records)
        station_spc[sid] = spc
        total_defects += spc["total_defects"]
        total_opportunities += spc["total_opportunities"]
        total_ticks = max(total_ticks, spc["sample_size"])

        if spc.get("special_cause_active") or (records and (records[-1].get("bikes", 10) <= 2 or records[-1].get("bikes", 10) >= 18)):
            active_special_causes.append({
                "station_id": sid,
                "name": station_meta.get(sid, {}).get("name", sid),
                "type": spc.get("special_cause_type", "DEFICIT" if records[-1].get("bikes", 10) <= 2 else "SURPLUS"),
                "bikes": records[-1].get("bikes", 10) if records else 10,
                "remedy_required": True,
            })

    sys_dpmo = (total_defects / max(1, total_opportunities)) * 1_000_000.0
    avg_cpk = (
        sum(s["cpk"] for s in station_spc.values()) / max(1, len(station_spc))
        if station_spc
        else 0.0
    )
    system_availability = (
        sum(s["availability_pct"] for s in station_spc.values())
        / max(1, len(station_spc))
        if station_spc
        else 100.0
    )

    pareto = sorted(
        [
            {
                "station_id": sid,
                "name": station_meta.get(sid, {}).get("name", sid),
                "zone": station_meta.get(sid, {}).get("zone", "mixed"),
                "defects": spc["total_defects"],
                "stockouts": spc["stockout_ticks"],
                "overflows": spc["overflow_ticks"],
                "cpk": spc["cpk"],
                "status": spc["status"],
            }
            for sid, spc in station_spc.items()
        ],
        key=lambda x: x["defects"],
        reverse=True,
    )

    all_snapshots = [row for rows in station_records.values() for row in rows]
    p_chart_data = calculate_p_chart(all_snapshots, n_stations=max(1, len(station_records)))

    return {
        "define": {
            "project_title": "Ithaca Bikeshare Fleet Reliability & Dock Crisis Mitigation",
            "business_case": "Mitigate rush-hour docks full/empty crisis using data-driven SPC and targeted van dispatch.",
            "fleet_size": fleet_size,
            "reserve_inventory": reserve_inventory,
            "control_limits": {"lcl": 2, "ucl": 18, "nominal_target": 10},
            "spec_limits": {"lsl": 0, "usl": 20},
            "warning_limits": {"low": 5, "high": 15},
            "critical_to_quality_targets": {
                "min_cpk": 1.33,
                "min_availability_pct": 95.0,
                "max_dpmo": 3400.0,
            },
        },
        "measure": {
            "total_intervals_evaluated": total_ticks,
            "system_dpmo": round(sys_dpmo, 1),
            "system_mean_cpk": round(avg_cpk, 3),
            "system_availability_pct": round(system_availability, 2),
            "station_metrics": station_spc,
            "p_chart_summary": {
                "p_bar": p_chart_data["p_bar"],
                "ucl_p": p_chart_data["ucl_p"],
                "lcl_p": p_chart_data["lcl_p"],
                "np_bar": p_chart_data["np_bar"],
                "np_ucl": p_chart_data["np_ucl"],
                "out_of_control_intervals": p_chart_data["out_of_control_count"],
                "citation": "SYSEN 5300 Lesson 5 Slide 25 & 41-46",
            },
        },
        "analyze": {
            "pareto_defect_ranking": pareto,
            "active_special_causes": active_special_causes,
            "rush_hour_vulnerabilities": {
                "morning_rush_06_10": "Residential stations (Lansing, Maplewood) experience rapid inventory drain toward working district.",
                "evening_rush_16_20": "Employment stations (Central Campus, North Campus) experience dock overflow as commuters return.",
                "overnight_quiescence_22_06": "Low volume after 10 PM creates opportunity for proportional overnight rebalancing.",
            },
        },
        "improve": {
            "rebalancing_strategy": "Maintenance van dispatch required for Special Cause recovery; preventive dispatch at warning thresholds (bikes < 5 or > 15).",
            "overnight_policy": "Proportional rebalance based on previous day's time-averaged occupancy.",
            "buffer_utilization": f"{reserve_inventory} central reserve bikes available for targeted injection.",
        },
        "control": {
            "control_method": "Individual & Moving Range (I-MR) charts (UCL=18, LCL=2) + Fraction Defective (p-Chart) based on Cornell SYSEN 5300 Lesson 5.",
            "p_chart_control_limits": {
                "centerline_p": p_chart_data["p_bar"],
                "ucl_p": p_chart_data["ucl_p"],
                "lcl_p": p_chart_data["lcl_p"],
            },
            "active_out_of_control_stations": [
                sid for sid, s in station_spc.items() if s["status"] in ("CRITICAL_SPECIAL_CAUSE", "OUT_OF_CONTROL")
            ],
            "action_thresholds": {
                "green_zone": "5 <= bikes <= 15 (Common cause variation — auto-correcting)",
                "yellow_zone": "2 < bikes < 5 or 15 < bikes < 18 (Warning buffer)",
                "red_zone": "bikes <= 2 or bikes >= 18 (Special Cause locked — operator command required)",
            },
        },
    }
