from __future__ import annotations

import pytest

from racecoach.csvio import read_csv_file
from racecoach.demo import demo_csv_texts, demo_payload, export_demo


def test_demo_payload_has_known_feedback():
    payload = demo_payload()
    analysis = payload["analysis"]
    assert payload["demo"] is True
    assert analysis["summary"]["braking_zones"] == 5
    assert analysis["summary"]["completed_zones"] == 4
    assert analysis["summary"]["skipped_zones"] == 1
    assert analysis["summary"]["practice_gaps"] == 1
    first = analysis["zones"][0]
    assert "12 metres earlier" in first["message"]
    assert "0.18 seconds longer" in first["message"]
    assert analysis["zones"][1]["message"] == "Matched the reference through this section."
    assert analysis["zones"][3]["status"] == "skipped"
    assert "44 m gap" in analysis["zones"][3]["skip_reason"]
    assert len(analysis["replay_events"]) == 4


def test_demo_csv_texts_roundtrip():
    ref_text, prac_text = demo_csv_texts()
    assert ref_text.startswith("lap_number,distance_m,elapsed_s,speed_kmh,throttle,brake")
    assert prac_text.count("\n") > 1000
    from racecoach.csvio import parse_csv

    ref = parse_csv(ref_text).laps[0]
    prac = parse_csv(prac_text).laps[0]
    assert ref.end_m == pytest.approx(2400.0)
    assert prac.end_m == pytest.approx(2400.0)


def test_export_demo_writes_openable_files(tmp_path):
    ref_path, prac_path = export_demo(tmp_path / "path with spaces")
    assert ref_path.exists() and prac_path.exists()
    ref = read_csv_file(ref_path).laps[0]
    prac = read_csv_file(prac_path).laps[0]
    assert ref.sample_count > 1000
    assert prac.sample_count > 1000
