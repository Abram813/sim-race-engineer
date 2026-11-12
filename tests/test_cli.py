from __future__ import annotations

import json

from racecoach import cli


def test_analyze_json_is_machine_readable(demo_files, capsys):
    ref_path, prac_path = demo_files
    code = cli.main(
        [
            "analyze",
            "--reference",
            str(ref_path),
            "--practice",
            str(prac_path),
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["completed_zones"] == 4
    assert payload["zones"][0]["message"].startswith("You started braking 12 metres earlier")
    assert "grid" not in payload
    assert len(payload["replay_events"]) == 4


def test_analyze_human_output_contains_measurable_feedback(demo_files, capsys):
    ref_path, prac_path = demo_files
    code = cli.main(
        [
            "analyze",
            "--reference",
            str(ref_path),
            "--practice",
            str(prac_path),
        ]
    )
    output = capsys.readouterr().out
    assert code == 0
    assert "12 metres earlier" in output
    assert "0.18 seconds longer" in output
    assert "Skipped sections:" in output
    assert "44 m gap" in output
    assert "Replay messages: 4" in output


def test_export_demo_command(tmp_path, capsys):
    out = tmp_path / "demo laps"
    code = cli.main(["export-demo", "--out", str(out)])
    output = capsys.readouterr().out
    assert code == 0
    assert (out / "reference_lap.csv").exists()
    assert (out / "practice_lap.csv").exists()
    assert "reference_lap.csv" in output
