from __future__ import annotations

from racecoach import cli
from racecoach.analysis import analyze
from racecoach.synth import demo_laps


def test_replay_events_are_one_per_completed_zone():
    reference, practice = demo_laps()
    result = analyze(reference, practice)
    completed = [zone for zone in result.zones if zone.status == "complete"]
    assert len(result.replay_events) == len(completed) == 4
    assert [event["zone_index"] for event in result.replay_events] == [zone.index for zone in completed]
    assert [event["distance_m"] for event in result.replay_events] == sorted(
        event["distance_m"] for event in result.replay_events
    )
    assert all("Skipped" not in event["message"] for event in result.replay_events)


def test_cli_replay_prints_one_message_per_completed_zone(demo_files, capsys):
    ref_path, prac_path = demo_files
    code = cli.main(
        [
            "replay",
            "--reference",
            str(ref_path),
            "--practice",
            str(prac_path),
        ]
    )
    output = capsys.readouterr().out
    assert code == 0
    message_lines = [line for line in output.splitlines() if line.startswith("[") and " m] " in line]
    assert len(message_lines) == 4
    assert "Replay complete: 4 message(s), one per completed braking zone." in output
    assert "12 metres earlier" in output
    assert "Skipped" not in output
