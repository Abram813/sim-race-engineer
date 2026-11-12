from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from racecoach.server import create_server, server_url


@pytest.fixture
def running_server():
    server = create_server("127.0.0.1", 0, offline=True)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield server, server_url(server)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    assert not thread.is_alive()


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_app_starts_serves_demo_and_shuts_down(running_server):
    server, url = running_server
    with urllib.request.urlopen(url, timeout=5) as response:
        html = response.read().decode("utf-8")
    assert response.status == 200
    assert "RaceCoach" in html
    assert "Loading demo" in html
    health = get_json(url + "api/health")
    assert health["status"] == "ok"
    assert health["offline"] is True
    demo = get_json(url + "api/demo")
    assert demo["demo"] is True
    assert demo["analysis"]["summary"]["completed_zones"] == 4
    assert len(demo["analysis"]["zones"]) == 5
    assert demo["reference_laps"][0]["label"] == "Lap 1"


def test_section_selection_changes_displayed_measurement(running_server):
    _, url = running_server
    demo = get_json(url + "api/demo")
    zones = demo["analysis"]["zones"]
    first_message = zones[0]["message"]
    second_message = zones[1]["message"]
    assert first_message != second_message
    assert "12 metres earlier" in first_message
    assert zones[0]["delta"]["section_time_s"] == pytest.approx(0.18, abs=0.001)
    assert zones[1]["delta"]["section_time_s"] == pytest.approx(0.0, abs=0.001)


def test_analyze_endpoint_accepts_uploaded_csvs(running_server, demo_csvs):
    _, url = running_server
    ref_text, prac_text = demo_csvs
    status, payload = post_json(
        url + "api/analyze",
        {
            "reference": {"name": "reference lap.csv", "csv": ref_text},
            "practice": {"name": "practice lap.csv", "csv": prac_text},
            "max_gap_m": 25,
        },
    )
    assert status == 200
    assert payload["demo"] is False
    assert payload["reference"]["source"] == "reference lap.csv"
    assert payload["analysis"]["summary"]["completed_zones"] == 4
    assert "grid" in payload["analysis"]
    assert len(payload["analysis"]["grid"]["distance_m"]) > 100


def test_analyze_endpoint_rejects_bad_csv(running_server):
    _, url = running_server
    status, payload = post_json(
        url + "api/analyze",
        {
            "reference": {"name": "bad.csv", "csv": "not a telemetry file"},
            "practice": {"name": "bad.csv", "csv": "not a telemetry file"},
        },
    )
    assert status == 400
    assert "error" in payload


def test_web_assets_have_no_external_urls(running_server):
    _, url = running_server
    for path in ("", "app.js", "styles.css"):
        with urllib.request.urlopen(url + path, timeout=5) as response:
            text = response.read().decode("utf-8")
        assert "http://" not in text
        assert "https://" not in text
