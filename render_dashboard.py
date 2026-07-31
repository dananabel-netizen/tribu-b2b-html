#!/usr/bin/env python3
"""
build_dashboard.py — Genera okrs_dashboard.html con datos del datalake embebidos.
Uso: cd tribu-b2b-dana && .venv\Scripts\python.exe skills/okrs-html/build_dashboard.py
"""

import json
import sys
from decimal import Decimal
from pathlib import Path
from datetime import datetime


HTML_TEMPLATE = """[PYTHON_HTML_TEMPLATE]


def to_json_native(obj):
    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return obj
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()[:10]
    try:
        return float(obj)
    except (TypeError, ValueError):
        return str(obj)


def build_html(data, updated):
    clean = {
        kr: [{col: to_json_native(val) for col, val in row.items()} for row in rows]
        for kr, rows in data.items()
    }
    html = HTML_TEMPLATE.replace('__DATA__', json.dumps(clean, ensure_ascii=False))
    html = html.replace('__UPDATED__', updated)
    return html

# ── Main ───────────────────────────────────────────────────────────────────────


