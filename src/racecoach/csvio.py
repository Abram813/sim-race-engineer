"""CSV input and output.

The interchange format is deliberately small::

    lap_number,distance_m,elapsed_s,speed_kmh,throttle,brake

Parsing is forgiving about common header spellings and delimiters, but it is
strict about never inventing data: malformed rows are dropped with a warning,
and distance gaps are preserved so the analyser can skip incomplete sections.
"""

from __future__ import annotations

import csv
import io
import math
import re
from pathlib import Path

from .model import CsvFormatError, Lap, LapSet, Sample, clamp01

CANONICAL_COLUMNS = [
    "lap_number",
    "distance_m",
    "elapsed_s",
    "speed_kmh",
    "throttle",
    "brake",
]

_ALIASES: dict[str, set[str]] = {
    "lap_number": {
        "lap_number",
        "lap",
        "lap_no",
        "lapno",
        "lap_num",
        "lapnum",
        "lap_index",
        "lapindex",
    },
    "distance_m": {
        "distance_m",
        "distance",
        "dist_m",
        "dist",
        "distance_metres",
        "distance_meters",
        "meters",
        "metres",
        "lap_distance_m",
        "lapdistance",
    },
    "elapsed_s": {
        "elapsed_s",
        "elapsed",
        "time_s",
        "time",
        "laptime",
        "lap_time",
        "lap_time_s",
        "elapsed_time_s",
        "t",
    },
    "speed_kmh": {
        "speed_kmh",
        "speed",
        "speed_kph",
        "speed_km_h",
        "speedkmh",
        "kmh",
        "kph",
    },
    "throttle": {
        "throttle",
        "gas",
        "throttle_0_1",
        "throttle_pct",
        "throttle_percent",
        "throttle_percentage",
    },
    "brake": {
        "brake",
        "brake_0_1",
        "brake_pct",
        "brake_percent",
        "brake_percentage",
    },
}

_ALIAS_TO_CANONICAL = {
    alias: canonical for canonical, aliases in _ALIASES.items() for alias in aliases
}


def _normalise_header(value: str) -> str:
    value = value.replace("\ufeff", "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")


def _detect_delimiter(text: str) -> str:
    first_line = next((line for line in text.splitlines() if line.strip()), "")
    counts = {",": first_line.count(","), ";": first_line.count(";"), "\t": first_line.count("\t")}
    delimiter = max(counts, key=counts.get)
    return delimiter if counts[delimiter] else ","


def _parse_number(raw: str, field: str, row_number: int, delimiter: str) -> float:
    value = raw.strip()
    if not value:
        raise ValueError(f"row {row_number}: empty {field}")
    percent = value.endswith("%")
    if percent:
        value = value[:-1].strip()
    if delimiter != "," and "," in value and "." not in value:
        value = value.replace(",", ".")
    value = value.replace(" ", "")
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(f"row {row_number}: {field}={raw!r} is not a number") from exc
    if not math.isfinite(number):
        raise ValueError(f"row {row_number}: {field}={raw!r} is not finite")
    return number / 100.0 if percent else number


def parse_csv(text: str, source: str = "<memory>", max_gap_m: float = 25.0) -> LapSet:
    """Parse telemetry CSV text into one or more laps."""
    if not text or not text.strip():
        raise CsvFormatError("The CSV file is empty.")

    text = text.replace("\ufeff", "")
    delimiter = _detect_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        raise CsvFormatError("The CSV file contains no data rows.")

    first = [_normalise_header(cell) for cell in rows[0]]
    canonical_first = [_ALIAS_TO_CANONICAL.get(cell) for cell in first]
    warnings: list[str] = []

    if all(name is not None for name in canonical_first):
        header = canonical_first
        data_rows = rows[1:]
        start_row = 2
    else:
        # Accept headerless files only when the first row is clearly numeric and
        # has at least the five required measurements.
        numeric = True
        for cell in rows[0]:
            try:
                float(cell.replace(",", "."))
            except ValueError:
                numeric = False
                break
        if numeric and len(rows[0]) >= 5:
            if len(rows[0]) >= 6:
                header = CANONICAL_COLUMNS[: len(rows[0])]
            else:
                header = CANONICAL_COLUMNS[1:]
            data_rows = rows
            start_row = 1
            warnings.append("No header row found; assuming the documented column order.")
        else:
            found = ", ".join(cell or "<blank>" for cell in first)
            raise CsvFormatError(
                "Could not find the required columns. "
                f"Found: {found}. Expected: {', '.join(CANONICAL_COLUMNS)}. "
                "Column names are case-insensitive and common aliases are accepted."
            )

    positions: dict[str, int] = {}
    for idx, name in enumerate(header):
        if name is None:
            continue
        if name in positions:
            raise CsvFormatError(f"Column {name!r} appears more than once.")
        positions[name] = idx

    required = ["distance_m", "elapsed_s", "speed_kmh", "throttle", "brake"]
    missing = [name for name in required if name not in positions]
    if missing:
        raise CsvFormatError(
            "Missing required column(s): "
            + ", ".join(missing)
            + ". Expected: "
            + ", ".join(CANONICAL_COLUMNS)
            + "."
        )
    if "lap_number" not in positions:
        warnings.append("No lap_number column; treating every row as lap 1.")

    parsed: list[tuple[int, float, float, float, float, float]] = []
    for offset, row in enumerate(data_rows):
        row_number = start_row + offset
        if not any(cell.strip() for cell in row):
            continue
        try:
            def cell(name: str) -> str:
                idx = positions[name]
                if idx >= len(row):
                    raise ValueError(f"row {row_number}: missing value for {name}")
                return row[idx]

            lap_raw = cell("lap_number") if "lap_number" in positions else "1"
            lap_number = int(float(lap_raw.replace(",", "."))) if lap_raw.strip() else 1
            distance = _parse_number(cell("distance_m"), "distance_m", row_number, delimiter)
            elapsed = _parse_number(cell("elapsed_s"), "elapsed_s", row_number, delimiter)
            speed = _parse_number(cell("speed_kmh"), "speed_kmh", row_number, delimiter)
            throttle = _parse_number(cell("throttle"), "throttle", row_number, delimiter)
            brake = _parse_number(cell("brake"), "brake", row_number, delimiter)
        except (ValueError, IndexError) as exc:
            warnings.append(f"Skipped {exc}.")
            continue
        if speed < 0:
            warnings.append(f"Row {row_number}: negative speed clamped to 0.")
            speed = 0.0
        parsed.append((lap_number, distance, elapsed, speed, throttle, brake))

    if not parsed:
        raise CsvFormatError("No usable telemetry rows were found. " + " ".join(warnings[-3:]))

    # Pedal channels are documented as 0..1.  Some tools export 0..100; scale
    # once for the whole file rather than silently clamping every row.
    for channel, idx in (("throttle", 4), ("brake", 5)):
        peak = max(abs(row[idx]) for row in parsed)
        if peak > 1.5 and peak <= 100.5:
            warnings.append(f"{channel} values look like percent; divided by 100.")
            parsed = [
                row[:idx] + (row[idx] / 100.0,) + row[idx + 1 :] for row in parsed
            ]
            peak = max(abs(row[idx]) for row in parsed)
        if peak > 1.0 or min(row[idx] for row in parsed) < 0.0:
            warnings.append(f"{channel} values outside 0..1 were clamped.")
            parsed = [
                row[:idx] + (clamp01(row[idx]),) + row[idx + 1 :] for row in parsed
            ]

    # Split into laps.  A lap can also split into segments when distance resets
    # without the lap number changing (a pit reset, or a game writing a new lap
    # before the lap counter updates).
    groups: list[list[tuple[int, float, float, float, float, float]]] = []
    current: list[tuple[int, float, float, float, float, float]] = []
    last_lap: int | None = None
    last_distance: float | None = None
    last_elapsed: float | None = None
    for row in parsed:
        lap_number, distance, elapsed, speed, throttle, brake = row
        new_group = False
        if last_lap is None or lap_number != last_lap:
            new_group = True
        elif last_distance is not None and distance < last_distance - 1.0:
            new_group = True
            warnings.append(
                f"Distance reset from {last_distance:.1f} m to {distance:.1f} m "
                f"inside lap {lap_number}; treated as a new segment."
            )
        elif last_elapsed is not None and elapsed < last_elapsed - 1e-6:
            warnings.append(
                f"Elapsed time went backwards inside lap {lap_number}; "
                "that row was skipped."
            )
            continue
        if new_group and current:
            groups.append(current)
            current = []
        if not current and last_distance is not None and distance == last_distance:
            # Duplicate first sample after a split; harmless.
            pass
        current.append(row)
        last_lap = lap_number
        last_distance = distance
        last_elapsed = elapsed
    if current:
        groups.append(current)

    laps: list[Lap] = []
    segment_counts: dict[int, int] = {}
    for group in groups:
        lap_number = group[0][0]
        segment_counts[lap_number] = segment_counts.get(lap_number, 0) + 1
        segment = segment_counts[lap_number]
        samples: list[Sample] = []
        seen_distance: dict[float, int] = {}
        for lap_no, distance, elapsed, speed, throttle, brake in group:
            key = round(distance, 2)
            if key in seen_distance:
                idx = seen_distance[key]
                warnings.append(
                    f"Duplicate distance {distance:.2f} m in lap {lap_number}; kept the later row."
                )
                samples[idx] = Sample(distance, elapsed, speed, throttle, brake, lap_no)
            else:
                seen_distance[key] = len(samples)
                samples.append(Sample(distance, elapsed, speed, throttle, brake, lap_no))
        if len(samples) < 2:
            warnings.append(f"{Lap(samples, lap_number, segment, source).label} has fewer than 2 samples and was ignored.")
            continue
        laps.append(Lap(samples=samples, lap_number=lap_number, segment=segment, source=source, warnings=[]))

    if not laps:
        raise CsvFormatError("No lap with at least two samples was found. " + " ".join(warnings[-3:]))

    for lap in laps:
        lap.warnings = list(warnings)
    return LapSet(laps=laps, warnings=warnings, columns=[name for name in header if name])


def read_csv_file(path: str | Path, max_gap_m: float = 25.0) -> LapSet:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise CsvFormatError(f"Could not read {path}: {exc}") from exc
    return parse_csv(text, source=str(path), max_gap_m=max_gap_m)


def _format_row(sample: Sample) -> list[str]:
    return [
        str(int(sample.lap_number)),
        f"{sample.distance_m:.3f}",
        f"{sample.elapsed_s:.3f}",
        f"{sample.speed_kmh:.2f}",
        f"{sample.throttle:.3f}",
        f"{sample.brake:.3f}",
    ]


def write_csv_text(laps: list[Lap]) -> str:
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CANONICAL_COLUMNS)
    for lap in laps:
        for sample in lap.samples:
            row = _format_row(sample)
            if sample.lap_number != lap.lap_number:
                row[0] = str(int(lap.lap_number))
            writer.writerow(row)
    return out.getvalue()


def write_laps_csv(laps: list[Lap], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(write_csv_text(laps), encoding="utf-8")
    return path


def write_lap_csv(lap: Lap, path: str | Path) -> Path:
    return write_laps_csv([lap], path)
