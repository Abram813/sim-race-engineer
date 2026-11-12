"""Small local web server for the RaceCoach UI.

The app is intentionally dependency-free.  It binds to loopback by default,
serves four static files from the package, and exposes a tiny JSON API.
"""

from __future__ import annotations

import json
import platform
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from .analysis import AnalysisOptions, analyze
from .csvio import parse_csv
from .demo import demo_analysis, demo_csv_texts, demo_payload
from .model import CsvFormatError, TelemetryError

WEB_DIR = Path(__file__).parent / "web"
MAX_BODY_BYTES = 25_000_000


class RaceCoachServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, *, offline: bool = False, quiet: bool = True):
        super().__init__(address, handler)
        self.offline = offline
        self.quiet = quiet


class Handler(BaseHTTPRequestHandler):
    server: RaceCoachServer

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 - stdlib API
        if not self.server.quiet:
            super().log_message(fmt, *args)

    # -- helpers ---------------------------------------------------------
    def _send_bytes(self, data: bytes, content_type: str, status: int = 200, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'self'",
        )
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self._send_bytes(data, "application/json; charset=utf-8", status)

    def _error(self, message: str, status: int = 400) -> None:
        self._send_json({"error": message}, status)

    def _static(self, filename: str, content_type: str) -> None:
        path = (WEB_DIR / filename).resolve()
        if not path.is_relative_to(WEB_DIR.resolve()) or not path.is_file():
            self._error("Not found.", HTTPStatus.NOT_FOUND)
            return
        self._send_bytes(path.read_bytes(), content_type)

    # -- HTTP verbs ------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._static("index.html", "text/html; charset=utf-8")
        elif path == "/app.js":
            self._static("app.js", "text/javascript; charset=utf-8")
        elif path == "/styles.css":
            self._static("styles.css", "text/css; charset=utf-8")
        elif path == "/favicon.svg":
            self._static("favicon.svg", "image/svg+xml")
        elif path == "/api/health":
            self._send_json(
                {
                    "status": "ok",
                    "version": __version__,
                    "offline": self.server.offline,
                    "platform": platform.platform(),
                    "python": sys.version.split()[0],
                }
            )
        elif path == "/api/demo":
            self._send_json(self._demo_payload())
        elif path == "/api/demo/reference.csv":
            reference, _ = demo_csv_texts()
            self._send_bytes(
                reference.encode("utf-8"),
                "text/csv; charset=utf-8",
                extra={"Content-Disposition": 'attachment; filename="demo_reference_lap.csv"'},
            )
        elif path == "/api/demo/practice.csv":
            _, practice = demo_csv_texts()
            self._send_bytes(
                practice.encode("utf-8"),
                "text/csv; charset=utf-8",
                extra={"Content-Disposition": 'attachment; filename="demo_practice_lap.csv"'},
            )
        else:
            self._error("Not found.", HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        path = urlparse(self.path).path
        if path != "/api/analyze":
            self._error("Not found.", HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._error("Invalid Content-Length.")
            return
        if length <= 0:
            self._error("Request body is empty.")
            return
        if length > MAX_BODY_BYTES:
            self._error("Request body is too large.", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._error(f"Invalid JSON: {exc}")
            return
        try:
            self._send_json(self._analyse_payload(body))
        except (CsvFormatError, TelemetryError, ValueError) as exc:
            self._error(str(exc))
        except Exception as exc:  # pragma: no cover - defensive boundary
            self._error(f"Unexpected analysis error: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)

    # -- API implementation ---------------------------------------------
    def _demo_payload(self) -> dict:
        reference, practice, result = demo_analysis()
        payload = demo_payload()
        payload.update(
            {
                "reference_laps": [reference.summary()],
                "practice_laps": [practice.summary()],
                "reference_selected_index": 0,
                "practice_selected_index": 0,
                "analysis": result.to_dict(include_grid=True),
            }
        )
        return payload

    def _analyse_payload(self, body: dict) -> dict:
        if not isinstance(body, dict):
            raise ValueError("Request body must be a JSON object.")
        reference = _source(body.get("reference"), "reference")
        practice = _source(body.get("practice"), "practice")
        ref_set = parse_csv(reference["csv"], source=reference["name"])
        prac_set = parse_csv(practice["csv"], source=practice["name"])

        ref_index = _lap_index(body.get("reference_lap_index"), len(ref_set.laps), ref_set.default_index())
        prac_index = _lap_index(body.get("practice_lap_index"), len(prac_set.laps), prac_set.default_index())

        max_gap = _number(body.get("max_gap_m"), 25.0, 1.0, 1000.0)
        brake_threshold = _number(body.get("brake_threshold"), 0.05, 0.0, 1.0)
        grid_step = _number(body.get("grid_step_m"), 5.0, 0.5, 100.0)
        zone_end = _number(body.get("zone_end_after_release_m"), 30.0, 5.0, 500.0)
        options = AnalysisOptions(
            max_gap_m=max_gap,
            brake_threshold=brake_threshold,
            grid_step_m=grid_step,
            zone_end_after_release_m=zone_end,
        )
        result = analyze(ref_set.laps[ref_index], prac_set.laps[prac_index], options)
        return {
            "demo": False,
            "reference": {
                "source": reference["name"],
                "laps": ref_set.summaries(),
                "selected_index": ref_index,
                "warnings": ref_set.warnings,
            },
            "practice": {
                "source": practice["name"],
                "laps": prac_set.summaries(),
                "selected_index": prac_index,
                "warnings": prac_set.warnings,
            },
            "reference_laps": ref_set.summaries(),
            "practice_laps": prac_set.summaries(),
            "reference_selected_index": ref_index,
            "practice_selected_index": prac_index,
            "analysis": result.to_dict(include_grid=True),
        }


def _source(value, name: str) -> dict:
    if isinstance(value, str):
        return {"name": f"{name}.csv", "csv": value}
    if not isinstance(value, dict):
        raise ValueError(f"Missing {name} CSV.")
    csv_text = value.get("csv")
    if not isinstance(csv_text, str) or not csv_text.strip():
        raise ValueError(f"Missing {name} CSV text.")
    filename = value.get("name")
    if not isinstance(filename, str) or not filename.strip():
        filename = f"{name}.csv"
    return {"name": filename[:200], "csv": csv_text}


def _lap_index(value, count: int, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        index = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Lap selection must be an integer index.") from exc
    if index < 0 or index >= count:
        raise ValueError(f"Lap selection {index} is out of range (0-{count - 1}).")
    return index


def _number(value, default: float, low: float, high: float) -> float:
    if value is None or value == "":
        return default
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Numeric option is not a number.") from exc
    return max(low, min(high, number))


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    offline: bool = False,
    quiet: bool = True,
) -> RaceCoachServer:
    return RaceCoachServer((host, port), Handler, offline=offline, quiet=quiet)


def server_url(server: RaceCoachServer) -> str:
    host, port = server.server_address[:2]
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    return f"http://{host}:{port}/"
