from __future__ import annotations

"""Deterministic process-simulation KPI model for the agentic optimization loop.

The goal-seeking loop needs to evaluate many AGV-count candidates *synchronously* within a
single chat turn. The live UE5 path delivers KPIs asynchronously, one run at a time, so it
cannot drive an in-turn search. This module provides a deterministic, reproducible KPI model
keyed on AGV count so the agent can observe → judge → decide → re-run without a UE5 round-trip
(demo prototype: speed over fidelity).

The bottleneck rate is intentionally *derived from a congestion heatmap grid* — the same
hot-fraction calculation used by ``evaluation._heatmap_stats`` and mirroring the UE5
``UCongestionHeatmapComponent`` density grid — rather than returned as a free-standing number,
so "bottleneck rate" stays grounded in the heatmap the rest of the system already speaks.
"""

from typing import Any

# Heat grid resolution. res_x matches the default assumed by evaluation._heatmap_stats.
HEATMAP_RES_X = 24
HEATMAP_RES_Y = 16
_TOTAL_CELLS = HEATMAP_RES_X * HEATMAP_RES_Y

# A cell counts as "hot" (bottlenecked) at >= 60% of peak density — same threshold as
# evaluation._heatmap_stats hot_fraction. Hot cells are deposited at peak; the rest sit at a
# background level below the hot cutoff so they are never miscounted.
_HOT_CUTOFF = 0.6
_PEAK_DENSITY = 1.0
_BACKGROUND_DENSITY = 0.12


def _congested_fraction(agv_count: int) -> float:
    """Target fraction of the floor that is congested, as a function of AGV count.

    Monotonically increasing and slightly super-linear: more AGVs contend for the same
    intersections, so queues spill across more cells. Calibrated so the rate crosses the
    demo's 30% goal between 2 and 3 AGVs (n=1≈0.13, n=2≈0.24, n=3≈0.39).
    """
    n = max(0, agv_count)
    return min(0.95, 0.06 + 0.05 * n + 0.02 * n * n)


def build_congestion_heatmap(agv_count: int) -> tuple[list[float], int, int]:
    """Build a deterministic heat grid whose congestion grows with AGV count.

    Hot cells are placed as a contiguous cluster around the cell centre (a stand-in for the
    central intersection), which is where AGV congestion concentrates, so the grid also reads
    sensibly through evaluation._heatmap_stats (peak/mean concentration, hotspot location).
    """
    grid = [_BACKGROUND_DENSITY] * _TOTAL_CELLS
    hot_cells = round(_congested_fraction(agv_count) * _TOTAL_CELLS)
    if hot_cells <= 0:
        return grid, HEATMAP_RES_X, HEATMAP_RES_Y

    center_x = (HEATMAP_RES_X - 1) / 2.0
    center_y = (HEATMAP_RES_Y - 1) / 2.0
    by_distance = sorted(
        range(_TOTAL_CELLS),
        key=lambda i: (i % HEATMAP_RES_X - center_x) ** 2 + (i // HEATMAP_RES_X - center_y) ** 2,
    )
    for index in by_distance[:hot_cells]:
        grid[index] = _PEAK_DENSITY
    return grid, HEATMAP_RES_X, HEATMAP_RES_Y


def bottleneck_rate_from_heatmap(
    grid: list[float],
    res_x: int,
    res_y: int,
    traversed_grid: list[bool] | list[int] | list[float] | None = None,
) -> float:
    """Bottleneck rate (percent) = share of traversed heat cells at >= 60% of peak density.

    Single source of truth for the bottleneck metric. When UE5 provides a traversed/visited
    mask, the denominator excludes cells AGVs never entered. Without a mask, positive-density
    cells are treated as traversed so empty floor area does not dilute a concentrated hotspot.
    Returns 0.0 for an empty/flat grid.
    """
    cells = [float(v) for v in grid if isinstance(v, (int, float))]
    if not cells:
        return 0.0
    peak = max(cells)
    if peak <= 0:
        return 0.0
    if traversed_grid is not None:
        traversed = [
            index
            for index, flag in enumerate(traversed_grid[: len(cells)])
            if isinstance(flag, (bool, int, float)) and bool(flag)
        ]
    else:
        traversed = [index for index, value in enumerate(cells) if value > 0.0]
    if not traversed:
        return 0.0
    hot = sum(1 for index in traversed if cells[index] >= peak * _HOT_CUTOFF)
    return round(hot / len(traversed) * 100.0, 1)


def simulate_run_kpis(agv_count: int, speed_multiplier: float = 1.0) -> dict[str, Any]:
    """Deterministic KPI set for one run at the given AGV count.

    Returns the same KPI keys a real UE5 completion carries (so the evaluation / comparison /
    report paths treat an optimization candidate exactly like any other run), with
    ``bottleneck_rate`` derived from the embedded congestion heatmap.
    """
    n = max(1, int(agv_count))
    speed = speed_multiplier if speed_multiplier and speed_multiplier > 0 else 1.0

    grid, res_x, res_y = build_congestion_heatmap(n)
    bottleneck_rate = bottleneck_rate_from_heatmap(grid, res_x, res_y)

    # More AGVs lift throughput but congestion eats into the gain; wait time and collision risk
    # climb with contention; uptime dips slightly. All monotonic and demo-plausible.
    throughput = round(26.0 * n * (1.0 - 0.06 * n) * speed, 1)
    avg_wait_time = round(4.0 + 3.0 * n + 2.0 * n * n, 1)
    collision_risk = round(0.15 * n * n, 2)
    uptime = round(max(0.5, 0.98 - 0.03 * n), 2)

    return {
        "throughput": throughput,
        "avg_wait_time": avg_wait_time,
        "collision_risk": collision_risk,
        "uptime": uptime,
        "active_agvs": n,
        "bottleneck_rate": bottleneck_rate,
        "heatmap_grid": grid,
        "heatmap_res_x": res_x,
        "heatmap_res_y": res_y,
    }
