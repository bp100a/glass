"""Command line entry for the glass cutting planner."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fractions import Fraction

from glasscut.model import CutError, load_job
from glasscut.optimize import solve
from glasscut.report import write_report
from glasscut.units import UnitError, format_quantity


def main(argv: list[str] | None = None) -> int:
    """Plan cuts for the YAML job and write ``cut-plan.pdf``."""
    parser = argparse.ArgumentParser(
        description="Plan guillotine cuts that produce every window pane from sheet stock."
    )
    parser.add_argument("job", type=Path, help="YAML file of stock, panes, adjustment, and thickness")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("out"),
        help="directory for cut-plan.pdf (default: out)",
    )
    args = parser.parse_args(argv)
    try:
        job = load_job(args.job)
        plan = solve(job)
    except (CutError, UnitError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    destination = args.output / "cut-plan.pdf"
    write_report(job, plan, destination)
    glass = plan.glass_area
    percent = Fraction(0) if glass == 0 else plan.waste_area / glass * 100
    print(f"Sheets to buy: {plan.purchase}")
    print(
        f"Waste: {format_quantity(plan.waste_area)} sq in "
        f"({format_quantity(plan.waste_area / 144)} sq ft, {format_quantity(percent, 1)}%)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
