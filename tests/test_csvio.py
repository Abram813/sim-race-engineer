from __future__ import annotations

import pytest

from racecoach.csvio import parse_csv, write_csv_text
from racecoach.model import CsvFormatError


CANONICAL = """lap_number,distance_m,elapsed_s,speed_kmh,throttle,brake
1,0,0,200,1,0
1,10,0.2,190,1,0
1,20,0.45,120,0,0.8
1,30,0.75,90,0,1.0
1,40,1.1,100,0.6,0.2
"""


def test_parse_canonical_csv():
    laps = parse_csv(CANONICAL)
    assert len(laps.laps) == 1
    lap = laps.laps[0]
    assert lap.lap_number == 1
    assert lap.sample_count == 5
    assert lap.start_m == 0
    assert lap.end_m == 40
    assert lap.samples[2].brake == 0.8


def test_bom_semicolon_and_decimal_comma():
    text = "\ufefflap_number;distance_m;elapsed_s;speed_kmh;throttle;brake\n1;0;0;200;1;0\n1;10;0,2;190;1;0\n1;20;0,45;120;0;0,8\n"
    laps = parse_csv(text)
    assert laps.laps[0].sample_count == 3
    assert laps.laps[0].samples[2].elapsed_s == 0.45
    assert laps.laps[0].samples[2].brake == 0.8


def test_aliases_and_percent_pedals():
    text = """Lap, Distance (m), Time (s), Speed (km/h), Gas, Brake
1,0,0,200,100,0
1,10,0.2,190,100,0
1,20,0.45,120,0,80
1,30,0.75,90,0,100
"""
    laps = parse_csv(text)
    lap = laps.laps[0]
    assert lap.samples[2].throttle == 0
    assert lap.samples[2].brake == 0.8
    assert any("divided by 100" in warning for warning in laps.warnings)


def test_invalid_rows_are_skipped_with_warning():
    text = """lap_number,distance_m,elapsed_s,speed_kmh,throttle,brake
1,0,0,200,1,0
1,bad,0.2,190,1,0
1,20,0.45,120,0,0.8
1,30,0.75,90,0,1.0
"""
    laps = parse_csv(text)
    assert laps.laps[0].sample_count == 3
    assert any("not a number" in warning for warning in laps.warnings)


def test_distance_reset_splits_segments():
    text = """lap_number,distance_m,elapsed_s,speed_kmh,throttle,brake
1,0,0,200,1,0
1,50,1,190,1,0
1,10,2,150,1,0
1,60,3,140,1,0
"""
    laps = parse_csv(text)
    assert len(laps.laps) == 2
    assert laps.laps[0].segment == 1
    assert laps.laps[1].segment == 2
    assert any("Distance reset" in warning for warning in laps.warnings)


def test_missing_required_columns_raises():
    with pytest.raises(CsvFormatError, match="Missing required column"):
        parse_csv("lap_number,distance_m,elapsed_s,speed_kmh,throttle\n1,0,0,200,1\n")


def test_empty_csv_raises():
    with pytest.raises(CsvFormatError, match="empty"):
        parse_csv("   \n")


def test_headerless_file_uses_documented_order():
    text = """1,0,0,200,1,0
1,10,0.2,190,1,0
1,20,0.45,120,0,0.8
"""
    laps = parse_csv(text)
    assert laps.laps[0].sample_count == 3
    assert any("No header" in warning for warning in laps.warnings)


def test_duplicate_distance_keeps_later_row():
    text = """lap_number,distance_m,elapsed_s,speed_kmh,throttle,brake
1,0,0,200,1,0
1,10,0.2,190,1,0
1,10,0.25,180,1,0
1,20,0.45,120,0,0.8
"""
    laps = parse_csv(text)
    assert laps.laps[0].sample_count == 3
    assert laps.laps[0].samples[1].speed_kmh == 180
    assert any("Duplicate distance" in warning for warning in laps.warnings)


def test_write_roundtrip():
    laps = parse_csv(CANONICAL)
    text = write_csv_text(laps.laps)
    again = parse_csv(text)
    assert again.laps[0].sample_count == laps.laps[0].sample_count
    for a, b in zip(laps.laps[0].samples, again.laps[0].samples):
        assert a.distance_m == pytest.approx(b.distance_m)
        assert a.elapsed_s == pytest.approx(b.elapsed_s)
        assert a.speed_kmh == pytest.approx(b.speed_kmh)
        assert a.throttle == pytest.approx(b.throttle)
        assert a.brake == pytest.approx(b.brake)
