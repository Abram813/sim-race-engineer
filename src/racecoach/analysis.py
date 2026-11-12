"""Distance-based braking-zone analysis.

The reference lap defines the sections.  Each section starts at the reference
brake application and ends at the first throttle application after brake
release (or a bounded fallback).  The practice lap is sampled at the *same
distances*, so the comparison is always by distance rather than by elapsed
time.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import Gap, Lap, Sample, TelemetryError

DEFAULT_OPTIONS = {
    "max_gap_m": 25.0,
    "max_time_gap_s": 2.0,
    "brake_threshold": 0.05,
    "min_zone_length_m": 15.0,
    "merge_gap_m": 20.0,
    "min_brake_peak": 0.2,
    "zone_end_after_release_m": 30.0,
    "brake_search_back_m": 150.0,
    "brake_search_forward_m": 60.0,
    "distance_epsilon_m": 1.0,
    "time_epsilon_s": 0.01,
    "speed_epsilon_kmh": 0.5,
    "grid_step_m": 5.0,
}


@dataclass(frozen=True)
class AnalysisOptions:
    max_gap_m: float = 25.0
    max_time_gap_s: float = 2.0
    brake_threshold: float = 0.05
    min_zone_length_m: float = 15.0
    merge_gap_m: float = 20.0
    min_brake_peak: float = 0.2
    zone_end_after_release_m: float = 30.0
    brake_search_back_m: float = 150.0
    brake_search_forward_m: float = 60.0
    distance_epsilon_m: float = 1.0
    time_epsilon_s: float = 0.01
    speed_epsilon_kmh: float = 0.5
    grid_step_m: float = 5.0

    def to_dict(self) -> dict:
        return {name: getattr(self, name) for name in DEFAULT_OPTIONS}


@dataclass
class BrakingZone:
    index: int
    start_m: float
    end_m: float
    release_m: float
    peak_brake: float
    start_known: bool
    end_known: bool
    throttle_found: bool
    start_idx: int
    release_idx: int


@dataclass
class ZoneMetrics:
    brake_start_m: float | None
    brake_start_exact: bool
    min_speed_kmh: float
    entry_time_s: float
    exit_time_s: float
    section_time_s: float
    peak_brake: float = 0.0

    def to_dict(self) -> dict:
        return {
            "brake_start_m": _round(self.brake_start_m, 3),
            "brake_start_exact": self.brake_start_exact,
            "min_speed_kmh": _round(self.min_speed_kmh, 3),
            "entry_time_s": _round(self.entry_time_s, 4),
            "exit_time_s": _round(self.exit_time_s, 4),
            "section_time_s": _round(self.section_time_s, 4),
            "peak_brake": _round(self.peak_brake, 4),
        }


@dataclass
class ZoneDelta:
    brake_start_m: float | None
    min_speed_kmh: float
    section_time_s: float

    def to_dict(self) -> dict:
        return {
            "brake_start_m": _round(self.brake_start_m, 3),
            "min_speed_kmh": _round(self.min_speed_kmh, 3),
            "section_time_s": _round(self.section_time_s, 4),
        }


@dataclass
class ZoneComparison:
    index: int
    label: str
    start_m: float
    end_m: float
    status: str
    skip_reason: str | None
    reference: ZoneMetrics | None
    practice: ZoneMetrics | None
    delta: ZoneDelta | None
    message: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "label": self.label,
            "start_m": _round(self.start_m, 3),
            "end_m": _round(self.end_m, 3),
            "status": self.status,
            "skip_reason": self.skip_reason,
            "reference": self.reference.to_dict() if self.reference is not None else None,
            "practice": self.practice.to_dict() if self.practice is not None else None,
            "delta": self.delta.to_dict() if self.delta is not None else None,
            "message": self.message,
            "notes": list(self.notes),
        }


@dataclass
class AnalysisResult:
    reference: Lap
    practice: Lap
    options: AnalysisOptions
    zones: list[ZoneComparison]
    grid: dict
    summary: dict
    gaps: dict
    replay_events: list[dict]

    def to_dict(self, include_grid: bool = True) -> dict:
        data = {
            "reference": self.reference.summary(self.options.max_gap_m, self.options.max_time_gap_s),
            "practice": self.practice.summary(self.options.max_gap_m, self.options.max_time_gap_s),
            "options": self.options.to_dict(),
            "zones": [zone.to_dict() for zone in self.zones],
            "skipped": [zone.to_dict() for zone in self.zones if zone.status == "skipped"],
            "summary": self.summary,
            "gaps": self.gaps,
            "replay_events": self.replay_events,
            "messages": [zone.message for zone in self.zones if zone.status == "complete"],
        }
        if include_grid:
            data["grid"] = self.grid
        return data


def _round(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    value = round(value, digits)
    return 0.0 if value == 0 else value


def _fmt_distance(value: float) -> str:
    value = abs(value)
    if value >= 10 or abs(value - round(value)) < 0.05:
        return f"{value:.0f}"
    return f"{value:.1f}"


def _fmt_time(value: float) -> str:
    return f"{abs(value):.2f}"


def _fmt_speed(value: float) -> str:
    return f"{abs(value):.1f}"


def _runs(lap: Lap, options: AnalysisOptions) -> list[tuple[int, int, float]]:
    runs: list[tuple[int, int, float]] = []
    start: int | None = None
    peak = 0.0
    for idx, sample in enumerate(lap.samples):
        if sample.brake >= options.brake_threshold:
            if start is None:
                start = idx
                peak = sample.brake
            else:
                peak = max(peak, sample.brake)
        elif start is not None:
            runs.append((start, idx - 1, peak))
            start = None
            peak = 0.0
    if start is not None:
        runs.append((start, len(lap.samples) - 1, peak))

    merged: list[tuple[int, int, float]] = []
    for run in runs:
        if not merged:
            merged.append(run)
            continue
        prev = merged[-1]
        gap_m = lap.samples[run[0]].distance_m - lap.samples[prev[1]].distance_m
        if gap_m <= options.merge_gap_m:
            merged[-1] = (prev[0], run[1], max(prev[2], run[2]))
        else:
            merged.append(run)
    return merged


def detect_braking_zones(lap: Lap, options: AnalysisOptions | None = None) -> list[BrakingZone]:
    options = options or AnalysisOptions()
    runs = _runs(lap, options)
    zones: list[BrakingZone] = []
    for run_index, (start_idx, release_idx, peak) in enumerate(runs):
        start_m = lap.samples[start_idx].distance_m
        release_m = lap.samples[release_idx].distance_m
        length = release_m - start_m
        if length < options.min_zone_length_m or peak < options.min_brake_peak:
            continue

        next_start = None
        if run_index + 1 < len(runs):
            next_start = lap.samples[runs[run_index + 1][0]].distance_m

        end_m = release_m
        end_known = release_idx < len(lap.samples) - 1
        throttle_found = False
        for idx in range(release_idx + 1, len(lap.samples)):
            sample = lap.samples[idx]
            if sample.distance_m > release_m + options.zone_end_after_release_m:
                break
            if sample.throttle >= 0.5:
                end_m = sample.distance_m
                throttle_found = True
                break
        if not throttle_found:
            end_m = min(release_m + options.zone_end_after_release_m, lap.end_m)
        if next_start is not None:
            end_m = min(end_m, next_start - 5.0)
        if end_m <= start_m:
            end_known = False

        zones.append(
            BrakingZone(
                index=len(zones) + 1,
                start_m=start_m,
                end_m=end_m,
                release_m=release_m,
                peak_brake=peak,
                start_known=start_idx > 0,
                end_known=end_known and end_m > start_m,
                throttle_found=throttle_found,
                start_idx=start_idx,
                release_idx=release_idx,
            )
        )
    return zones


def _coverage_reason(lap: Lap, start_m: float, end_m: float, label: str) -> str | None:
    if start_m < lap.start_m - 1e-6 or end_m > lap.end_m + 1e-6:
        return (
            f"{label} data covers {lap.start_m:.0f}-{lap.end_m:.0f} m, "
            f"but this section is {start_m:.0f}-{end_m:.0f} m."
        )
    return None


def _gap_reason(gap: Gap, label: str) -> str:
    return (
        f"{label} data has a {gap.gap_m:.0f} m gap between "
        f"{gap.start_m:.0f} m and {gap.end_m:.0f} m inside this section."
    )


def _metrics(
    lap: Lap,
    start_m: float,
    end_m: float,
    brake_start_m: float | None,
    brake_start_exact: bool,
    options: AnalysisOptions,
    label: str,
) -> tuple[ZoneMetrics | None, str | None]:
    gap = lap.first_gap_between(start_m, end_m, options.max_gap_m, options.max_time_gap_s)
    if gap is not None:
        return None, _gap_reason(gap, label)
    coverage = _coverage_reason(lap, start_m, end_m, label)
    if coverage:
        return None, coverage
    entry = lap.sample_at(start_m, options.max_gap_m)
    exit_ = lap.sample_at(end_m, options.max_gap_m)
    if entry is None or exit_ is None:
        return None, f"{label} data does not cover the complete section."
    section_time = exit_.elapsed_s - entry.elapsed_s
    if section_time < -1e-6:
        return None, f"{label} elapsed time decreases inside this section; the recording is inconsistent."
    inner = lap.samples_between(start_m, end_m)
    speeds = [entry.speed_kmh, exit_.speed_kmh] + [s.speed_kmh for s in inner]
    return (
        ZoneMetrics(
            brake_start_m=brake_start_m,
            brake_start_exact=brake_start_exact,
            min_speed_kmh=min(speeds),
            entry_time_s=entry.elapsed_s,
            exit_time_s=exit_.elapsed_s,
            section_time_s=max(section_time, 0.0),
            peak_brake=max((s.brake for s in inner), default=0.0),
        ),
        None,
    )


def find_practice_brake_start(
    practice: Lap,
    zone: BrakingZone,
    previous_zone_end_m: float | None,
    options: AnalysisOptions,
) -> tuple[float | None, bool]:
    """Return (onset distance, exact).

    ``exact`` is False when practice was already braking at the start of the
    search window; in that case the distance is a lower bound.
    """
    lower = max(
        practice.start_m,
        previous_zone_end_m + 1.0 if previous_zone_end_m is not None else practice.start_m,
        zone.start_m - options.brake_search_back_m,
    )
    upper = min(zone.end_m, zone.start_m + options.brake_search_forward_m)
    if lower > upper:
        return None, False

    window = [s for s in practice.samples if lower - 1e-9 <= s.distance_m <= upper + 1e-9]
    if not window:
        return None, False

    first_braking = next(
        (s for s in window if s.brake >= options.brake_threshold),
        None,
    )
    if first_braking is None:
        return None, False

    # If the window opens mid-brake from the previous zone, skip to the next
    # release before looking for this zone's onset.
    scan_from = 0
    if window[0].brake >= options.brake_threshold:
        released = next(
            (i for i, s in enumerate(window) if s.brake < options.brake_threshold),
            None,
        )
        if released is None:
            return lower, False
        scan_from = released

    transitions: list[float] = []
    for i in range(max(scan_from, 1), len(window)):
        prev = window[i - 1]
        cur = window[i]
        if cur.brake >= options.brake_threshold and prev.brake < options.brake_threshold:
            transitions.append(cur.distance_m)
    if not transitions:
        # The window opened mid-brake and no later onset exists.
        return lower, False
    return min(transitions, key=lambda d: abs(d - zone.start_m)), True


def build_message(
    reference: ZoneMetrics,
    practice: ZoneMetrics,
    delta: ZoneDelta,
    *,
    practice_brake_exact: bool,
    practice_has_brake: bool,
    options: AnalysisOptions,
) -> str:
    no_difference = (
        abs(delta.min_speed_kmh) < options.speed_epsilon_kmh
        and abs(delta.section_time_s) < options.time_epsilon_s
        and (
            delta.brake_start_m is None
            or abs(delta.brake_start_m) < options.distance_epsilon_m
        )
        and practice_has_brake
    )
    if no_difference:
        return "Matched the reference through this section."

    parts: list[str] = []
    if not practice_has_brake:
        parts.append("You did not brake in this section")
    elif delta.brake_start_m is not None:
        if abs(delta.brake_start_m) < options.distance_epsilon_m:
            parts.append("You braked at the same point")
        else:
            direction = "earlier" if delta.brake_start_m > 0 else "later"
            prefix = "" if practice_brake_exact else "more than "
            parts.append(
                f"You started braking {prefix}{_fmt_distance(delta.brake_start_m)} metres {direction}"
            )

    if abs(delta.section_time_s) >= options.time_epsilon_s:
        direction = "longer" if delta.section_time_s > 0 else "shorter"
        time_part = f"took {_fmt_time(delta.section_time_s)} seconds {direction} through this section"
    else:
        time_part = "you matched the reference time through this section"

    if parts:
        message = parts[0] + " and " + time_part
    else:
        message = time_part[0].upper() + time_part[1:]

    if abs(delta.min_speed_kmh) >= options.speed_epsilon_kmh:
        direction = "lower" if delta.min_speed_kmh < 0 else "higher"
        message += f" (minimum speed {_fmt_speed(delta.min_speed_kmh)} km/h {direction})"
    return message + "."


def analyze(
    reference: Lap,
    practice: Lap,
    options: AnalysisOptions | None = None,
) -> AnalysisResult:
    options = options or AnalysisOptions()
    if not reference.samples or not practice.samples:
        raise TelemetryError("Both laps need at least two samples.")
    if reference.end_m <= reference.start_m or practice.end_m <= practice.start_m:
        raise TelemetryError("Both laps need a positive distance span.")

    zones = detect_braking_zones(reference, options)
    comparisons: list[ZoneComparison] = []
    previous_end: float | None = None

    for zone in zones:
        label = f"Braking zone {zone.index}"
        ref_brake_start = zone.start_m if zone.start_known else None
        ref_metrics, ref_error = _metrics(
            reference,
            zone.start_m,
            zone.end_m,
            ref_brake_start,
            zone.start_known,
            options,
            "Reference",
        )
        skip_reason = None
        notes: list[str] = []
        if not zone.start_known:
            skip_reason = "Reference lap begins mid-braking, so the braking point is unknown."
        elif not zone.end_known:
            skip_reason = "Reference lap ends before a usable section end."
        elif ref_error:
            skip_reason = ref_error
        if not zone.throttle_found and skip_reason is None:
            notes.append(
                "No throttle application was found after brake release; "
                f"the section ends {options.zone_end_after_release_m:.0f} m after release."
            )

        practice_metrics: ZoneMetrics | None = None
        delta: ZoneDelta | None = None
        message = ""
        if skip_reason is None:
            prac_brake_start, exact = find_practice_brake_start(
                practice, zone, previous_end, options
            )
            prac_metrics, prac_error = _metrics(
                practice,
                zone.start_m,
                zone.end_m,
                prac_brake_start,
                exact,
                options,
                "Practice",
            )
            if prac_error:
                skip_reason = prac_error
            elif ref_metrics is not None and prac_metrics is not None:
                practice_metrics = prac_metrics
                brake_delta = None
                if ref_metrics.brake_start_m is not None and prac_metrics.brake_start_m is not None:
                    brake_delta = ref_metrics.brake_start_m - prac_metrics.brake_start_m
                delta = ZoneDelta(
                    brake_start_m=brake_delta,
                    min_speed_kmh=prac_metrics.min_speed_kmh - ref_metrics.min_speed_kmh,
                    section_time_s=prac_metrics.section_time_s - ref_metrics.section_time_s,
                )
                if prac_metrics.brake_start_m is None:
                    notes.append("Practice has no brake application in this section.")
                elif not prac_metrics.brake_start_exact:
                    notes.append(
                        "Practice was already braking at the start of the search window; "
                        "the braking shift is a lower bound."
                    )
                message = build_message(
                    ref_metrics,
                    prac_metrics,
                    delta,
                    practice_brake_exact=prac_metrics.brake_start_exact,
                    practice_has_brake=prac_metrics.brake_start_m is not None,
                    options=options,
                )

        if skip_reason is not None:
            message = f"Skipped: {skip_reason}"
            practice_metrics = None
            delta = None
        comparisons.append(
            ZoneComparison(
                index=zone.index,
                label=label,
                start_m=zone.start_m,
                end_m=zone.end_m,
                status="skipped" if skip_reason else "complete",
                skip_reason=skip_reason,
                reference=ref_metrics,
                practice=practice_metrics,
                delta=delta,
                message=message,
                notes=notes,
            )
        )
        previous_end = zone.end_m

    grid = _build_grid(reference, practice, options)
    completed = [zone for zone in comparisons if zone.status == "complete"]
    skipped = [zone for zone in comparisons if zone.status == "skipped"]
    replay_events = [
        {
            "distance_m": _round(zone.end_m, 3),
            "zone_index": zone.index,
            "label": zone.label,
            "message": zone.message,
        }
        for zone in completed
    ]

    ref_gaps = reference.gaps(options.max_gap_m, options.max_time_gap_s)
    prac_gaps = practice.gaps(options.max_gap_m, options.max_time_gap_s)
    start_m = grid["start_m"]
    end_m = grid["end_m"]
    total_delta = None
    ref_total = None
    prac_total = None
    if start_m is not None and end_m is not None:
        ref_start = reference.sample_at(start_m, options.max_gap_m)
        ref_end = reference.sample_at(end_m, options.max_gap_m)
        prac_start = practice.sample_at(start_m, options.max_gap_m)
        prac_end = practice.sample_at(end_m, options.max_gap_m)
        if ref_start and ref_end and prac_start and prac_end:
            ref_total = ref_end.elapsed_s - ref_start.elapsed_s
            prac_total = prac_end.elapsed_s - prac_start.elapsed_s
            total_delta = prac_total - ref_total

    summary = {
        "braking_zones": len(comparisons),
        "completed_zones": len(completed),
        "skipped_zones": len(skipped),
        "replay_messages": len(replay_events),
        "overlap_start_m": _round(start_m, 3),
        "overlap_end_m": _round(end_m, 3),
        "overlap_distance_m": _round((end_m - start_m) if start_m is not None and end_m is not None else None, 3),
        "reference_overlap_time_s": _round(ref_total, 4),
        "practice_overlap_time_s": _round(prac_total, 4),
        "total_time_delta_s": _round(total_delta, 4),
        "reference_gaps": len(ref_gaps),
        "practice_gaps": len(prac_gaps),
    }
    gaps = {
        "reference": [gap.to_dict() for gap in ref_gaps],
        "practice": [gap.to_dict() for gap in prac_gaps],
    }
    return AnalysisResult(
        reference=reference,
        practice=practice,
        options=options,
        zones=comparisons,
        grid=grid,
        summary=summary,
        gaps=gaps,
        replay_events=replay_events,
    )


def _build_grid(reference: Lap, practice: Lap, options: AnalysisOptions) -> dict:
    start_m = max(reference.start_m, practice.start_m)
    end_m = min(reference.end_m, practice.end_m)
    if end_m <= start_m:
        raise TelemetryError(
            "The reference and practice laps do not overlap by distance. "
            f"Reference: {reference.start_m:.0f}-{reference.end_m:.0f} m; "
            f"practice: {practice.start_m:.0f}-{practice.end_m:.0f} m."
        )
    step = max(options.grid_step_m, 0.5)
    distances: list[float] = []
    value = start_m
    while value < end_m - 1e-9:
        distances.append(round(value, 3))
        value += step
    distances.append(round(end_m, 3))

    def series(lap: Lap) -> dict:
        speed: list[float | None] = []
        throttle: list[float | None] = []
        brake: list[float | None] = []
        elapsed: list[float | None] = []
        for distance in distances:
            sample = lap.sample_at(distance, options.max_gap_m)
            if sample is None:
                speed.append(None)
                throttle.append(None)
                brake.append(None)
                elapsed.append(None)
            else:
                speed.append(round(sample.speed_kmh, 3))
                throttle.append(round(sample.throttle, 4))
                brake.append(round(sample.brake, 4))
                elapsed.append(round(sample.elapsed_s, 4))
        return {
            "speed_kmh": speed,
            "throttle": throttle,
            "brake": brake,
            "elapsed_s": elapsed,
        }

    ref_series = series(reference)
    prac_series = series(practice)
    delta_time: list[float | None] = []
    for ref_t, prac_t in zip(ref_series["elapsed_s"], prac_series["elapsed_s"]):
        if ref_t is None or prac_t is None:
            delta_time.append(None)
        else:
            delta_time.append(round(prac_t - ref_t, 4))
    return {
        "start_m": _round(start_m, 3),
        "end_m": _round(end_m, 3),
        "step_m": step,
        "distance_m": distances,
        "reference": ref_series,
        "practice": prac_series,
        "delta_time_s": delta_time,
    }
