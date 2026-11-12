from __future__ import annotations

import pytest

from racecoach.analysis import analyze
from racecoach.synth import shifted_lap


def test_known_twelve_metre_early_braking_shift():
    reference, practice = shifted_lap(
        brake_shift_m=12.0,
        time_delta_s=0.18,
        min_speed_delta_kmh=-2.0,
    )
    result = analyze(reference, practice)
    assert len(result.zones) == 1
    zone = result.zones[0]
    assert zone.status == "complete"
    assert zone.delta is not None
    assert zone.delta.brake_start_m == pytest.approx(12.0, abs=0.01)
    assert zone.delta.section_time_s == pytest.approx(0.18, abs=0.001)
    assert zone.delta.min_speed_kmh == pytest.approx(-2.0, abs=0.01)
    assert "12 metres earlier" in zone.message
    assert "0.18 seconds longer" in zone.message
    assert "minimum speed 2.0 km/h lower" in zone.message
    assert result.replay_events[0]["message"] == zone.message


def test_known_later_braking_shift_and_faster_section():
    reference, practice = shifted_lap(
        brake_shift_m=-8.0,
        time_delta_s=-0.09,
        min_speed_delta_kmh=1.5,
    )
    result = analyze(reference, practice)
    zone = result.zones[0]
    assert zone.status == "complete"
    assert zone.delta is not None
    assert zone.delta.brake_start_m == pytest.approx(-8.0, abs=0.01)
    assert zone.delta.section_time_s == pytest.approx(-0.09, abs=0.001)
    assert "8 metres later" in zone.message
    assert "0.09 seconds shorter" in zone.message
    assert "minimum speed 1.5 km/h higher" in zone.message


def test_section_time_is_measured_at_the_same_distances():
    reference, practice = shifted_lap()
    result = analyze(reference, practice)
    zone = result.zones[0]
    assert zone.reference is not None and zone.practice is not None
    assert zone.start_m == pytest.approx(400.0)
    assert zone.end_m == pytest.approx(520.0)
    assert zone.reference.section_time_s == pytest.approx(
        zone.reference.exit_time_s - zone.reference.entry_time_s
    )
    assert zone.practice.section_time_s == pytest.approx(
        zone.practice.exit_time_s - zone.practice.entry_time_s
    )
    assert (
        zone.practice.section_time_s - zone.reference.section_time_s
    ) == pytest.approx(zone.delta.section_time_s)
    assert zone.practice.section_time_s > zone.reference.section_time_s
