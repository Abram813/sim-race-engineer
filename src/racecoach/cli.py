"""Command line entry points for RaceCoach."""

from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from pathlib import Path

from . import __version__
from .analysis import AnalysisOptions, AnalysisResult, analyze
from .csvio import read_csv_file
from .demo import export_demo
from .model import CsvFormatError, LapSet, TelemetryError
from .server import create_server, server_url


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _load_laps(path: str, max_gap_m: float) -> LapSet:
    return read_csv_file(path, max_gap_m=max_gap_m)


def _select_lap(lap_set: LapSet, index: int | None, name: str):
    if index is None:
        return lap_set.laps[lap_set.default_index()]
    if index < 0 or index >= len(lap_set.laps):
        raise TelemetryError(
            f"{name} lap index {index} is out of range; the file has "
            f"{len(lap_set.laps)} lap(s) (0-{len(lap_set.laps) - 1})."
        )
    return lap_set.laps[index]


def _options(args) -> AnalysisOptions:
    return AnalysisOptions(
        max_gap_m=getattr(args, "max_gap_m", 25.0),
        brake_threshold=getattr(args, "brake_threshold", 0.05),
        grid_step_m=getattr(args, "grid_step_m", 5.0),
        zone_end_after_release_m=getattr(args, "zone_end_after_release_m", 30.0),
    )


def _signed(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if abs(value) < 10 ** (-digits) / 2:
        return f"{0:.{digits}f}"
    return f"{value:+.{digits}f}"


def _print_analysis_human(
    reference_name: str,
    practice_name: str,
    ref_set: LapSet,
    prac_set: LapSet,
    result: AnalysisResult,
) -> None:
    ref = result.reference
    prac = result.practice
    print("RaceCoach analysis")
    print(f"Reference: {reference_name} ({ref.label}, {ref.start_m:.0f}-{ref.end_m:.0f} m, {ref.duration_s:.2f} s)")
    print(f"Practice:  {practice_name} ({prac.label}, {prac.start_m:.0f}-{prac.end_m:.0f} m, {prac.duration_s:.2f} s)")
    summary = result.summary
    print(
        f"Zones: {summary['completed_zones']} complete, {summary['skipped_zones']} skipped "
        f"(of {summary['braking_zones']})"
    )
    print(
        f"Overlap: {summary['overlap_start_m']:.0f}-{summary['overlap_end_m']:.0f} m "
        f"({summary['overlap_distance_m']:.0f} m), "
        f"total time delta {_signed(summary['total_time_delta_s'], 3)} s"
    )
    warnings = list(dict.fromkeys(ref_set.warnings + prac_set.warnings))
    if warnings:
        print("Data warnings:")
        for warning in warnings[-8:]:
            print(f"  - {warning}")
    print()

    for zone in result.zones:
        print(f"[{zone.index}] {zone.label}  {zone.start_m:.0f}-{zone.end_m:.0f} m  {zone.status.upper()}")
        if zone.status == "skipped":
            print(f"    {zone.message}")
            print()
            continue
        assert zone.reference is not None and zone.practice is not None and zone.delta is not None
        ref_m = zone.reference
        prac_m = zone.practice
        delta = zone.delta
        if prac_m.brake_start_m is None:
            brake_line = f"ref {ref_m.brake_start_m:.0f} m, practice: no brake"
        elif abs(delta.brake_start_m or 0) < 1.0:
            brake_line = f"ref {ref_m.brake_start_m:.0f} m, practice {prac_m.brake_start_m:.0f} m (same point)"
        else:
            direction = "earlier" if (delta.brake_start_m or 0) > 0 else "later"
            brake_line = (
                f"ref {ref_m.brake_start_m:.0f} m, practice {prac_m.brake_start_m:.0f} m "
                f"({abs(delta.brake_start_m or 0):.0f} m {direction})"
            )
        print(f"    Brake start: {brake_line}")
        print(
            f"    Min speed:   ref {ref_m.min_speed_kmh:.1f}, practice {prac_m.min_speed_kmh:.1f} km/h "
            f"({_signed(delta.min_speed_kmh, 1)} km/h)"
        )
        print(
            f"    Section:     ref {ref_m.section_time_s:.2f}, practice {prac_m.section_time_s:.2f} s "
            f"({_signed(delta.section_time_s, 2)} s)"
        )
        print(f"    Feedback:    {zone.message}")
        for note in zone.notes:
            print(f"    Note:        {note}")
        print()

    skipped = [zone for zone in result.zones if zone.status == "skipped"]
    if skipped:
        print("Skipped sections:")
        for zone in skipped:
            print(f"  [{zone.index}] {zone.start_m:.0f}-{zone.end_m:.0f} m: {zone.skip_reason}")
        print()
    if result.gaps["reference"] or result.gaps["practice"]:
        print("Large data gaps:")
        for label, gaps in (("Reference", result.gaps["reference"]), ("Practice", result.gaps["practice"])):
            for gap in gaps:
                print(
                    f"  {label}: {gap['gap_m']:.0f} m between {gap['start_m']:.0f} m and "
                    f"{gap['end_m']:.0f} m ({gap['gap_s']:.2f} s)"
                )
        print()
    print(f"Replay messages: {len(result.replay_events)} (one per completed braking zone)")


def cmd_analyze(args) -> int:
    try:
        ref_set = _load_laps(args.reference, args.max_gap_m)
        prac_set = _load_laps(args.practice, args.max_gap_m)
        reference = _select_lap(ref_set, args.ref_lap, "Reference")
        practice = _select_lap(prac_set, args.prac_lap, "Practice")
        result = analyze(reference, practice, _options(args))
    except (CsvFormatError, TelemetryError, OSError) as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result.to_dict(include_grid=False), indent=2, ensure_ascii=False))
    else:
        _print_analysis_human(args.reference, args.practice, ref_set, prac_set, result)
    return 0


def cmd_replay(args) -> int:
    try:
        ref_set = _load_laps(args.reference, args.max_gap_m)
        prac_set = _load_laps(args.practice, args.max_gap_m)
        reference = _select_lap(ref_set, args.ref_lap, "Reference")
        practice = _select_lap(prac_set, args.prac_lap, "Practice")
        result = analyze(reference, practice, _options(args))
    except (CsvFormatError, TelemetryError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print(f"Replay: {len(result.replay_events)} completed braking zone(s)")
    for event in result.replay_events:
        print(f"[{event['distance_m']:.0f} m] {event['message']}")
        if args.delay > 0:
            import time

            time.sleep(args.delay)
    print(f"Replay complete: {len(result.replay_events)} message(s), one per completed braking zone.")
    return 0


def cmd_export_demo(args) -> int:
    ref_path, prac_path = export_demo(args.out)
    print(f"Wrote {ref_path}")
    print(f"Wrote {prac_path}")
    return 0


def cmd_serve(args) -> int:
    offline = args.offline or _truthy(os.environ.get("RACECOACH_OFFLINE"))
    no_browser = args.no_browser or _truthy(os.environ.get("RACECOACH_NO_BROWSER"))
    server = None
    last_error: OSError | None = None
    candidates = [0] if args.port == 0 else list(range(args.port, args.port + 20))
    for candidate in candidates:
        try:
            server = create_server(args.host, candidate, offline=offline, quiet=not args.verbose)
            break
        except OSError as exc:
            last_error = exc
    if server is None:
        print(f"Error: could not bind a local port: {last_error}", file=sys.stderr)
        return 2

    url = server_url(server)
    print(f"RACECOACH_URL={url}", flush=True)
    print(f"RaceCoach {__version__} is running at {url}")
    print("Press Ctrl+C to stop.")
    if not no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        # On Windows, a console Ctrl+Break should behave like Ctrl+C.  The
        # default SIGBREAK action can terminate the process without running the
        # cleanup below, so route it through Python's KeyboardInterrupt handler.
        import signal

        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, signal.default_int_handler)
    except (ValueError, OSError):
        pass
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        print("Stopped cleanly.", flush=True)
    return 0


def _add_analysis_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--reference", required=True, help="Reference lap CSV path")
    parser.add_argument("--practice", required=True, help="Practice lap CSV path")
    parser.add_argument("--ref-lap", type=int, default=None, help="Reference lap index (0-based)")
    parser.add_argument("--prac-lap", type=int, default=None, help="Practice lap index (0-based)")
    parser.add_argument("--max-gap-m", type=float, default=25.0, help="Flag distance gaps above this many metres")
    parser.add_argument("--brake-threshold", type=float, default=0.05, help="Brake pedal threshold (0..1)")
    parser.add_argument("--grid-step-m", type=float, default=5.0, help="Distance grid step for the chart")
    parser.add_argument(
        "--zone-end-after-release-m",
        type=float,
        default=30.0,
        help="Fallback section end after brake release",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="racecoach", description="Distance-based AC/ACC lap coaching")
    parser.add_argument("--version", action="version", version=f"racecoach {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Start the local web app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765, help="Port (0 picks a free port)")
    serve.add_argument("--no-browser", action="store_true", help="Do not open a browser")
    serve.add_argument("--offline", action="store_true", help="Mark the app as offline (no external requests)")
    serve.add_argument("--verbose", action="store_true", help="Log HTTP requests")
    serve.set_defaults(func=cmd_serve)

    analyze_p = sub.add_parser("analyze", help="Analyze two CSV laps in the terminal")
    _add_analysis_args(analyze_p)
    analyze_p.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    analyze_p.set_defaults(func=cmd_analyze)

    replay_p = sub.add_parser("replay", help="Print one coaching message per completed braking zone")
    _add_analysis_args(replay_p)
    replay_p.add_argument("--delay", type=float, default=0.0, help="Seconds to wait between messages")
    replay_p.set_defaults(func=cmd_replay)

    demo_p = sub.add_parser("export-demo", help="Write the built-in demo CSVs")
    demo_p.add_argument("--out", default="examples", help="Output directory")
    demo_p.set_defaults(func=cmd_export_demo)

    version_p = sub.add_parser("version", help="Print the version")
    version_p.set_defaults(func=lambda _args: (print(f"racecoach {__version__}"), 0)[1])
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["serve"]
    elif argv[0].startswith("-") and argv[0] not in ("--version", "-V", "--help", "-h"):
        argv = ["serve"] + argv
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
