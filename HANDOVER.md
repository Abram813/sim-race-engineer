# Handover report

Date: 2026-11-12

## Repositories

| Project | Published URL | Local path | Branch |
| --- | --- | --- | --- |
| RaceCoach app | <https://github.com/Abram813/sim-race-engineer> | `/Users/abram/Documents/f1-lab/sim-race-engineer` | `main` |
| Windows capture agent | <https://github.com/Abram813/ac-shared-memory> | `/Users/abram/Documents/f1-lab/ac-shared-memory` | `main` |

Documentation commits at verification time: `87d5de6` (RaceCoach) and `43a2c3e` (capture). Later documentation-only commits do not change the measured results.
Verification CI runs: [RaceCoach 43295300842](https://github.com/Abram813/sim-race-engineer/actions/runs/43295300842) and [capture 43295553422](https://github.com/Abram813/ac-shared-memory/actions/runs/43295553422).

## Launch commands

RaceCoach:

```bash
cd "/Users/abram/Documents/f1-lab/sim-race-engineer"
uv sync --all-groups
uv run python -m racecoach
```

RaceCoach CLI check:

```bash
uv run racecoach analyze --reference "examples/reference_lap.csv" --practice "examples/practice_lap.csv"
uv run racecoach replay  --reference "examples/reference_lap.csv" --practice "examples/practice_lap.csv"
```

Capture demo (works on macOS and Windows):

```bash
cd "/Users/abram/Documents/f1-lab/ac-shared-memory"
uv sync --all-groups
uv run accapture record --demo --out "demo laps/session.csv" --laps 1
```

Capture live (Windows with AC/ACC running):

```powershell
uv run accapture probe --game acc
uv run accapture record --game acc --out "laps\reference lap.csv" --laps 1
uv run accapture record --game acc --out "laps\practice lap.csv" --laps 1 --reference "laps\reference lap.csv" --racecoach "C:\path\to\sim-race-engineer\.venv\Scripts\racecoach.exe"
```

## Actual CI results

The CI workflows fresh-clone each repository into a directory containing spaces (`fresh clone/racecoach` or `fresh clone/accapture`), then run the offline tests and smoke test. Environment values below come from the uploaded `environment.txt` artifacts.

### RaceCoach app

| Runner | OS / CPU architecture | Python | uv | Unit + API tests | App smoke | UI smoke |
| --- | --- | --- | --- | --- | --- | --- |
| `windows-latest` | Windows Server 2025, x86_64 (AMD64) | 3.12.10 | 0.13.7 | pass | pass | pass |
| `macos-15` | macOS 15.8.2, arm64 (Apple Silicon) | 3.12.10 | 0.13.7 | pass | pass | pass |
| `macos-15-intel` | macOS 15.7.9, x86_64 (Intel) | 3.12.10 | 0.13.7 | pass | pass | pass |

Verified Mac architectures: Apple Silicon arm64 and Intel x86_64.

The app smoke starts the real server, loads the demo, changes the selected braking section and verifies the measurement changes, uploads the demo CSVs, and shuts down cleanly. The browser UI smoke repeats the demo, section change, replay messages, and upload with Playwright and fails on any non-loopback request.

### Windows capture agent

| Runner | OS / CPU architecture | Python | uv | Tests | Smoke |
| --- | --- | --- | --- | --- | --- |
| `windows-x64` | Windows Server 2025, x86_64 (AMD64) | 3.12.10 | 0.13.7 | 44 passed, 3 skipped | pass |
| `macos-arm64` | macOS 15.8.2, arm64 (Apple Silicon) | 3.12.10 | 0.13.7 | 43 passed, 4 skipped | pass |
| `macos-x64` | macOS 15.7.9, x86_64 (Intel) | 3.12.10 | 0.13.7 | 43 passed, 4 skipped | pass |

On Windows, the four fake-shared-memory tests run against real Windows mappings; the three skipped tests are assertions for the non-Windows error path. On macOS, the four Windows mapping tests are skipped.

### Local verification

Local machine: macOS 26.6.2, arm64 (Apple M1 Pro), Python 3.14.2, uv 0.13.7.

- RaceCoach: 33 tests passed; app smoke passed; Playwright UI smoke passed.
- Capture: 43 passed, 4 skipped; CLI smoke passed.
- Capture demo feedback against the RaceCoach reference lap: 5 complete braking zones and one feedback message per zone.
- Offline runs with external requests blocked: RaceCoach `RACECOACH_OFFLINE=1` 33 passed; capture `ACCAPTURE_OFFLINE=1` 43 passed, 4 skipped. Both test suites install a network guard that blocks non-loopback sockets and DNS.
- Exact README commands were run from local fresh clones whose paths contained spaces (`.../fresh clone/racecoach` and `.../fresh clone/accapture`). RaceCoach: 33 passed, app smoke passed, UI smoke passed, and `racecoach analyze` produced the expected 12 m / 0.18 s first-zone feedback. Capture: 43 passed, 4 skipped, smoke passed, demo recording produced 1201 rows, and feedback produced 5 complete zones.

## Checks not performed

### Actual running AC/ACC game test

Not performed. This development environment is macOS and has no Windows host or AC/ACC installation. The packet-decoding tests and Windows fake-mapping tests are not substitutes for a real game test.

Exact commands to run on Windows with AC or ACC in a session:

```powershell
cd "C:\path\to\ac-shared-memory"
uv run accapture probe --game acc
```

Expected: exit code `0`; JSON with `graphics.status_name == "live"`, a plausible `physics.speed_kmh`, and `graphics.distance_traveled_m` changing as the car moves.

```powershell
uv run accapture record --game acc --out "laps\reference lap.csv" --laps 1
```

Expected: `Recording lap 1...`, `Saved lap 1 (... samples).`, and `Recorded 1 completed lap(s)`. The CSV has `lap_number,distance_m,elapsed_s,speed_kmh,throttle,brake` and `lap_number` 1.

```powershell
uv run accapture record --game acc --out "laps\practice lap.csv" --laps 1 --reference "laps\reference lap.csv" --racecoach "C:\path\to\sim-race-engineer\.venv\Scripts\racecoach.exe"
```

Expected: the practice CSV is written, RaceCoach runs, and one feedback line is printed per completed braking zone.

Additional expected behavior:

- Pause: `Game paused; recording paused.`; resume: `Game resumed.` The pause interval must not inflate `elapsed_s`.
- New lap with `--laps 2`: `Saved lap 1 (... samples).` then `Recording lap 2...`; the CSV contains lap numbers 1 and 2.
- Close the game after a few seconds: a `Game closed` message, `Saved partial lap ...`, and a non-empty CSV.
- Start `record` with the game closed: `Waiting for ACC shared memory...` until `--wait-s` expires, then exit code `3` with a message to start the game.
- Start `record` before any telemetry: exit code `4` if no rows could be written.

## Known limitations

- Braking zones come only from the reference lap's brake pedal. A corner taken without braking is not a zone.
- The app compares one reference/practice lap pair at a time.
- Very sparse CSVs can miss the true minimum speed; the gap warning is the signal to record at a higher rate.
- Tyre, fuel, setup, and weather channels are not analysed.
- The capture agent reads only the documented prefixes; it does not mirror every game version's full structure.
