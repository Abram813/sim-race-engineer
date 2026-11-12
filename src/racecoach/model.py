"""Core telemetry data model.

All comparisons in RaceCoach are made against distance, never against wall
clock time.  A lap is an ordered list of samples plus the bookkeeping needed
to detect missing data.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from typing import Iterable


class TelemetryError(ValueError):
    """Base class for user-facing telemetry errors."""


class CsvFormatError(TelemetryError):
    """Raised when a CSV cannot be interpreted as a lap recording."""


@dataclass(frozen=True, slots=True)
class Sample:
    distance_m: float
    elapsed_s: float
    speed_kmh: float
    throttle: float
    brake: float
    lap_number: int = 1


@dataclass(frozen=True, slots=True)
class InterpolatedSample:
    distance_m: float
    elapsed_s: float
    speed_kmh: float
    throttle: float
    brake: float


@dataclass(frozen=True, slots=True)
class Gap:
    start_m: float
    end_m: float
    gap_m: float
    gap_s: float

    def to_dict(self) -> dict:
        return {
            "start_m": round(self.start_m, 3),
            "end_m": round(self.end_m, 3),
            "gap_m": round(self.gap_m, 3),
            "gap_s": round(self.gap_s, 3),
        }


@dataclass
class Lap:
    samples: list[Sample]
    lap_number: int = 1
    segment: int = 1
    source: str = "<memory>"
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.samples.sort(key=lambda s: s.distance_m)
        self._distances = [s.distance_m for s in self.samples]

    @property
    def label(self) -> str:
        if self.segment > 1:
            return f"Lap {self.lap_number} (segment {self.segment})"
        return f"Lap {self.lap_number}"

    @property
    def start_m(self) -> float:
        return self.samples[0].distance_m if self.samples else 0.0

    @property
    def end_m(self) -> float:
        return self.samples[-1].distance_m if self.samples else 0.0

    @property
    def duration_s(self) -> float:
        if not self.samples:
            return 0.0
        return self.samples[-1].elapsed_s - self.samples[0].elapsed_s

    @property
    def sample_count(self) -> int:
        return len(self.samples)

    def sample_at(self, distance_m: float, max_gap_m: float = 25.0) -> InterpolatedSample | None:
        """Linearly interpolate at a distance.

        Returns ``None`` when the distance is outside the lap or when the
        bracketing samples straddle a data gap larger than ``max_gap_m``.
        Interpolating across a gap would invent telemetry, so we never do it.
        """
        if not self.samples:
            return None
        if distance_m < self.start_m - 1e-6 or distance_m > self.end_m + 1e-6:
            return None

        idx = bisect_left(self._distances, distance_m)
        if idx < len(self.samples) and abs(self._distances[idx] - distance_m) <= 1e-6:
            s = self.samples[idx]
            return InterpolatedSample(s.distance_m, s.elapsed_s, s.speed_kmh, s.throttle, s.brake)
        if idx == 0:
            s = self.samples[0]
            return InterpolatedSample(s.distance_m, s.elapsed_s, s.speed_kmh, s.throttle, s.brake)
        if idx >= len(self.samples):
            s = self.samples[-1]
            return InterpolatedSample(s.distance_m, s.elapsed_s, s.speed_kmh, s.throttle, s.brake)

        left = self.samples[idx - 1]
        right = self.samples[idx]
        span = right.distance_m - left.distance_m
        if span > max_gap_m:
            return None
        if span <= 1e-9:
            return InterpolatedSample(
                right.distance_m, right.elapsed_s, right.speed_kmh, right.throttle, right.brake
            )
        t = (distance_m - left.distance_m) / span
        return InterpolatedSample(
            distance_m=distance_m,
            elapsed_s=left.elapsed_s + t * (right.elapsed_s - left.elapsed_s),
            speed_kmh=left.speed_kmh + t * (right.speed_kmh - left.speed_kmh),
            throttle=left.throttle + t * (right.throttle - left.throttle),
            brake=left.brake + t * (right.brake - left.brake),
        )

    def samples_between(self, start_m: float, end_m: float) -> list[Sample]:
        return [s for s in self.samples if start_m - 1e-9 <= s.distance_m <= end_m + 1e-9]

    def first_gap_between(
        self,
        start_m: float,
        end_m: float,
        max_gap_m: float = 25.0,
        max_time_gap_s: float = 2.0,
    ) -> Gap | None:
        for gap in self.gaps(max_gap_m=max_gap_m, max_time_gap_s=max_time_gap_s):
            if gap.end_m < start_m or gap.start_m > end_m:
                continue
            return gap
        return None

    def gaps(self, max_gap_m: float = 25.0, max_time_gap_s: float = 2.0) -> list[Gap]:
        out: list[Gap] = []
        for a, b in zip(self.samples, self.samples[1:]):
            gap_m = b.distance_m - a.distance_m
            gap_s = b.elapsed_s - a.elapsed_s
            if gap_m > max_gap_m or gap_s > max_time_gap_s:
                out.append(Gap(a.distance_m, b.distance_m, gap_m, gap_s))
        return out

    def summary(self, max_gap_m: float = 25.0, max_time_gap_s: float = 2.0) -> dict:
        return {
            "label": self.label,
            "lap_number": self.lap_number,
            "segment": self.segment,
            "source": self.source,
            "start_m": round(self.start_m, 3),
            "end_m": round(self.end_m, 3),
            "duration_s": round(self.duration_s, 3),
            "sample_count": self.sample_count,
            "gaps": [g.to_dict() for g in self.gaps(max_gap_m, max_time_gap_s)],
            "warnings": list(self.warnings),
        }


@dataclass
class LapSet:
    laps: list[Lap]
    warnings: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)

    def summaries(self) -> list[dict]:
        return [lap.summary() for lap in self.laps]

    def default_index(self) -> int:
        """Pick a sensible default lap.

        Prefer the most complete lap (largest distance span), then the fastest
        one.  This avoids selecting a short out-lap when a full lap is present.
        """
        if not self.laps:
            raise CsvFormatError("The file contains no usable lap data.")
        best = max(self.laps, key=lambda lap: (lap.end_m - lap.start_m, -lap.duration_s))
        return self.laps.index(best)


def clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def median(values: Iterable[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0
