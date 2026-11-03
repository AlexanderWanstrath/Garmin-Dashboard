"""Aerobic decoupling (Pa:HR) from per-second samples.

The run (after the warm-up) is split into two halves of equal moving time. For each
half EF = mean speed / mean heart rate; decoupling = (EF_1 - EF_2) / EF_1 * 100 %.
Below about 5 % counts as a solid aerobic base.
"""

from __future__ import annotations

from runlog.metrics import Row, mean

MIN_SPEED = 0.5  # m/s; slower samples count as standing (pauses, traffic lights)
MIN_MOVING_S = 20 * 60  # shorter runs give no meaningful halves


def decoupling_pct(samples: list[Row], warmup_s: float = 0) -> float | None:
    moving = [
        s
        for s in samples
        if s.get("t_offset_s", 0) >= warmup_s and s.get("hr") and s.get("speed") is not None and s["speed"] >= MIN_SPEED
    ]
    if len(moving) < MIN_MOVING_S:
        return None
    half = len(moving) // 2
    ef1 = efficiency(moving[:half])
    ef2 = efficiency(moving[half:])
    if not ef1 or ef2 is None:
        return None
    return round((ef1 - ef2) / ef1 * 100, 1)


def efficiency(samples: list[Row]) -> float | None:
    speed = mean([s["speed"] for s in samples])
    hr = mean([s["hr"] for s in samples])
    return speed / hr if speed is not None and hr else None
