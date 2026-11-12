"""Built-in demo data and demo export helpers."""

from __future__ import annotations

from pathlib import Path

from .analysis import AnalysisOptions, AnalysisResult, analyze
from .csvio import write_lap_csv, write_csv_text
from .model import Lap
from .synth import demo_laps


def demo_analysis(options: AnalysisOptions | None = None) -> tuple[Lap, Lap, AnalysisResult]:
    reference, practice = demo_laps()
    return reference, practice, analyze(reference, practice, options)


def demo_payload(options: AnalysisOptions | None = None) -> dict:
    reference, practice, result = demo_analysis(options)
    return {
        "demo": True,
        "reference": reference.summary(),
        "practice": practice.summary(),
        "analysis": result.to_dict(include_grid=True),
        "sources": {
            "reference": "demo reference lap (synthetic, 2400 m)",
            "practice": "demo practice lap (synthetic, 2400 m)",
        },
    }


def demo_csv_texts() -> tuple[str, str]:
    reference, practice = demo_laps()
    return write_csv_text([reference]), write_csv_text([practice])


def export_demo(out_dir: str | Path) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    reference, practice = demo_laps()
    ref_path = write_lap_csv(reference, out_dir / "reference_lap.csv")
    prac_path = write_lap_csv(practice, out_dir / "practice_lap.csv")
    return ref_path, prac_path
