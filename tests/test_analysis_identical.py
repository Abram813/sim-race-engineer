from __future__ import annotations

import pytest

from racecoach.analysis import analyze
from racecoach.csvio import read_csv_file, write_lap_csv
from racecoach.model import Lap
from racecoach.synth import identical_laps


def test_identical_laps_have_zero_difference():
    reference, practice = identical_laps()
    result = analyze(reference, practice)
    assert result.summary["completed_zones"] == 3
    assert result.summary["skipped_zones"] == 0
    assert result.summary["total_time_delta_s"] == 0
    assert result.summary["reference_overlap_time_s"] == result.summary["practice_overlap_time_s"]
    assert len(result.replay_events) == result.summary["completed_zones"]
    for zone in result.zones:
        assert zone.status == "complete"
        assert zone.delta is not None
        assert zone.delta.brake_start_m == 0
        assert zone.delta.min_speed_kmh == 0
        assert zone.delta.section_time_s == 0
        assert zone.message == "Matched the reference through this section."


def test_identical_laps_roundtripped_through_csv_stay_within_rounding(tmp_path):
    reference, practice = identical_laps()
    ref_path = write_lap_csv(reference, tmp_path / "reference lap.csv")
    prac_path = write_lap_csv(practice, tmp_path / "practice lap.csv")
    ref = read_csv_file(ref_path).laps[0]
    prac = read_csv_file(prac_path).laps[0]
    result = analyze(ref, prac)
    assert result.summary["completed_zones"] == 3
    assert abs(result.summary["total_time_delta_s"]) < 0.005
    for zone in result.zones:
        assert zone.status == "complete"
        assert zone.delta is not None
        assert abs(zone.delta.section_time_s) < 0.005
        assert abs(zone.delta.min_speed_kmh) < 0.01
        assert zone.message == "Matched the reference through this section."


def test_practice_with_a_large_gap_is_skipped_and_flagged():
    from racecoach.synth import demo_laps

    reference, practice = demo_laps()
    result = analyze(reference, practice)
    assert result.summary["completed_zones"] == 4
    assert result.summary["skipped_zones"] == 1
    assert result.summary["practice_gaps"] == 1
    assert result.gaps["practice"][0]["gap_m"] == pytest.approx(44.0)
    skipped = [zone for zone in result.zones if zone.status == "skipped"]
    assert len(skipped) == 1
    assert "gap" in skipped[0].skip_reason.lower()
    assert "44 m" in skipped[0].skip_reason
    assert len(result.replay_events) == 4
    assert all("Skipped" not in event["message"] for event in result.replay_events)


def test_truncated_practice_data_skips_the_incomplete_section():
    from racecoach.synth import demo_laps

    reference, practice = demo_laps()
    truncated = Lap(
        samples=[sample for sample in practice.samples if sample.distance_m <= 350],
        lap_number=1,
        source="truncated practice",
    )
    result = analyze(reference, truncated)
    first = result.zones[0]
    assert first.status == "skipped"
    assert "covers" in first.skip_reason
    assert first.practice is None
    assert first.delta is None
    assert len(result.replay_events) == result.summary["completed_zones"]


def test_reference_that_ends_mid_braking_is_skipped():
    from racecoach.synth import demo_laps

    reference, practice = demo_laps()
    truncated = Lap(
        samples=[sample for sample in reference.samples if sample.distance_m <= 350],
        lap_number=1,
        source="truncated reference",
    )
    result = analyze(truncated, practice)
    assert result.zones[0].status == "skipped"
    assert "ends" in result.zones[0].skip_reason.lower() or "mid-braking" in result.zones[0].skip_reason.lower()
