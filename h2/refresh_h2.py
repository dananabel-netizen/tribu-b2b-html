#!/usr/bin/env python3
"""
refresh_h2.py — Actualiza el dashboard OKRs H2 y lo publica en GitHub (rama tablero-live, carpeta h2/).

Corre desde tablero-live/h2/. Trae los datos del datalake, actualiza data.json, hace commit y push;
el GitHub Action (build-dashboard-h2.yml) regenera el HTML y el Apps Script lo sirve.

Modos (que claves de data.json se refrescan):
  diario   -> kr11_prog, kr21_prog, kr22_prog   (pestaña Progreso)
  semanal  -> kr21_sem,  kr22_sem    (pestaña Semanal)
  mensual  -> kr11, kr21, kr22        (pestaña Mensual)
  todo     -> las tres
  auto     -> las tres, todos los dias   (default)

--pedido: lo usa la tarea que corre cada pocos minutos. Mira si el boton "Actualizar" del tablero dejo un
pedido nuevo (h2/refresh_request.json en tablero-live); si no hay, sale sin hacer nada. Si hay, refresca todo.

Uso: .venv\\Scripts\\python.exe tablero-live/h2/refresh_h2.py [--modo auto|diario|semanal|mensual|todo] [--no-push]
"""

import argparse
import json
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../tribu-b2b-dana/tablero-live/h2
REPO = HERE.parent                              # .../tribu-b2b-dana/tablero-live (worktree)
ROOT = REPO.parent                              # .../tribu-b2b-dana (.env, skills/)
DATA = HERE / 'data.json'
REMOTE, BRANCH = 'personal', 'tablero-live'
PEDIDO_REMOTO = 'h2/refresh_request.json'       # lo escribe el Apps Script cuando se toca "Actualizar"
PEDIDO_VISTO = ROOT / '.refresh_h2_pedido'      # ultimo pedido ya atendido (fuera del worktree)

sys.path.insert(0, str(HERE))
import build_dashboard as bd

MODOS = {
    'diario':  ['kr11_prog', 'kr21_prog', 'kr22_prog'],
    'semanal': ['kr21_sem', 'kr22_sem'],
    'mensual': ['kr11', 'kr21', 'kr22'],
}


def git(*args):
    r = subprocess.run(['git', '-C', str(REPO), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {(r.stderr or r.stdout).strip()[:400]}")
    return r.stdout.strip()


def sync_remoto(intentos=4):
    """fetch + rebase sobre la ref remota (sin FETCH_HEAD, que se pisa cuando otras tareas
    programadas hacen fetch en el mismo worktree a la vez). Reintenta ante colisiones."""
    for i in range(intentos):
        try:
            git('fetch', REMOTE, BRANCH)
            git('rebase', '--autostash', f'{REMOTE}/{BRANCH}')
            return
        except RuntimeError:
            if i == intentos - 1:
                raise
            time.sleep(5 + random.randint(0, 20))


def pedido_pendiente():
    """Devuelve el requested_at del pedido del boton si todavia no se atendio; si no, None."""
    for i in range(3):
        try:
            git('fetch', REMOTE, BRANCH)
            break
        except RuntimeError:
            if i == 2:
                raise
            time.sleep(5 + random.randint(0, 20))
    try:
        req = json.loads(git('show', f'{REMOTE}/{BRANCH}:{PEDIDO_REMOTO}')).get('requested_at')
    except (RuntimeError, ValueError):
        return None
    visto = PEDIDO_VISTO.read_text(encoding='utf-8').strip() if PEDIDO_VISTO.exists() else ''
    return req if req and req > visto else None


def modos_de_hoy(modo):
    hoy = datetime.now()
    if modo == 'todo':
        return ['diario', 'semanal', 'mensual']
    if modo != 'auto':
        return [modo]
    # Las 8 queries son livianas: se refrescan todas los dias. Antes semanal solo corria los lunes y
    # mensual el dia 1, y si la PC estaba apagada ese dia la pestaña quedaba una semana/mes desactualizada.
    return ['diario', 'semanal', 'mensual']


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
    ap.add_argument('--pedido', action='store_true', help='solo corre si el boton Actualizar dejo un pedido nuevo')
    args = ap.parse_args()

    pedido = None
    if args.pedido:
        pedido = pedido_pendiente()
        if not pedido:
            return
        args.modo = 'todo'

    modos = modos_de_hoy(args.modo)
    keys = [k for m in modos for k in MODOS[m]]
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] modos: {', '.join(modos)}")

    try:
        git('checkout', '--', str(DATA))   # descarta restos de una corrida anterior fallida
    except RuntimeError:
        pass
    sync_remoto()

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
        if pedido:
            PEDIDO_VISTO.write_text(pedido, encoding='utf-8')
        return
    git('commit', '-m', f"Refresh H2 ({'+'.join(modos)}) {datetime.now():%Y-%m-%d %H:%M}")
    if args.no_push:
        print("Commit local hecho (--no-push).")
        return
    git('push', REMOTE, BRANCH)
    if pedido:
        PEDIDO_VISTO.write_text(pedido, encoding='utf-8')
    print("OK — data.json publicado; el Action regenera el HTML en ~1 min.")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
