#!/usr/bin/env python3
"""Summarize per-dimension repeatability from a validation artifact (0539)."""
import argparse
import json
import math
from collections import Counter
from pathlib import Path


def diagnose(artifact: dict) -> dict:
    cells = []
    for ticker, dims in artifact.get("results", {}).get("repeatability", {}).items():
        for dimension, row in dims.items():
            values = row.get("values", [])
            counts = Counter(values)
            n = row.get("n", len(values))
            mean = row.get("mean")
            stdev = row.get("stdev")
            if values:
                lo, hi = min(values), max(values)
                mode_n = max(counts.values())
                entropy = -sum((c / len(values)) * math.log2(c / len(values)) for c in counts.values())
            else:
                lo = hi = None
                mode_n = 0
                entropy = None
            cells.append({"ticker": ticker, "dimension": dimension, "n": n,
                          "mean": mean, "stdev": stdev, "min": lo, "max": hi,
                          "range": (hi - lo) if lo is not None else row.get("range"),
                          "mode_fraction": mode_n / len(values) if values else None,
                          "entropy_bits": entropy,
                          "range_le_1": (hi - lo <= 1) if lo is not None else row.get("range", 999) <= 1})
    ranges = Counter("missing" if c["range"] is None else ("3+" if c["range"] >= 3 else str(c["range"])) for c in cells)
    return {"record_id": artifact.get("record_id"), "verdict": artifact.get("verdict"),
            "cells": cells, "range_distribution": dict(ranges),
            "range_le_1_count": sum(c["range_le_1"] for c in cells)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = diagnose(json.loads(args.artifact.read_text()))
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(text + "\n")
    else:
        print(text)


if __name__ == "__main__":
    main()
