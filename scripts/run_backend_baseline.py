from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from ai_novel_studio.application.evaluation_service import (
    load_context_baseline_suite,
    run_context_baseline,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the deterministic Phase 0 backend context baseline."
    )
    parser.add_argument("suite", type=Path, help="Path to a validated baseline JSON suite")
    args = parser.parse_args(argv)

    report = run_context_baseline(load_context_baseline_suite(args.suite))
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return int(
        report.matched_scenarios != report.total_scenarios
        or report.unexpected_error_count > 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
