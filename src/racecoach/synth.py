"""Deterministic synthetic laps used by the demo and the regression tests.

The generator is intentionally simple and transparent.  A lap is a distance
grid with piecewise-linear speed, brake and throttle channels.  Elapsed time is
integrated from speed.  Practice laps can shift the braking point, change the
minimum speed, add a measured time delta through a section, and punch a hole in
the data to exercise gap handling.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass

from .model import Lap, Sample


@dataclass(frozen=True)
class ZonePlan:
    brake_m: float
    apex_m: float
    release_m: float
    min_speed_kmh: float
    practice_brake_shift_m: float = 0.0  # positive means practice brakes earlier
    practice_min_speed_kmh: float | None = None
    practice_time_delta_s: float = 0.0
    practice_gap: tuple[float, float] | None = None


DEFAULT_ZONES = [
    ZonePlan(300, 360, 400, 90, practice_brake_shift_m=12, practice_min_speed_kmh=88, practice_time_delta_s=0.18),
    ZonePlan(700, 760, 800, 110),
    ZonePlan(
        1150,
        1210,
        1250,
        80,
        practice_brake_shift_m=-8,
        practice_min_speed_kmh=81.5,
        practice_time_delta_s=-0.09,
    ),
    ZonePlan(
        1600,
        1660,
        1700,
        100,
        practice_gap=(1580, 1620),
    ),
    ZonePlan(
        2050,
        2110,
        2150,
        95,
        practice_brake_shift_m=20,
        practice_min_speed_kmh=92,
        practice_time_delta_s=0.25,
    ),
]


def _index_at_or_after(distances: list[float], value: float) -> int:
    idx = bisect_left(distances, value)
    return min(idx, len(distances) - 1)


def _speed_profile(
    distances: list[float],
    zones: list[ZonePlan],
    practice: bool,
    base_speed_kmh: float,
    accel_distance_m: float,
) -> list[float]:
    speed = [base_speed_kmh for _ in distances]
    for zone in zones:
        brake_m = zone.brake_m - (zone.practice_brake_shift_m if practice else 0.0)
        min_speed = (
            zone.practice_min_speed_kmh
            if practice and zone.practice_min_speed_kmh is not None
            else zone.min_speed_kmh
        )
        i0 = _index_at_or_after(distances, brake_m)
        i_apex = _index_at_or_after(distances, zone.apex_m)
        i_release = _index_at_or_after(distances, zone.release_m)
        start_speed = speed[i0]
        if i_apex > i0:
            for i in range(i0, i_apex + 1):
                frac = (distances[i] - brake_m) / max(zone.apex_m - brake_m, 1e-9)
                speed[i] = start_speed + (min_speed - start_speed) * frac
        for i in range(i_apex, i_release + 1):
            speed[i] = min(speed[i], min_speed)
        i_end = _index_at_or_after(distances, zone.release_m + accel_distance_m)
        for i in range(i_release, i_end + 1):
            frac = (distances[i] - zone.release_m) / max(accel_distance_m, 1e-9)
            target = min_speed + (base_speed_kmh - min_speed) * frac
            speed[i] = min(speed[i], max(target, min_speed))
    return speed


def _integrate_time(distances: list[float], speed_kmh: list[float]) -> list[float]:
    elapsed = [0.0]
    for i in range(1, len(distances)):
        step_m = distances[i] - distances[i - 1]
        avg_mps = max((speed_kmh[i - 1] + speed_kmh[i]) / 2.0 / 3.6, 0.1)
        elapsed.append(elapsed[-1] + step_m / avg_mps)
    return elapsed


def _apply_time_deltas(
    distances: list[float],
    elapsed: list[float],
    reference_elapsed: list[float],
    zones: list[ZonePlan],
) -> list[float]:
    """Add the requested section time deltas, ramped across each section.

    The ramp starts at the reference braking point and ends at the reference
    throttle point, which is exactly the section the analyser compares.  The
    practice speed profile can itself change the section time, so the ramp is
    calibrated to cancel that base difference and land on the requested delta.
    """
    offsets = [0.0 for _ in distances]
    for zone in zones:
        start = zone.brake_m
        end = zone.release_m
        i0 = _index_at_or_after(distances, start)
        i1 = _index_at_or_after(distances, end)
        base_diff = (elapsed[i1] - elapsed[i0]) - (reference_elapsed[i1] - reference_elapsed[i0])
        ramp_delta = zone.practice_time_delta_s - base_diff
        if abs(ramp_delta) < 1e-12:
            continue
        span = max(end - start, 1e-9)
        for i in range(i0, i1 + 1):
            frac = min(max((distances[i] - start) / span, 0.0), 1.0)
            offsets[i] += ramp_delta * frac
        for i in range(i1 + 1, len(distances)):
            offsets[i] += ramp_delta
    return [t + o for t, o in zip(elapsed, offsets)]


def build_lap(
    *,
    track_length_m: float = 2400.0,
    step_m: float = 2.0,
    base_speed_kmh: float = 240.0,
    accel_distance_m: float = 120.0,
    zones: list[ZonePlan] | None = None,
    practice: bool = False,
    lap_number: int = 1,
    source: str = "<synthetic>",
) -> Lap:
    zones = list(DEFAULT_ZONES if zones is None else zones)
    count = int(round(track_length_m / step_m)) + 1
    distances = [round(i * step_m, 6) for i in range(count)]
    speed = _speed_profile(distances, zones, practice, base_speed_kmh, accel_distance_m)
    elapsed = _integrate_time(distances, speed)
    if practice:
        ref_speed = _speed_profile(distances, zones, False, base_speed_kmh, accel_distance_m)
        ref_elapsed = _integrate_time(distances, ref_speed)
        elapsed = _apply_time_deltas(distances, elapsed, ref_elapsed, zones)

    samples: list[Sample] = []
    for distance, time_s, speed_kmh in zip(distances, elapsed, speed):
        if practice and any(
            zone.practice_gap and zone.practice_gap[0] <= distance <= zone.practice_gap[1]
            for zone in zones
        ):
            continue
        braking = any(
            (zone.brake_m - (zone.practice_brake_shift_m if practice else 0.0))
            <= distance
            < zone.release_m
            for zone in zones
        )
        samples.append(
            Sample(
                distance_m=distance,
                elapsed_s=time_s,
                speed_kmh=speed_kmh,
                throttle=0.0 if braking else 1.0,
                brake=1.0 if braking else 0.0,
                lap_number=lap_number,
            )
        )
    return Lap(samples=samples, lap_number=lap_number, source=source)


def demo_laps() -> tuple[Lap, Lap]:
    reference = build_lap(practice=False, source="demo reference lap")
    practice = build_lap(practice=True, source="demo practice lap")
    return reference, practice


def identical_laps(*, zones: list[ZonePlan] | None = None, track_length_m: float = 1400.0) -> tuple[Lap, Lap]:
    reference = build_lap(track_length_m=track_length_m, zones=zones, practice=False)
    practice = build_lap(track_length_m=track_length_m, zones=zones, practice=False)
    return reference, practice


def shifted_lap(
    *,
    brake_shift_m: float = 12.0,
    time_delta_s: float = 0.18,
    min_speed_delta_kmh: float = -2.0,
) -> tuple[Lap, Lap]:
    """One braking zone with an exactly known shift and section time delta."""
    zone = ZonePlan(
        brake_m=400,
        apex_m=460,
        release_m=520,
        min_speed_kmh=90,
        practice_brake_shift_m=brake_shift_m,
        practice_min_speed_kmh=90 + min_speed_delta_kmh,
        practice_time_delta_s=time_delta_s,
    )
    reference = build_lap(track_length_m=1000, step_m=1.0, zones=[zone], practice=False)
    practice = build_lap(track_length_m=1000, step_m=1.0, zones=[zone], practice=True)
    return reference, practice
