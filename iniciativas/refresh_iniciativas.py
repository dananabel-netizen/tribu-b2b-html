#!/usr/bin/env python3
"""
refresh_iniciativas.py — Actualiza las métricas de impacto del dashboard Iniciativas y las publica en GitHub
(rama tablero-live, carpeta iniciativas/).

Corre desde tablero-live/iniciativas/. Trae los datos del datalake, actualiza data.json["impact"], hace commit y push;
el HTML se genera acá mismo (build_html.py) y se publica junto con data.json; el Apps Script lo sirve.

NO toca data.json["initiatives"]: esa lista la mantiene la rutina que lee la bitácora de Slack.

Uso: .venv\\Scripts\\python.exe tablero-live/iniciativas/refresh_iniciativas.py [--no-push] [--no-git]
  --no-push  hace el commit local pero no publica
  --no-git   solo actualiza data.json y regenera el HTML local (sin pull/commit/push)
"""

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../tribu-b2b-dana/tablero-live/iniciativas
REPO = HERE.parent                              # .../tribu-b2b-dana/tablero-live (worktree)
ROOT = REPO.parent                              # .../tribu-b2b-dana (.env, skills/)
DATA = HERE / 'data.json'
REMOTE, BRANCH = 'personal', 'tablero-live'

CHANNELS = "('hoteldo-html-platinum','hoteldo-html-gold','hoteldo-html-silver','hoteldo-html-classic')"

# ── Link de pago en hoteles non ref: prendido escalonado ───────────────────────────────────────────
LDP_COUNTRIES = ['MX', 'AR', 'CL', 'BR', 'CO', 'PE']
LDP_LAUNCH = {'MX': '2026-09-29', 'AR': '2026-10-13', 'CL': '2026-10-13', 'BR': '2026-10-19', 'CO': '2026-10-19', 'PE': '2026-10-19'}
LDP_FROM = min(LDP_LAUNCH.values())
# Link de pago (KPIs, tabla por país, evolución del share) = hoteles NO reembolsables con medio de pago REMOTE, desde el lanzamiento de cada país.
# En el gráfico "Solo link de pago" = cualquier reserva con medio de pago REMOTE (solo o combinado), reembolsable o no.
# Se excluyen agencias con "test" en el nombre.

_LD_CASE = "case c " + " ".join(f"when '{c}' then date '{d}'" for c, d in LDP_LAUNCH.items()) + " end"
_IN = ",".join(f"'{c}'" for c in LDP_COUNTRIES)

_BASE = f"""
b as (
  select bi.creation_date d, bi.country_code c, bi.partner_id p, bi.agency_name an, bi.transaction_code r,
         bi.transaction_status st, bi.gb, product.refundable rf, product.payment_methods pm
  from analytics.bi_sales_fact_sales_recognition bi
  left join lake.channels_bo_product product on bi.origin_product_id = product.transaction_id
  where bi.channel in {CHANNELS}
    and bi.creation_date >= date '{LDP_FROM}' and bi.partition_period >= '{LDP_FROM[:7]}'
    and bi.product = 'Hoteles' and bi.country_code in ({_IN})
    and lower(coalesce(bi.agency_name,'')) not like '%test%'),
k as (select *, {_LD_CASE} ld from b)
"""

Q_LDP_DAILY = f"""
with {_BASE},
z as (select *, case when rf=false and pm like '%REMOTE%' and d>=ld then 'L' when rf=false then 'N' when rf=true then 'R' else 'X' end cls
      from k where st='Confirmado')
select cast(d as varchar) d,
 round(sum(case when cls='R' then gb end)) ref, round(sum(case when cls='N' then gb end)) non, round(sum(case when cls='L' then gb end)) link,
 round(sum(case when cls='X' then gb end)) sd, round(sum(case when d>=ld then gb end)) scope,
 count(distinct case when cls='L' then r end) nl,
 round(sum(case when d>=ld and rf=false then gb end)) scope_nr
from z group by d order by d
"""

Q_LDP_COUNTRY = f"""
with {_BASE},
s as (select * from k where d>=ld),
l as (select * from s where rf=false and pm like '%REMOTE%'),
pa as (select c, p, count(distinct r) n from l where st='Confirmado' group by c, p),
pt as (select p, count(distinct r) n from l where st='Confirmado' group by p)
select c, cast(max(ld) as varchar) ld,
 count(distinct case when st='Confirmado' then r end) nl, round(sum(case when st='Confirmado' then gb end)) gl,
 count(distinct case when st='Confirmado' then p end) ag, count(distinct case when st='Cancelado' then r end) nc, round(sum(case when st='Cancelado' then gb end)) gc,
 (select count(*) from pa where pa.c=l.c and pa.n>=2) rep
from l group by c
union all select 'ALL','',count(distinct case when st='Confirmado' then r end), round(sum(case when st='Confirmado' then gb end)), count(distinct case when st='Confirmado' then p end),
 count(distinct case when st='Cancelado' then r end), round(sum(case when st='Cancelado' then gb end)), (select count(*) from pt where n>=2) from l
union all select 'TOT','',count(distinct case when st='Confirmado' then r end), round(sum(case when st='Confirmado' then gb end)), count(distinct case when st='Confirmado' then p end),
 count(distinct case when st='Cancelado' then r end), round(sum(case when st='Cancelado' then gb end)), 0 from s
"""

Q_LDP_TOTALS = f"""
with {_BASE}
select c, round(sum(gb)) gt, count(distinct r) nt, count(distinct p) agt from k where d>=ld and st='Confirmado' and rf=false group by c
union all select 'ALL', round(sum(gb)), count(distinct r), count(distinct p) from k where d>=ld and st='Confirmado' and rf=false
"""

Q_LDP_TOP = f"""
with {_BASE},
t as (select p, max(an) an, max(c) c, count(distinct r) n, round(sum(gb)) g from k
      where d>=ld and st='Confirmado' and rf=false and pm like '%REMOTE%' group by p)
select p, an, c, n, g from t order by g desc limit 10
"""

# ── Pago diferido AR ───────────────────────────────────────────────────────────────────────────────
PD_LAUNCH = '2026-10-19'
Q_PD_DAILY = f"""
select cast(bi.creation_date as varchar) d, count(distinct bi.transaction_code) n, round(sum(bi.gb), 2) gb
from analytics.bi_sales_fact_sales_recognition bi
where bi.channel in {CHANNELS} and bi.creation_date >= date '{PD_LAUNCH}' and bi.partition_period >= '{PD_LAUNCH[:7]}'
  and bi.country_code = 'AR' and bi.transaction_status = 'Confirmado'
group by 1 order by 1
"""


def num(v):
    if v is None:
        return 0
    if isinstance(v, Decimal):
        v = float(v)
    return int(v) if isinstance(v, float) and v == int(v) else v


def git(*args):
    r = subprocess.run(['git', '-C', str(REPO), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {(r.stderr or r.stdout).strip()[:400]}")
    return r.stdout.strip()


def fetch_all():
    sys.path.insert(0, str(ROOT / 'skills' / 'datalake-query'))
    from presto_query import load_env, start_connection, execute_query
    load_env(str(ROOT / '.env'))
    print("Conectando a datalake.despegar.com...")
    conn = start_connection(catalog='data', schema='analytics')
    out = {}

    def q(name, sql):
        print(f"  -> {name}...", end=' ', flush=True)
        cols, rows = execute_query(conn, sql.strip())
        print(f"OK ({len(rows)} filas)")
        return [list(r) for r in rows]

    try:
        out['ldp_daily'] = q('ldp_daily', Q_LDP_DAILY)
        out['ldp_country'] = q('ldp_country', Q_LDP_COUNTRY)
        out['ldp_totals'] = q('ldp_totals', Q_LDP_TOTALS)
        out['ldp_top'] = q('ldp_top', Q_LDP_TOP)
        out['pd_daily'] = q('pd_daily', Q_PD_DAILY)
        return out, q   # q se reusa para las reservas de pago diferido
    except Exception:
        conn.close()
        raise


def build_ldp(cfg_old, r, today):
    daily = [[row[0]] + [num(x) for x in row[1:]] for row in r['ldp_daily']]
    cty = {row[0]: row for row in r['ldp_country']}
    tt = {row[0]: row for row in r['ldp_totals']}
    nr = tt.pop('ALL')
    countries = []
    for c in LDP_COUNTRIES:
        if c not in cty:
            continue
        x, t = cty[c], tt.get(c, [c, 0, 0, 0])
        # [país, prendido, bookings link, GB link, agencias link, GB hoteles total, bookings hoteles total, canceladas link, repitieron]
        countries.append([c, LDP_LAUNCH[c], num(x[2]), num(x[3]), num(x[4]), num(t[1]), num(t[2]), num(x[5]), num(x[7])])
    A, T = cty['ALL'], cty['TOT']
    tot = {'nl': num(A[2]), 'gl': num(A[3]), 'ag': num(A[4]), 'gt': num(nr[1]), 'nt': num(nr[2]),
           'agt': num(nr[3]), 'nc': num(A[5]), 'gc': num(A[6]), 'rep': num(A[7]), 'hnc': num(T[5])}
    top = [[row[0], row[1], row[2], num(row[3]), num(row[4])] for row in r['ldp_top']]
    cfg = dict(cfg_old)
    cfg.pop('remote', None)   # ya no se usa
    cfg.update(kind='ldp', title=cfg_old.get('title', 'Link de pago en hoteles non ref'), asof=today.isoformat(),
               partial=(today + timedelta(days=1)).isoformat(), daily=daily, countries=countries, tot=tot, top=top)
    return cfg


def build_pd(cfg_old, r, q, today):
    cfg = dict(cfg_old)
    sql = cfg_old['query']
    bookings = [[str(x[0]), x[1], x[2], x[3], str(x[4]), num(x[5])] for x in q('pd_bookings', sql)]
    cfg.update(asof=today.isoformat(), partial=(today + timedelta(days=1)).isoformat(),
               daily=[[row[0], num(row[1]), num(row[2])] for row in r['pd_daily']], bookings=bookings)
    return cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-push', action='store_true')
    ap.add_argument('--no-git', action='store_true')
    args = ap.parse_args()
    today = date.today()
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] refresh iniciativas")

    if not args.no_git:
        try:
            git('checkout', '--', str(DATA))   # descarta restos de una corrida anterior fallida
        except RuntimeError:
            pass
        git('pull', '--rebase', REMOTE, BRANCH)

    data = json.loads(DATA.read_text(encoding='utf-8'))
    cfgs = data['impact']['configs']
    r, q = fetch_all()
    cfgs['ldp'] = build_ldp(cfgs.get('ldp', {}), r, today)
    cfgs['pd_ar'] = build_pd(cfgs['pd_ar'], r, q, today)
    data['updated'] = today.isoformat()
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')

    subprocess.run([sys.executable, str(HERE / 'build_html.py'), str(DATA)], check=True)   # genera iniciativas_dashboard.html
    if args.no_git:
        print("OK — data.json y HTML locales actualizados (--no-git).")
        return

    git('add', str(DATA), str(HERE / 'iniciativas_dashboard.html'))
    if not git('diff', '--cached', '--name-only'):
        print("Sin cambios en los datos — nada para publicar.")
        return
    git('commit', '-m', f"Refresh Iniciativas {datetime.now():%Y-%m-%d %H:%M}")
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
