#!/usr/bin/env python3
"""
build_html.py — Genera iniciativas_dashboard.html a partir de template.html + data.json (sin conexión al datalake).

Uso:
  python build_html.py                    # usa data.json del mismo directorio
  python build_html.py /ruta/data.json

data.json: {"updated": "YYYY-MM-DD",
            "initiatives": [[nombre, fecha, "AR,CL", categoria, nota], ...],     # lo mantiene la bitácora de Slack
            "impact": {"configs": {...}, "map": {"nombre|fecha": "clave_config"}}}  # lo genera refresh_iniciativas.py
"""
import json
import sys
from pathlib import Path


def js(obj):
    # JSON seguro para incrustar dentro de un <script>
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')


def main():
    here = Path(__file__).parent
    data_path = Path(sys.argv[1]) if len(sys.argv) > 1 else here / 'data.json'
    data = json.loads(data_path.read_text(encoding='utf-8'))
    html = (here / 'template.html').read_text(encoding='utf-8')
    html = (html.replace('@@RAW@@', js(data['initiatives']))
                .replace('@@CFG@@', js(data['impact']['configs']))
                .replace('@@MAP@@', js(data['impact']['map']))
                .replace('@@UPDATED@@', data['updated']))
    out = data_path.parent / 'iniciativas_dashboard.html'
    out.write_text(html, encoding='utf-8')
    print(f"Dashboard generado: {out}")


if __name__ == '__main__':
    main()
