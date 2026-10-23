#!/usr/bin/env python3
"""
refresh_h2.py — Actualiza el dashboard OKRs H2 y lo publica en GitHub (rama tablero-live, carpeta h2/).

Corre desde tablero-live/h2/. Trae los datos del datalake, actualiza data.json, hace commit y push;
el GitHub Action (build-dashboard-h2.yml) regenera el HTML y el Apps Script lo sirve.

Modos (que claves de data.json se refrescan):
  diario   -> kr21_prog, kr22_prog   (pestaña Progreso)
  semanal  -> kr21_sem,  kr22_sem    (pestaña Semanal)
  mensual  -> kr21,      kr22        (pestaña Mensual)
  todo     -> las tres
  auto     -> siempre diario; + semanal si hoy es lunes; + mensual si hoy es dia 1   (default)

Uso: .venv\\Scripts\\python.exe tablero-live/h2/refresh_h2.py [--modo auto|diario|semanal|mensual|todo] [--no-push]
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../tribu-b2b-dana/tablero-live/h2
REPO = HERE.parent                              # .../tribu-b2b-dana/tablero-live (worktree)
ROOT = REPO.parent                              # .../tribu-b2b-dana (.env, skills/)
DATA = HERE / 'data.json'
REMOTE, BRANCH = 'personal', 'tablero-live'

sys.path.insert(0, str(HERE))
import build_dashboard as bd

MODOS = {
    'diario':  ['kr21_prog', 'kr22_prog'],
    'semanal': ['kr21_sem', 'kr22_sem'],
    'mensual': ['kr21', 'kr22'],
}


def git(*args):
    r = subprocess.run(['git', '-C', str(REPO), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {(r.stderr or r.stdout).strip()[:400]}")
    return r.stdout.strip()


def modos_de_hoy(modo):
    hoy = datetime.now()
    if modo == 'todo':
        return ['diario', 'semanal', 'mensual']
    if modo != 'auto':
        return [modo]
    out = ['diario']
    if hoy.weekday() == 0:
        out.append('semanal')
    if hoy.day == 1:
        out.append('mensual')
    return out


def run_keys(keys):
    sys.path.insert(0, str(ROOT / 'skills' / 'datalake-query'))
    from presto_query import load_env, start_connection, execute_query
    load_env(str(ROOT / '.env'))
    print("Conectando a datalake.despegar.com...")
    conn = start_connection(catalog='data', schema='analytics')
    queries = dict(bd.QUERIES)
    new = {}
    try:
        for k in keys:
            print(f"  -> {k.upper()}...", end=' ', flush=True)
            cols, rows = execute_query(conn, queries[k].strip())
            new[k] = bd.rows_to_dicts(cols, rows)
            print(f"OK ({len(rows)} filas)")
    finally:
        conn.close()
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--modo', default='auto', choices=['auto', 'diario', 'semanal', 'mensual', 'todo'])
    ap.add_argument('--no-push', action='store_true')
    args = ap.parse_args()

    modos = modos_de_hoy(args.modo)
    keys = [k for m in modos for k in MODOS[m]]
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] modos: {', '.join(modos)}")

    git('pull', '--rebase', REMOTE, BRANCH)

    existing = json.loads(DATA.read_text(encoding='utf-8')) if DATA.exists() else {}
    existing.update(run_keys(keys))
    clean = {
        kr: [{c: bd.to_json_native(v) for c, v in row.items()} for row in rows]
        for kr, rows in existing.items()
    }
    DATA.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding='utf-8')

    git('add', str(DATA))
    if not git('diff', '--cached', '--name-only'):
        print("Sin cambios en los datos — nada para publicar.")
        return
    git('commit', '-m', f"Refresh H2 ({'+'.join(modos)}) {datetime.now():%Y-%m-%d %H:%M}")
    if args.no_push:
        print("Commit local hecho (--no-push).")
        return
    git('push', REMOTE, BRANCH)
    print("OK — data.json publicado; el Action regenera el HTML en ~1 min.")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
