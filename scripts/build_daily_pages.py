#!/usr/bin/env python3
"""Backward-compatible entry: builds the full daily+monthly site."""
from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("build_report_pages.py")), run_name="__main__")
