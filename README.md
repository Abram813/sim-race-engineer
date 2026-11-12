# RaceCoach

RaceCoach is a local, offline lap-coaching app for **Assetto Corsa** and **Assetto Corsa Competizione** telemetry. It loads a reference lap and a practice lap from CSV, aligns them by distance, finds the reference lap's braking zones, and reports measurable differences:

> You started braking 12 metres earlier and took 0.18 seconds longer through this section (minimum speed 2.0 km/h lower).

The app is dependency-free at runtime: Python's standard library serves a small local web UI with canvas charts. It never uploads telemetry and makes no external requests.

## Quick start

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run python -m racecoach
```

The app opens `http://127.0.0.1:8765/` in your browser and loads a deterministic demo automatically. If port 8765 is busy it tries the next ports; `--port 0` picks a free port.

Useful variants:

```bash
uv run python -m racecoach serve --no-browser --port 0 --offline
uv run racecoach analyze --reference "examples/reference_lap.csv" --practice "examples/practice_lap.csv"
uv run racecoach replay  --reference "examples/reference_lap.csv" --practice "examples/practice_lap.csv"
uv run racecoach export-demo --out "demo laps"
```

All paths are quoted because they may contain spaces. The exact same commands work from a directory whose full path contains spaces.

## CSV format

One row per telemetry sample, with this header:

| Column | Meaning | Units / range |
| --- | --- | --- |
| `lap_number` | Lap identifier | integer |
| `distance_m` | Distance travelled in the lap | metres |
| `elapsed_s` | Elapsed lap time at this sample | seconds |
| `speed_kmh` | Vehicle speed | km/h |
| `throttle` | Throttle pedal | 0–1 |
| `brake` | Brake pedal | 0–1 |

```csv
lap_number,distance_m,elapsed_s,speed_kmh,throttle,brake
1,0.000,0.000,240.00,1.000,0.000
1,2.000,0.030,240.00,1.000,0.000
```

The parser also accepts:

- UTF-8 with or without a BOM.
- Comma, semicolon, or tab delimiters.
- Decimal commas in semicolon/tab files.
- Common header aliases such as `lap`, `distance`, `time`, `speed`, `gas`, `throttle_pct`.
- Pedal values exported as 0–100 (divided by 100 once, with a warning).
- Multiple laps in one file, including distance resets that split a lap into segments.

Malformed rows are skipped with a warning. A distance jump larger than the gap threshold (25 m by default) is preserved and flagged; RaceCoach never interpolates across it.

## What the analysis does

1. **Find braking zones in the reference lap.** A zone starts when `brake` crosses the threshold (0.05), and ends at the first throttle application after brake release. Nearby brake applications are merged. Very short or very light applications are ignored.
2. **Find the practice braking point.** It searches a window around the reference point (150 m earlier to 60 m later) for a brake-pedal transition. If practice was already braking at the window edge, the shift is reported as a lower bound.
3. **Compare at identical distances.** The practice lap is interpolated at the reference section's start and end distances. The section time is the difference in elapsed time, not a resampled estimate. Minimum speed is the lowest sampled speed in the section.
4. **Skip incomplete sections.** If either lap lacks data for the section, or a flagged gap overlaps it, the section is skipped with a reason. Replay only emits messages for completed sections.
5. **Report measurable deltas.** Every message includes the braking-point shift in metres, the section time delta in seconds, and the minimum-speed delta in km/h when they exceed the display thresholds.

The reference lap defines the sections. If the reference is recorded with a different driving line, the section boundaries may not match another driver's braking points; that is a deliberate, explainable choice.

## Demo

The built-in demo is generated deterministically by `racecoach/synth.py`:

| Zone | Reference brake | Practice brake | Section time | Min speed | Result |
| --- | --- | --- | --- | --- | --- |
| 1 | 300 m | 288 m (12 m earlier) | +0.18 s longer | 2.0 km/h lower | complete |
| 2 | 700 m | 700 m (same) | 0.00 s | same | complete |
| 3 | 1150 m | 1158 m (8 m later) | 0.09 s shorter | 1.5 km/h higher | complete |
| 4 | 1600 m | — | — | — | skipped: 44 m practice gap |
| 5 | 2050 m | 2030 m (20 m earlier) | +0.25 s longer | 3.0 km/h lower | complete |

The demo therefore has **4 completed braking zones and 4 replay messages**, plus one explicitly skipped section. The UI shows the gap in the data-quality panel.

Download the demo files from the UI or write them with:

```bash
uv run racecoach export-demo --out "demo laps"
```

## Replay

The web UI replays the lap by distance. Press **Play**; a cursor moves along the distance axis at the reference lap's speed, scaled by the selected multiplier (1×–32×). When the cursor crosses the end of a completed braking zone, exactly one coaching message is appended. Skipped zones never produce a message.

The CLI equivalent prints the same events without animation:

```bash
uv run racecoach replay --reference "examples/reference_lap.csv" --practice "examples/practice_lap.csv"
```

## Offline guarantee

Runtime:

- The server binds to `127.0.0.1` only by default.
- The UI loads only `/`, `/app.js`, `/styles.css`, and `/favicon.svg` from the local server.
- There are no CDNs, web fonts, analytics, or telemetry uploads.
- The Content-Security-Policy restricts scripts, styles, images, and connections to the local origin.

Tests:

- `tests/conftest.py` monkeypatches `socket.socket.connect`, `socket.create_connection`, and `socket.getaddrinfo` so any non-loopback address raises `NetworkBlocked`.
- The suite runs with `RACECOACH_OFFLINE=1`.
- `tests/test_no_network.py` proves that an external connection is blocked.

After dependencies are installed, the test suite and app need no network:

```bash
uv run pytest
```

On Windows PowerShell:

```powershell
$env:RACECOACH_OFFLINE = "1"
uv run pytest
```

## Verification commands

Run these from the repository root. They are the exact commands used in CI, including from a path containing spaces.

```bash
# Unit and API tests (offline guard active)
uv run pytest

# Start the real app, load the demo, change the selected section, upload CSVs, Ctrl+C
uv run python scripts/smoke.py

# Headless Chromium: demo, section change, replay messages, file upload, clean shutdown
uv sync --all-groups
uv run playwright install chromium
uv run python scripts/ui_smoke.py
```

`scripts/smoke.py` prints the OS, CPU architecture, Python version, and uv version, and exits non-zero unless the app starts, serves the demo, changes a section measurement, accepts an upload, and shuts down cleanly after Ctrl+C (Ctrl+Break on Windows).

`scripts/ui_smoke.py` blocks every non-loopback browser request and fails if one is attempted.

## Verified environments

The GitHub Actions workflow runs a fresh clone in a path containing spaces on Windows and macOS. The table below records the verification run used for this handover; later README-only commits do not change the measured results.

| Runner | OS / CPU architecture | Python | uv | Unit + API tests | App smoke | UI smoke |
| --- | --- | --- | --- | --- | --- | --- |
| `windows-latest` | Windows Server 2025, x86_64 (AMD64) | 3.12.10 | 0.13.7 | pass | pass | pass |
| `macos-15` | macOS 15.8.2, arm64 (Apple Silicon) | 3.12.10 | 0.13.7 | pass | pass | pass |
| `macos-15-intel` | macOS 15.7.9, x86_64 (Intel) | 3.12.10 | 0.13.7 | pass | pass | pass |

CI run: [43295300842](https://github.com/Abram813/sim-race-engineer/actions/runs/43295300842), commit `1eea73c`. The environment artifacts show the executable path inside `fresh clone/racecoach`, confirming the path-with-spaces run. Verified Mac architectures: Apple Silicon arm64 and Intel x86_64.

Local verification on the development machine (not a CI claim):

| OS / CPU architecture | Python | uv | Tests | App smoke | UI smoke |
| --- | --- | --- | --- | --- | --- |
| macOS 26.6.2, arm64 (Apple M1 Pro) | 3.14.2 | 0.13.7 | 33 passed | pass | pass |

A second local check cloned the repository into a path containing spaces (`.../fresh clone/racecoach`) and ran the exact README commands: `uv sync --all-groups`, `uv run pytest` (33 passed), `uv run python scripts/smoke.py` (`SMOKE PASS`), and `uv run python scripts/ui_smoke.py` (`UI SMOKE PASS`). The smoke starts the app, loads the demo, changes the selected section, uploads a CSV, and shuts down cleanly; the UI smoke also confirms no external requests.

## Live capture on Windows

Live shared-memory capture is a separate repository:

**<https://github.com/Abram813/ac-shared-memory>**

It contains the Windows-only `accapture` command, which reads the documented read-only AC/ACC shared-memory mappings and writes the same CSV format. It can record a session and then run:

```powershell
accapture record --game acc --out "laps\session.csv" --laps 1 --reference "reference lap.csv"
```

or analyse an existing recording:

```powershell
accapture feedback --reference "reference lap.csv" --session "laps\session.csv"
```

That repository also documents the exact running-game test procedure. Actual game testing is separate from packet-decoding tests and cannot be performed on macOS.

## Limitations

- Braking zones come from the reference lap's brake pedal only. A corner taken without braking is not a zone.
- The app compares one pair of laps at a time; it does not merge multiple sessions or build a track map.
- Minimum speed is sampled at the recorded distance grid. Very sparse CSVs can miss the true minimum; the gap warning is the signal to record at a higher rate.
- The app does not read AC/ACC files directly. Use the Windows capture agent or export CSV from your telemetry tool.
- Tyre, fuel, setup, and weather channels are not analysed.
- The reference lap's section boundaries are used even if the practice lap takes a different line.

## Troubleshooting

**The browser does not open.** The server prints `RACECOACH_URL=...`. Open that URL manually, or run with `--no-browser` in a terminal and copy the URL.

**Port already in use.** RaceCoach tries the next 20 ports automatically, or use `--port 0`.

**The CSV will not load.** Check the header names and that each row has a value for `distance_m`, `elapsed_s`, `speed_kmh`, `throttle`, and `brake`. The error message lists what was found and what is required.

**A section is skipped.** Open the Data quality panel. A skipped section means one lap did not cover the same distance range or a large gap crossed it. The reason is printed verbatim.

**The demo shows one skipped section.** That is intentional: the practice lap has a 44 m data gap at zone 4. It demonstrates the skip-and-flag behaviour.

## Two-minute VS Code walkthrough

1. **Open the folder.** In VS Code, choose **File → Open Folder** and select this repository. Open a terminal with **Terminal → New Terminal**.
2. **Install and start.** Run `uv sync`, then `uv run python -m racecoach`. The browser opens the demo. If it does not, open the `RACECOACH_URL` printed in the terminal.
3. **Read the headline.** The first braking zone is selected. The feedback panel says: “You started braking 12 metres earlier and took 0.18 seconds longer through this section (minimum speed 2.0 km/h lower).”
4. **Change the section.** Click **Braking zone 2**. The section-time delta changes from `+0.18 s` to `0.00 s`, and the message becomes “Matched the reference through this section.” Click **Braking zone 3** to see `-0.09 s` and “8 metres later”.
5. **Replay.** Leave the replay speed at 32× and click **Reset**, then **Play**. The cursor moves across the charts. When it finishes, the message panel contains exactly four messages — one per completed braking zone — and the skipped zone 4 produces none.
6. **Inspect the gap.** Look at the Data quality panel: it reports the 44 m practice gap and explains why zone 4 was skipped.
7. **Load your own laps.** In `src/racecoach/web/index.html`, note the file inputs. In the browser, choose a reference CSV and a practice CSV, then click **Analyze laps**. The status changes to “Analysis loaded”. Use the lap selectors if a file contains multiple laps.
8. **Run the checks.** In the terminal, press `Ctrl+C` and confirm “Stopped cleanly.” Then run `uv run pytest`, `uv run python scripts/smoke.py`, and `uv run python scripts/ui_smoke.py`. Each should finish with a pass message.
9. **Find the code.** `src/racecoach/analysis.py` contains the braking-zone and delta logic; `src/racecoach/web/app.js` contains the charts and replay; `tests/test_analysis_shift.py` contains the known 12 m / 0.18 s regression.
