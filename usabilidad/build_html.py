#!/usr/bin/env python3
"""
build_html.py — Genera usabilidad_dashboard.html a partir de template.html + data.json.

- Reemplaza los datos (WINDOW, WEEKS, RAW y RAWC) entre los marcadores @@DATA_* y @@RAWC_* del template.
- Reemplaza IMG_BASE por la URL absoluta de las imágenes (dentro de Apps Script no andan las rutas relativas).

Uso: python build_html.py [--base URL_BASE] [--out ARCHIVO]
     (sin --base usa la carpeta usabilidad/ de la rama tablero-live en GitHub raw)
"""
import argparse
import json
import re
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_BASE = "https://raw.githubusercontent.com/dananabel-netizen/tribu-b2b-dana-/tablero-live/usabilidad/"
PRODUCTS = ["Hoteles", "Vuelos", "Autos", "Actividades", "Paquetes"]


def js(v):
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def data_block(d):
    weeks = d["weeks"]
    first = date.fromisoformat(weeks[0])
    last_end = date.fromisoformat(weeks[-1]) + timedelta(days=6)
    window = f"{len(weeks)} semanas: {first:%d/%m} – {last_end:%d/%m/%Y}"
    out = ["// @@DATA_BEGIN",
           f'const WINDOW = "{window}";',
           "// Una corrida por semana y producto (la de 30 días vence el tiempo). Cada semana: [visitas, \"filtro clicks thanks;...\"]",
           f"const WEEKS = {js(weeks)};",
           "const RAW = {"]
    prods = []
    for p in PRODUCTS:
        if p not in d["raw"]:
            continue
        rows = ",\n".join(f"  [{v},{js(s)}]" for v, s in d["raw"][p])
        prods.append(f' "{p}":{{card:{d["card"][p]}, w:[\n{rows}]}}')
    out.append(",\n".join(prods))
    out += ["};", "// @@DATA_END"]
    return "\n".join(out)


def rawc_block(d):
    out = ["// @@RAWC_BEGIN", "const RAWC = {"]
    prods = []
    for p in PRODUCTS:
        if p not in d["rawc"]:
            continue
        ccs = ",\n".join(f"  {js(cc)}:{js(ws)}" for cc, ws in d["rawc"][p].items())
        prods.append(f' "{p}":{{\n{ccs}\n }}')
    out.append(",\n".join(prods))
    out += ["};", "// @@RAWC_END"]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE, help="URL base de las imágenes (termina en /)")
    ap.add_argument("--out", default=str(HERE / "usabilidad_dashboard.html"))
    args = ap.parse_args()
    base = args.base if args.base.endswith("/") else args.base + "/"

    d = json.loads((HERE / "data.json").read_text(encoding="utf-8"))
    html = (HERE / "template.html").read_text(encoding="utf-8")

    html, n = re.subn(r"// @@DATA_BEGIN\n.*?// @@DATA_END", lambda m: data_block(d), html, count=1, flags=re.S)
    assert n == 1, "No encontré los marcadores @@DATA_* en template.html"
    html, n = re.subn(r"// @@RAWC_BEGIN\n.*?// @@RAWC_END", lambda m: rawc_block(d), html, count=1, flags=re.S)
    assert n == 1, "No encontré los marcadores @@RAWC_* en template.html"
    html, n = re.subn(r'const IMG_BASE = "";', lambda m: f'const IMG_BASE = "{base}";', html, count=1)
    assert n == 1, "No encontré IMG_BASE en template.html"

    Path(args.out).write_text(html, encoding="utf-8")
    print(f"OK · {args.out} · {len(d['weeks'])} semanas · imágenes en {base}")


if __name__ == "__main__":
    main()
