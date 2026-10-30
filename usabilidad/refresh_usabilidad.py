#!/usr/bin/env python3
"""
refresh_usabilidad.py — Agrega al dashboard de Usabilidad las semanas que ya cerraron y lo publica en GitHub
(rama tablero-live, carpeta usabilidad/).

Corre desde cualquier lado. Todos los días revisa si cerró una semana nueva (viernes a jueves, con
margen de 1 día para que el datalake termine de cargarla). Si hay, trae las consultas del datalake (una por producto,
abiertas por país), actualiza data.json, regenera el HTML, hace commit y push; el Apps Script lo sirve.
Si no hay semanas nuevas no consulta nada ni publica.

Uso: .venv\\Scripts\\python.exe tablero-live/usabilidad/refresh_usabilidad.py [--no-push] [--no-git] [--recompute N]
  --no-push      hace el commit local pero no publica
  --no-git       solo actualiza data.json y regenera el HTML local (sin pull/commit/push)
  --recompute N  vuelve a traer las últimas N semanas cerradas (para verificar o corregir datos)
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

for _s in (sys.stdout, sys.stderr):   # la consola/log de Windows usa cp1252: sin esto falla con flechas y acentos
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

HERE = Path(__file__).resolve().parent          # .../tribu-b2b-dana/tablero-live/usabilidad
REPO = HERE.parent                              # .../tribu-b2b-dana/tablero-live (worktree)
ROOT = REPO.parent                              # .../tribu-b2b-dana (.env, skills/)
DATA = HERE / 'data.json'
HTML = HERE / 'usabilidad_dashboard.html'
REMOTE, BRANCH = 'personal', 'tablero-live'

ANCHOR = date(2026, 8, 28)    # las semanas empiezan los viernes
MARGIN_DAYS = 1               # una semana se considera cerrada 1 día después de su último día
MAX_WEEKS = 26                # el tablero conserva las últimas 26 semanas
CHANNELS = "('hoteldo-html-classic','hoteldo-html-gold','hoteldo-html-silver','hoteldo-html-platinum')"
COUNTRIES = ['BR', 'MX', 'CO', 'AR', 'CL', 'PE', 'OT']
PRODUCTS = ['Hoteles', 'Vuelos', 'Autos', 'Actividades', 'Paquetes']

# producto del tablero -> (condición sobre bi_web_traffic, fuente de los clicks de filtros)
CONFIG = {
    'Hoteles':     ("b.product IN ('HOTELS','VACATION RENTALS')", 'acc'),
    'Vuelos':      ("b.product = 'FLIGHTS'", 'fl'),
    'Autos':       ("b.product = 'CARS'", 'cars'),
    'Actividades': ("b.product = 'ACTIVITIES'", 'act'),
    'Paquetes':    ("b.product = 'COMBINED PRODUCT'", 'acc'),
}


def clicks_cte(kind, start, end):
    dt = lambda a: f"{a}.datetime >= '{start}' AND {a}.datetime <= '{end}T23:59:59.999'"
    if kind in ('acc', 'cars'):
        table = 'accommodations_filter' if kind == 'acc' else 'cars_filter_change'
        return f"""
  SELECT DISTINCT b.cg, f.filter_name, b.visit
  FROM data.sot.{table} af
  CROSS JOIN UNNEST(map_entries(af.event.filters)) AS f(filter_name, filter_values)
  CROSS JOIN UNNEST(f.filter_values) AS v(filter_value)
  JOIN b ON af.event.pageview_id = b.pageview_id
  WHERE b.flow = 'SEARCH' AND {dt('af')}"""
    if kind == 'fl':
        return f"""
  SELECT DISTINCT b.cg, fsf.event.event.name AS filter_name, b.visit
  FROM data.sot.flights_sort_and_filter fsf
  CROSS JOIN UNNEST(fsf.event.event."values") AS v(filter_value)
  JOIN b ON fsf.event.pageview_id = b.pageview_id
  WHERE b.flow = 'SEARCH' AND fsf.event.type = 'filter' AND fsf.event.selected = '1'
    AND {dt('fsf')}"""
    return f"""
  SELECT DISTINCT b.cg, ag.event.label AS filter_name, b.visit
  FROM data.sot.activities_generic_event ag
  JOIN b ON ag.event.pageview_id = b.pageview_id
  WHERE b.flow = 'SEARCH' AND ag.event.action = 'apply'
    AND ag.event.label NOT IN ('sorting', 'ai-search')
    AND ag.event.data['filter'] IS NOT NULL
    AND {dt('ag')}"""


def query(product, start, end):
    cond, kind = CONFIG[product]
    return f"""
WITH b AS (
  SELECT visit, pageview_id, flow,
    CASE WHEN b.country IN ('BR','MX','CO','AR','CL','PE') THEN b.country ELSE 'OT' END AS cg
  FROM data.lake.bi_web_traffic b
  WHERE {cond} AND b.flow IN ('SEARCH','THANKS')
    AND b.date >= '{start}' AND b.date <= '{end}'
    AND b.ispageview = 1 AND b.flg_detalle_cp = 0 AND b.is_bot = 0
    AND b.channel in {CHANNELS}
),
clicks AS ({clicks_cte(kind, start, end)}
),
fc AS (
  SELECT c.cg, c.filter_name, COUNT(DISTINCT c.visit) AS clicks, COUNT(DISTINCT t.visit) AS thanks
  FROM clicks c LEFT JOIN b t ON c.visit = t.visit AND t.flow = 'THANKS' AND t.cg = c.cg
  GROUP BY 1,2
),
tv AS (SELECT cg, COUNT(DISTINCT visit) AS visits FROM b WHERE flow = 'SEARCH' GROUP BY 1)
SELECT tv.cg, tv.visits,
  array_join(array_agg(fc.filter_name || ' ' || CAST(fc.clicks AS VARCHAR) || ' ' || CAST(fc.thanks AS VARCHAR) ORDER BY fc.clicks DESC), ';') AS s
FROM tv LEFT JOIN fc ON fc.cg = tv.cg
GROUP BY 1,2 ORDER BY 2 DESC
"""


def git(*args):
    r = subprocess.run(['git', '-C', str(REPO), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {(r.stderr or r.stdout).strip()[:400]}")
    return r.stdout.strip()


def closed_weeks(today):
    """Inicios (viernes) de todas las semanas ya cerradas, desde ANCHOR."""
    out, d = [], ANCHOR
    while d + timedelta(days=6 + MARGIN_DAYS) <= today:
        out.append(d)
        d += timedelta(days=7)
    return out


def fetch_week(start, retries=3):
    """Trae los cinco productos de una semana. Devuelve {producto: {pais: (visitas, texto)}}."""
    sys.path.insert(0, str(ROOT / 'skills' / 'datalake-query'))
    from presto_query import load_env, start_connection, execute_query
    load_env(str(ROOT / '.env'))
    end = (start + timedelta(days=6)).isoformat()

    def one(product):
        sql = query(product, start.isoformat(), end).strip()
        for attempt in range(retries + 1):
            conn = None
            try:
                conn = start_connection(catalog='data', schema='lake')
                _, rows = execute_query(conn, sql)
                return product, {r[0]: (int(r[1]), r[2] or '') for r in rows}
            except (Exception, SystemExit) as e:   # execute_query hace sys.exit(1) cuando falla
                print(f"    {product} {start}: intento {attempt + 1} falló ({str(e)[:120] or type(e).__name__})")
                if attempt == retries:
                    raise RuntimeError(f"{product} {start}: la consulta falló {retries + 1} veces")
                time.sleep(45)
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass

    # De a una: el datalake rechaza (QUERY_QUEUE_FULL) varias consultas simultáneas del mismo usuario.
    print(f"  semana {start} → {end}: consultando 5 productos (de a uno)...", flush=True)
    out = {}
    for p in PRODUCTS:
        t0 = time.time()
        _, out[p] = one(p)
        print(f"    {p}: OK ({time.time() - t0:.0f}s, {len(out[p])} países)", flush=True)
    return out


def parse(s):
    return {x.split(' ')[0]: (int(x.split(' ')[1]), int(x.split(' ')[2])) for x in s.split(';') if x.strip()}


def merge_countries(by_cc):
    """Total del producto = suma de los países (visitas y clicks/thanks por filtro)."""
    visits, agg = 0, {}
    for v, s in by_cc.values():
        visits += v
        for f, (c, t) in parse(s).items():
            a = agg.setdefault(f, [0, 0])
            a[0] += c
            a[1] += t
    text = ';'.join(f"{f} {c} {t}" for f, (c, t) in sorted(agg.items(), key=lambda kv: -kv[1][0]))
    return visits, text


def apply_week(data, start, result):
    iso = start.isoformat()
    if iso in data['weeks']:
        i = data['weeks'].index(iso)
    else:
        data['weeks'].append(iso)
        i = len(data['weeks']) - 1
        for p in PRODUCTS:
            data['raw'][p].append([0, ''])
            for cc in data['rawc'][p]:
                data['rawc'][p][cc].append([0, ''])
    for p in PRODUCTS:
        by_cc = result[p]
        for cc in COUNTRIES:
            ws = data['rawc'][p].setdefault(cc, [[0, ''] for _ in data['weeks']])
            while len(ws) < len(data['weeks']):
                ws.append([0, ''])
            v, s = by_cc.get(cc, (0, ''))
            ws[i] = [v, s]
        v, s = merge_countries({cc: tuple(data['rawc'][p][cc][i]) for cc in data['rawc'][p]})
        data['raw'][p][i] = [v, s]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-push', action='store_true')
    ap.add_argument('--no-git', action='store_true')
    ap.add_argument('--recompute', type=int, default=0)
    args = ap.parse_args()
    today = date.today()
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] refresh usabilidad")

    if not args.no_git:
        try:
            git('checkout', '--', str(DATA))   # descarta restos de una corrida anterior fallida
        except RuntimeError:
            pass
        git('pull', '--rebase', REMOTE, BRANCH)

    data = json.loads(DATA.read_text(encoding='utf-8'))
    closed = closed_weeks(today)
    have = {date.fromisoformat(w) for w in data['weeks']}
    todo = [w for w in closed if w not in have]
    if args.recompute:
        todo = sorted(set(todo) | set(closed[-args.recompute:]))
    if not todo:
        print(f"Sin semanas nuevas (última cerrada: {closed[-1]}). Nada para hacer.")
        return

    print(f"Semanas a traer: {', '.join(str(w) for w in todo)}")
    for w in todo:
        apply_week(data, w, fetch_week(w))

    # ordena cronológicamente y conserva las últimas MAX_WEEKS
    order = sorted(range(len(data['weeks'])), key=lambda i: data['weeks'][i])
    data['weeks'] = [data['weeks'][i] for i in order]
    for p in PRODUCTS:
        data['raw'][p] = [data['raw'][p][i] for i in order]
        for cc in data['rawc'][p]:
            data['rawc'][p][cc] = [data['rawc'][p][cc][i] for i in order]
    if len(data['weeks']) > MAX_WEEKS:
        cut = len(data['weeks']) - MAX_WEEKS
        data['weeks'] = data['weeks'][cut:]
        for p in PRODUCTS:
            data['raw'][p] = data['raw'][p][cut:]
            for cc in data['rawc'][p]:
                data['rawc'][p][cc] = data['rawc'][p][cc][cut:]
    data['updated'] = today.isoformat()
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')

    subprocess.run([sys.executable, str(HERE / 'build_html.py')], check=True)   # genera usabilidad_dashboard.html
    if args.no_git:
        print("OK — data.json y HTML locales actualizados (--no-git).")
        return

    git('add', str(DATA), str(HTML))
    if not git('diff', '--cached', '--name-only'):
        print("Sin cambios en los datos — nada para publicar.")
        return
    git('commit', '-m', f"Refresh Usabilidad {datetime.now():%Y-%m-%d %H:%M}")
    if args.no_push:
        print("Commit local hecho (--no-push).")
        return
    git('push', REMOTE, BRANCH)
    print("OK — data.json y HTML publicados.")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
