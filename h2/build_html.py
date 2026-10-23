#!/usr/bin/env python3
"""
build_html.py — Genera okrs_dashboard_h2.html a partir de data.json (sin conexión a Trino).

Uso:
  python build_html.py                    # lee data.json en el mismo directorio
  python build_html.py /ruta/data.json    # ruta explícita al JSON

Formato de data.json: {"kr21": [...filas de card 173704...], "kr22": [...filas de card 173707...]}
"""

import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from build_dashboard import build_html as _render_html


def main():
    data_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / 'data.json'
    if not data_path.exists():
        print(f"ERROR: no se encontró {data_path}")
        sys.exit(1)

    data = json.loads(data_path.read_text(encoding='utf-8'))
    html = _render_html(data, datetime.now().strftime('%Y-%m-%d %H:%M'))

    output = data_path.parent / 'okrs_dashboard_h2.html'
    output.write_text(html, encoding='utf-8')
    print(f"Dashboard generado: {output}")


if __name__ == '__main__':
    main()
