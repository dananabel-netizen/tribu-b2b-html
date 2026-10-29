#!/usr/bin/env python3
"""
build_dashboard.py — Genera okrs_dashboard_h2.html con datos del datalake embebidos (H2 FY27: Oct 2026 – Mar 2027).
Uso: cd tribu-b2b-dana && .venv\\Scripts\\python.exe data-analytics/okrs-html-h2/build_dashboard.py

Las queries son las mismas de las cards de Metabase (los targets viajan dentro de la query):
  KR 2.1 -> card 173704   KR 2.2 -> card 173707
Los KRs de E&S (1.1 GMV medios de pago propios, 1.2 CPO) quedan como placeholders hasta tener query y target.
"""

import json
import sys
from decimal import Decimal
from pathlib import Path
from datetime import datetime

# ── Queries ────────────────────────────────────────────────────────────────────

# KR 2.1 — # de agencias que utilizan cotizaciones (Metabase card 173704)
QUERY_KR21 = """
WITH parametros AS (
    SELECT DATE '2026-10-01' AS fecha_inicio, DATE '2027-03-31' AS fecha_fin
),
targets AS (
    SELECT DATE '2026-10-01' AS mes, 4 AS semanas, 7500 AS target_agencias
    UNION ALL SELECT DATE '2026-11-01', 4, 7718
    UNION ALL SELECT DATE '2026-12-01', 5, 7601
    UNION ALL SELECT DATE '2027-01-01', 4, 7910
    UNION ALL SELECT DATE '2027-02-01', 4, 7818
    UNION ALL SELECT DATE '2027-03-01', 4, 8100
),
cotizaciones_socrates AS (
    SELECT DATE_TRUNC('month', CAST(created_at AS DATE)) AS mes,
           UPPER(agency_code) AS agency_code,
           COUNT(*) AS cotizaciones_realizadas
    FROM data.raw.socrates_trip_quotations
    CROSS JOIN parametros p
    WHERE CAST(created_at AS DATE) BETWEEN p.fecha_inicio AND p.fecha_fin
      AND channel_code IN ('hoteldo-html-classic','hoteldo-html-gold','hoteldo-html-platinum','hoteldo-html-silver')
      AND agency_code IS NOT NULL AND agency_code != ''
    GROUP BY 1, 2
),
evolucion AS (
    SELECT mes,
           COUNT(DISTINCT agency_code)  AS agencias_cotizadoras,
           SUM(cotizaciones_realizadas) AS cotizaciones_realizadas,
           ROUND(SUM(cotizaciones_realizadas) / NULLIF(COUNT(DISTINCT agency_code), 0), 1) AS cotizaciones_por_agencia
    FROM cotizaciones_socrates
    GROUP BY 1
)
SELECT t.mes,
       t.semanas AS semanas,
       COALESCE(e.agencias_cotizadoras, 0) AS agencias_cotizadoras,
       t.target_agencias AS target,
       ROUND(100.0 * COALESCE(e.agencias_cotizadoras, 0) / NULLIF(t.target_agencias, 0), 1) AS pct_cumplimiento
FROM targets t
LEFT JOIN evolucion e ON t.mes = e.mes
ORDER BY t.mes
"""

# KR 2.2 — # de agencias que compran al menos 3 semanas al mes (Metabase card 173707)
# Calendario comercial por semanas; devuelve la ultima semana disponible de cada mes (CIERRE / EN_CURSO).
QUERY_KR22 = """
WITH cal AS (
    SELECT periodo, desde, hasta, n_sem
    FROM (VALUES
        ('2026-10', DATE '2026-10-05', DATE '2026-11-01', 4),
        ('2026-11', DATE '2026-11-02', DATE '2026-11-29', 4),
        ('2026-12', DATE '2026-11-30', DATE '2027-01-03', 5),
        ('2027-01', DATE '2027-01-04', DATE '2027-01-31', 4),
        ('2027-02', DATE '2027-02-01', DATE '2027-02-28', 4),
        ('2027-03', DATE '2027-03-01', DATE '2027-03-28', 4)
    ) AS v (periodo, desde, hasta, n_sem)
),
sem AS (
    SELECT c.periodo, c.n_sem, c.desde AS m_desde, k AS semana,
           date_add('day', 7 * (k - 1), c.desde)     AS s_desde,
           date_add('day', 7 * (k - 1) + 6, c.desde) AS s_hasta,
           LEAST(date_add('day', 7 * k, c.desde), current_date) AS foto,
           CASE WHEN date_add('day', 7 * k, c.desde) <= current_date
                THEN 'CIERRE' ELSE 'EN_CURSO' END    AS estado
    FROM cal c
    CROSS JOIN UNNEST(sequence(1, c.n_sem)) AS t (k)
    WHERE date_add('day', 7 * (k - 1), c.desde) <= current_date
),
ord AS (
    SELECT CASE WHEN partner_data_id LIKE 'WLAG%' THEN substr(partner_data_id, 3) ELSE partner_data_id END AS agencia_id,
           CAST(reservation_date AS DATE)  AS rd,
           CAST(confirmation_date AS DATE) AS cd,
           CAST(cancelation_date AS DATE)  AS xd
    FROM data.analytics.bi_transactional_fact_transactions
    WHERE reservation_year_month >= DATE '2026-10-01'
      AND reservation_date >= DATE '2026-10-05'
      AND parent_channel = 'Agencias afiliadas'
      AND line_of_business = 'B2B'
),
det AS (
    SELECT s.periodo, s.semana, o.agencia_id,
           date_diff('day', s.m_desde, o.rd) / 7 + 1 AS w,
           CASE WHEN o.cd IS NOT NULL AND o.cd <= s.foto
                     AND (o.xd IS NULL OR o.xd > s.foto) THEN 1 ELSE 0 END AS conf,
           CASE WHEN o.xd IS NULL OR o.xd > s.foto THEN 1 ELSE 0 END        AS viva
    FROM sem s
    JOIN ord o ON o.rd BETWEEN s.m_desde AND s.s_hasta
),
ag AS (
    SELECT periodo, semana, agencia_id,
           COUNT(DISTINCT CASE WHEN conf = 1 THEN w END) AS sc,
           COUNT(DISTINCT CASE WHEN viva = 1 THEN w END) AS sv
    FROM det
    GROUP BY 1, 2, 3
),
m AS (
    SELECT periodo, semana,
           COUNT(DISTINCT CASE WHEN sc >= 3 THEN agencia_id END) AS frecuentes_conf,
           COUNT(DISTINCT CASE WHEN sv >= 3 THEN agencia_id END) AS frecuentes_vivas,
           COUNT(DISTINCT CASE WHEN sc >= 1 THEN agencia_id END) AS compradoras_conf,
           COUNT(DISTINCT CASE WHEN sv >= 1 THEN agencia_id END) AS compradoras_vivas
    FROM ag
    GROUP BY 1, 2
),
latest AS (
    SELECT periodo, MAX(semana) AS ultima_semana FROM m GROUP BY 1
),
targets AS (
    SELECT '2026-10' AS mes, 4 AS semanas, 3396 AS target
    UNION ALL SELECT '2026-11', 4, 3584
    UNION ALL SELECT '2026-12', 5, 3483
    UNION ALL SELECT '2027-01', 4, 3749
    UNION ALL SELECT '2027-02', 4, 3670
    UNION ALL SELECT '2027-03', 4, 3913
)
SELECT t.mes AS mes_comercial,
       t.semanas AS semanas,
       COALESCE(s.estado, 'PENDIENTE') AS estado,
       COALESCE(m.frecuentes_conf, 0)  AS agencias_frecuentes,
       t.target AS target,
       ROUND(100.0 * COALESCE(m.frecuentes_conf, 0) / NULLIF(t.target, 0), 1) AS pct_cumplimiento
FROM targets t
LEFT JOIN latest l ON l.periodo = t.mes
LEFT JOIN sem s ON s.periodo = t.mes AND s.semana = l.ultima_semana
LEFT JOIN m ON m.periodo = t.mes AND m.semana = l.ultima_semana
ORDER BY t.mes
"""

# KR 2.1 semanal — agencias que cotizaron por semana (lunes) + acumulado unico del mes.
# La semana que cruza dos meses se parte por mes; el acumulado del ultimo cierre coincide con el mensual.
QUERY_KR21_SEM = """
WITH q AS (
    SELECT CAST(created_at AS DATE) AS d, UPPER(agency_code) AS a
    FROM data.raw.socrates_trip_quotations
    WHERE CAST(created_at AS DATE) BETWEEN DATE '2026-10-01' AND DATE '2027-03-31'
      AND channel_code IN ('hoteldo-html-classic','hoteldo-html-gold','hoteldo-html-platinum','hoteldo-html-silver')
      AND agency_code IS NOT NULL AND agency_code != ''
),
q2 AS (SELECT DATE_TRUNC('month', d) AS mes, DATE_TRUNC('week', d) AS semana_inicio, a FROM q),
sem AS (SELECT mes, semana_inicio, COUNT(DISTINCT a) AS agencias_semana FROM q2 GROUP BY 1, 2),
cum AS (
    SELECT s.mes, s.semana_inicio, COUNT(DISTINCT q2.a) AS agencias_acum_mes
    FROM (SELECT DISTINCT mes, semana_inicio FROM q2) s
    JOIN q2 ON q2.mes = s.mes AND q2.semana_inicio <= s.semana_inicio
    GROUP BY 1, 2
)
SELECT sem.mes, sem.semana_inicio, sem.agencias_semana, cum.agencias_acum_mes
FROM sem JOIN cum ON cum.mes = sem.mes AND cum.semana_inicio = sem.semana_inicio
ORDER BY 2, 1
"""

# KR 2.2 semanal — por semana comercial: agencias que compraron esa semana y agencias con compra en 3+ semanas (acumulado a esa semana).
QUERY_KR22_SEM = """
WITH cal AS (
    SELECT periodo, desde, hasta, n_sem
    FROM (VALUES
        ('2026-10', DATE '2026-10-05', DATE '2026-11-01', 4),
        ('2026-11', DATE '2026-11-02', DATE '2026-11-29', 4),
        ('2026-12', DATE '2026-11-30', DATE '2027-01-03', 5),
        ('2027-01', DATE '2027-01-04', DATE '2027-01-31', 4),
        ('2027-02', DATE '2027-02-01', DATE '2027-02-28', 4),
        ('2027-03', DATE '2027-03-01', DATE '2027-03-28', 4)
    ) AS v (periodo, desde, hasta, n_sem)
),
sem AS (
    SELECT c.periodo, c.n_sem, c.desde AS m_desde, k AS semana,
           date_add('day', 7 * (k - 1), c.desde)     AS s_desde,
           date_add('day', 7 * (k - 1) + 6, c.desde) AS s_hasta,
           LEAST(date_add('day', 7 * k, c.desde), current_date) AS foto,
           CASE WHEN date_add('day', 7 * k, c.desde) <= current_date
                THEN 'CIERRE' ELSE 'EN_CURSO' END    AS estado
    FROM cal c
    CROSS JOIN UNNEST(sequence(1, c.n_sem)) AS t (k)
    WHERE date_add('day', 7 * (k - 1), c.desde) <= current_date
),
ord AS (
    SELECT CASE WHEN partner_data_id LIKE 'WLAG%' THEN substr(partner_data_id, 3) ELSE partner_data_id END AS agencia_id,
           CAST(reservation_date AS DATE)  AS rd,
           CAST(confirmation_date AS DATE) AS cd,
           CAST(cancelation_date AS DATE)  AS xd
    FROM data.analytics.bi_transactional_fact_transactions
    WHERE reservation_year_month >= DATE '2026-10-01'
      AND reservation_date >= DATE '2026-10-05'
      AND parent_channel = 'Agencias afiliadas'
      AND line_of_business = 'B2B'
),
det AS (
    SELECT s.periodo, s.semana, o.agencia_id,
           date_diff('day', s.m_desde, o.rd) / 7 + 1 AS w,
           CASE WHEN o.cd IS NOT NULL AND o.cd <= s.foto
                     AND (o.xd IS NULL OR o.xd > s.foto) THEN 1 ELSE 0 END AS conf
    FROM sem s
    JOIN ord o ON o.rd BETWEEN s.m_desde AND s.s_hasta
),
ag AS (
    SELECT periodo, semana, agencia_id,
           COUNT(DISTINCT CASE WHEN conf = 1 THEN w END) AS sc,
           COUNT(DISTINCT CASE WHEN conf = 1 AND w = semana THEN w END) AS compro_semana
    FROM det
    GROUP BY 1, 2, 3
),
m AS (
    SELECT periodo, semana,
           COUNT(DISTINCT CASE WHEN sc >= 3 THEN agencia_id END) AS frecuentes_acum,
           COUNT(DISTINCT CASE WHEN compro_semana >= 1 THEN agencia_id END) AS compradoras_semana
    FROM ag
    GROUP BY 1, 2
)
SELECT s.periodo AS mes_comercial, s.semana, CAST(s.s_desde AS VARCHAR) AS semana_inicio, s.estado,
       COALESCE(m.compradoras_semana, 0) AS compradoras_semana,
       COALESCE(m.frecuentes_acum, 0)    AS frecuentes_acum
FROM sem s
LEFT JOIN m ON m.periodo = s.periodo AND m.semana = s.semana
ORDER BY s.periodo, s.semana
"""

# kr21/kr22 alimentan la pestaña Mensual (se refrescan el dia 1); *_prog son las mismas queries
# pero alimentan Progreso (se refrescan todos los dias); *_sem alimentan Semanal (lunes).
QUERIES = [
    ('kr21', QUERY_KR21),
    ('kr22', QUERY_KR22),
    ('kr21_prog', QUERY_KR21),
    ('kr22_prog', QUERY_KR22),
    ('kr21_sem', QUERY_KR21_SEM),
    ('kr22_sem', QUERY_KR22_SEM),
]

# ── Helpers ────────────────────────────────────────────────────────────────────

def rows_to_dicts(cols, rows):
    result = []
    for row in rows:
        d = {}
        for col, val in zip(cols, row):
            if hasattr(val, 'isoformat'):
                val = val.isoformat()[:10]
            elif isinstance(val, Decimal):
                val = float(val)
            d[col] = val
        result.append(d)
    return result

def run_queries():
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'skills' / 'datalake-query'))
    from presto_query import load_env, start_connection, execute_query
    env_path = str(Path(__file__).parent.parent.parent / '.env')
    load_env(env_path)
    print("Conectando a datalake.despegar.com...")
    conn = start_connection(catalog='data', schema='analytics')
    data = {}
    for kr_name, query in QUERIES:
        print(f"  -> {kr_name.upper()}...", end=' ', flush=True)
        try:
            cols, rows = execute_query(conn, query.strip())
            data[kr_name] = rows_to_dicts(cols, rows)
            print(f"OK ({len(rows)} filas)")
        except Exception as e:
            print(f"ERROR: {e}")
            data[kr_name] = []
    conn.close()
    return data

# ── HTML ───────────────────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tablero Producto B2B - HTML · H2 FY27</title>
<style>
:root{--bg:#f4f5f7;--surface:#fff;--surface2:#f8f9fa;--border:#e8e0f0;--border2:#d5c8e8;--purple:#6D28D9;--text:#1f2328;--muted:#57606a;--radius:8px;--shadow:0 1px 4px rgba(0,0,0,.08),0 4px 16px rgba(0,0,0,.06)}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:-apple-system,'Segoe UI',sans-serif;font-size:16px;min-height:100vh}
header{background:linear-gradient(90deg,#5B21B6,#7C3AED);padding:0 28px;height:72px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:300;box-shadow:0 2px 12px rgba(91,33,182,.4)}
.logo-main{color:#fff;font-size:15px;font-weight:700}.logo-main span{color:#C4B5FD}
.logo-sub{color:rgba(196,181,253,.65);font-size:10px;font-weight:500;letter-spacing:.05em;text-transform:uppercase;margin-top:2px}
.upd{background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.35);color:#fff;border-radius:6px;padding:5px 10px;font-size:13px;font-weight:600;line-height:1.2;white-space:nowrap}
.filter-bar{display:flex;gap:24px;padding:14px 28px;background:#fff;border-bottom:1px solid var(--border);align-items:center;flex-wrap:wrap;position:sticky;top:72px;z-index:200;box-shadow:0 1px 4px rgba(0,0,0,.06)}
.filter-group{display:flex;align-items:center;gap:8px}
.filter-label{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;white-space:nowrap}
.pill{padding:5px 16px;border-radius:20px;border:1.5px solid var(--border2);background:#fff;color:var(--muted);font-size:12px;font-weight:600;cursor:pointer;transition:all .15s;line-height:1.4}
.pill:hover{border-color:var(--purple);color:var(--purple)}
.pill.active{background:var(--purple);border-color:var(--purple);color:#fff}
main{padding:28px 40px;width:100%;max-width:none;margin:0}
.sec-title{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:14px;padding-bottom:8px;border-bottom:2px solid var(--border);margin-top:28px}
.sec-title:first-child{margin-top:0}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow);overflow:auto;margin-bottom:8px}
.card-hdr{background:#5457D9;color:#fff;padding:14px 20px;font-size:15px;font-weight:700}
table{width:100%;border-collapse:collapse;font-size:15px}
th{background:#7C7FFF;color:#fff;padding:12px 10px;text-align:center;font-weight:700;font-size:13px;white-space:nowrap;border-right:1px solid rgba(255,255,255,.15)}
th.th-kr{text-align:left;padding-left:16px;width:340px}
th.th-q{background:#5457D9;border-left:2px solid rgba(255,255,255,.25)}
td{padding:11px 8px;text-align:center;border-bottom:1px solid var(--border);border-right:1px solid var(--border)}
td.td-kr{text-align:left;padding-left:16px;font-weight:500}
td.td-q{border-left:2px solid var(--border2);font-weight:700}
tbody tr:hover{background:var(--surface2)}
tbody tr:last-child td{border-bottom:none}
.chip{display:inline-block;padding:5px 12px;border-radius:5px;font-size:14px;font-weight:700;min-width:52px;text-align:center}
.ok{background:#d4f4dd;color:#16a34a}.warn{background:#fff7cd;color:#b45309}.bad{background:#ffd8d3;color:#cf222e}.na{background:#f0f0f0;color:#999;font-size:11px;font-weight:400}
.tag{display:block;font-size:9px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;margin-top:3px}
.pend{font-size:10px;background:#FEF3C7;color:#92400E;border-radius:4px;padding:1px 6px;margin-left:6px;font-weight:700;white-space:nowrap}
#portal-btn{background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.35);color:#fff;border-radius:6px;padding:5px 10px;font-size:13px;font-weight:600;text-decoration:none;line-height:1.2;white-space:nowrap;transition:background .2s}
#portal-btn:hover{background:rgba(255,255,255,.25)}
body.dark{--bg:#0f172a;--surface:#1e293b;--surface2:#162032;--border:#334155;--border2:#475569;--text:#e2e8f0;--muted:#94a3b8;--purple:#A78BFA}
body.dark .ok{background:#14532d;color:#86efac}body.dark .warn{background:#713f12;color:#fde68a}body.dark .bad{background:#7f1d1d;color:#fca5a5}body.dark .na{background:#1e293b;color:#64748b}
body.dark .filter-bar{background:var(--surface)}
body.dark .pill{background:var(--surface2);color:var(--muted);border-color:var(--border2)}
body.dark .pill.active{background:var(--purple);border-color:var(--purple);color:#fff}
body.dark tbody tr:hover{background:#1e3a5f22}
body,main,.card,.filter-bar{transition:background .25s,border-color .25s,color .25s}
#theme-btn{background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.35);color:#fff;border-radius:6px;padding:5px 10px;font-size:15px;cursor:pointer;line-height:1;transition:background .2s}
#theme-btn:hover{background:rgba(255,255,255,.25)}
</style>
</head>
<body>
<header>
  <div>
    <div class="logo-main">Tablero Producto B2B <span>HTML</span></div>
    <div class="logo-sub">H2 FY27 · Octubre 2026 — Marzo 2027</div>
  </div>
  <div style="display:flex;align-items:center;gap:14px">
    <span class="upd">Actualizado: __UPDATED__</span>
    <a id="portal-btn" href="https://script.google.com/a/macros/despegar.com/s/AKfycbw7nuX4vsH9zFXOtLwxTpXszKAFKMGKH9uJhPr5JQkX5BYeZWLy7PaSiyyn-X-LqXx5tw/exec" target="_blank" rel="noopener" title="Portal de dashboards">🗂️ Portal de dashboards</a>
    <button id="theme-btn" onclick="toggleTheme()" title="Modo noche/día">🌙</button>
  </div>
</header>
<div class="filter-bar">
  <div class="filter-group" id="sq-filter">
    <span class="filter-label">Squad</span>
    <button class="pill sqpill active" onclick="setSq('all',this)">Todos</button>
    <button class="pill sqpill" onclick="setSq('ce',this)">C&amp;E</button>
    <button class="pill sqpill" onclick="setSq('es',this)">E&amp;S</button>
  </div>
  <div class="filter-group" style="margin-left:auto">
    <button class="pill tabpill active" onclick="setTab('mensual',this)">Mensual</button>
    <button class="pill tabpill" onclick="setTab('semanal',this)">Semanal</button>
    <button class="pill tabpill" onclick="setTab('progreso',this)">Progreso</button>
  </div>
</div>
<main id="root"></main>
<script>
var DATA = __DATA__;

var MONTHS=["2026-10","2026-11","2026-12","2027-01","2027-02","2027-03"];
var LABELS=["Oct","Nov","Dic","Ene","Feb","Mar"];

var SRC='m';
function dataKey(base){return (SRC==='p'&&DATA[base+'_prog'])?DATA[base+'_prog']:DATA[base];}
function rowByMonth(rows,field,m){return (rows||[]).find(function(r){return String(r[field]||"").substring(0,7)===m;});}

var KRS=[
  {id:"kr11",squad:"es",peso:0,pending:true,label:"KR 1.1 - GB de ventas por utilización de métodos de pago propios (HDOpay y Cta Cte)",targets:null,inverted:false,
   fmtA:function(v){return v!==null?Math.round(v).toLocaleString("es-AR"):null;},fmtT:function(v){return v.toLocaleString("es-AR");},
   getActual:function(i){return null;}},
  {id:"kr12",squad:"es",peso:0,pending:true,label:"KR 1.2 - CPO Costo por Order",targets:null,inverted:true,
   fmtA:function(v){return v!==null?v.toFixed(2):null;},fmtT:function(v){return '≤ '+v;},
   getActual:function(i){return null;}},
  {id:"kr21",squad:"ce",peso:1,label:"KR 2.1 - Aumentar la cantidad de agencias que utilizan cotizaciones",targets:[7500,7718,7601,7910,7818,8100],inverted:false,
   fmtA:function(v){return v!==null?Math.round(v).toLocaleString("es-AR"):null;},fmtT:function(v){return v.toLocaleString("es-AR");},
   getActual:function(i){var r=rowByMonth(dataKey('kr21'),"mes",MONTHS[i]);return r?r.agencias_cotizadoras:null;},
   getTarget:function(i){var r=rowByMonth(dataKey('kr21'),"mes",MONTHS[i]);return(r&&r.target!=null)?r.target:null;}},
  {id:"kr22",squad:"ce",peso:1,label:"KR 2.2 - Aumentar la cantidad de agencias que compran 3 o más semanas al mes",targets:[3396,3584,3483,3749,3670,3913],inverted:false,
   fmtA:function(v){return v!==null?Math.round(v).toLocaleString("es-AR"):null;},fmtT:function(v){return v.toLocaleString("es-AR");},
   getActual:function(i){var r=rowByMonth(dataKey('kr22'),"mes_comercial",MONTHS[i]);return(r&&r.estado!=="PENDIENTE")?r.agencias_frecuentes:null;},
   getTarget:function(i){var r=rowByMonth(dataKey('kr22'),"mes_comercial",MONTHS[i]);return(r&&r.target!=null)?r.target:null;}}
];
function tgtOf(kr,i){
  if(kr.getTarget){var t=kr.getTarget(i);if(t!==null)return t;}
  return kr.targets?kr.targets[i]:null;
}

function krNro(label){return label.split(/ - | — /)[0].trim();}
function krDesc(label){var p=label.split(/ - | — /);return p.slice(1).join(' - ').trim();}
var activeTab='mensual', activeSq='all';

function setTab(tab,btn){
  activeTab=tab;
  document.querySelectorAll('.tabpill').forEach(function(b){b.classList.remove('active');});
  btn.classList.add('active');
  render();
}
function setSq(sq,btn){
  activeSq=sq;
  document.querySelectorAll('.sqpill').forEach(function(b){b.classList.remove('active');});
  btn.classList.add('active');
  render();
}
function filteredKRS(){return activeSq==='all'?KRS:KRS.filter(function(k){return k.squad===activeSq;});}
function compliance(a,t,inv){if(a===null||t===null||t===0)return null;return inv?t/a*100:a/t*100;}
function effComp(pct){return pct===null?null:pct<70?0:pct>130?130:pct;}
function chip(pct){
  if(pct===null)return'<span class="chip na">N/D</span>';
  var eff=effComp(pct);
  var cls=eff>=100?'ok':eff>=80?'warn':'bad';
  var note=pct<70?'≡ 0':pct>130?'↑&thinsp;130':'';
  if(!note)return'<span class="chip '+cls+'">'+Math.round(pct)+'%</span>';
  return'<span class="chip '+cls+'" style="display:inline-flex;flex-direction:column;align-items:center;line-height:1.2;padding:3px 8px"><span>'+Math.round(pct)+'%</span><span style="font-size:10px;font-weight:600;opacity:.9">'+note+'</span></span>';
}
function avg(arr){var v=arr.filter(function(x){return x!==null;});return v.length?v.reduce(function(a,b){return a+b;},0)/v.length:null;}
function nowYm(){var d=new Date();return d.getFullYear()+"-"+(d.getMonth()<9?"0":"")+(d.getMonth()+1);}
function pesoPcts(krs){
  var tot=krs.reduce(function(s,k){return s+k.peso;},0);
  return krs.map(function(k){return k.peso>0&&tot>0?(k.peso/tot*100).toFixed(1)+'%':'—';});
}
var PEND_TAG='<span class="pend">pendiente</span>';

function renderMensual(){
  var krs=filteredKRS();
  var cur=nowYm();
  var idxs=[0,1,2,3,4,5];
  var html='';

  html+='<p class="sec-title">OKR Status FY27</p>';
  html+='<div style="display:flex;gap:10px;align-items:center;margin-bottom:14px;flex-wrap:wrap">';
  html+='<span style="font-size:11px;color:var(--muted);font-weight:600">Umbrales:</span>';
  html+='<span class="chip ok">&#8805; 100%&nbsp; en target</span>';
  html+='<span class="chip warn">80 – 99%&nbsp; cerca</span>';
  html+='<span class="chip bad">&lt; 80%&nbsp; lejos</span>';
  html+='<span class="chip na">N/D&nbsp; sin dato</span>';
  html+='<span style="font-size:11px;color:var(--muted);margin-left:4px">· el mes en curso se muestra como parcial</span>';
  html+='</div>';
  html+='<div class="card"><div class="card-hdr">Tablero Producto B2B - HTML · H2 FY27</div>';
  html+='<table><thead><tr><th style="width:65px;text-align:center">Nro KR</th><th class="th-kr">KR</th><th style="width:45px;text-align:center">Peso</th>';
  idxs.forEach(function(i){html+='<th>'+LABELS[i]+'</th>';});
  html+='<th class="th-q">Q3</th><th class="th-q">Q4</th><th class="th-q">H2</th>';
  html+='</tr></thead><tbody>';
  var pesos=pesoPcts(krs);
  krs.forEach(function(kr,ki){
    var comps=MONTHS.map(function(m,i){
      if(m>cur)return null;
      return compliance(kr.getActual(i),tgtOf(kr,i),kr.inverted);
    });
    var q3=avg([comps[0],comps[1],comps[2]]),q4=avg([comps[3],comps[4],comps[5]]),h2=avg(comps);
    html+='<tr><td style="text-align:center;font-weight:700;color:#5B21B6;white-space:nowrap;padding:11px 8px">'+krNro(kr.label)+'</td><td class="td-kr">'+krDesc(kr.label)+(kr.pending?PEND_TAG:'')+'</td><td style="text-align:center;font-weight:600;color:var(--muted);white-space:nowrap;padding:11px 6px">'+pesos[ki]+'</td>';
    idxs.forEach(function(i){
      if(MONTHS[i]>cur){html+='<td>-</td>';return;}
      html+='<td>'+chip(comps[i])+(MONTHS[i]===cur&&comps[i]!==null?'<span class="tag">parcial</span>':'')+'</td>';
    });
    html+='<td class="td-q">'+chip(q3)+'</td><td class="td-q">'+chip(q4)+'</td><td class="td-q">'+chip(h2)+'</td>';
    html+='</tr>';
  });
  var wComps=idxs.map(function(i){
    if(MONTHS[i]>cur)return null;
    var num=0,den=0;
    krs.forEach(function(kr){
      var c=effComp(compliance(kr.getActual(i),tgtOf(kr,i),kr.inverted));
      if(c!==null&&kr.peso>0){num+=c*kr.peso;den+=kr.peso;}
    });
    return den>0?num/den:null;
  });
  var wQ3=avg([wComps[0],wComps[1],wComps[2]]),wQ4=avg([wComps[3],wComps[4],wComps[5]]),wH2=avg(wComps);
  html+='<tr style="border-top:2px solid var(--border2);background:var(--surface2)">';
  html+='<td colspan="2" style="text-align:left;padding-left:16px;font-weight:700;font-size:12px;color:var(--purple)">Cumplimiento Total Ponderado</td>';
  html+='<td style="text-align:center;font-weight:700;font-size:11px;color:var(--purple)">100%</td>';
  idxs.forEach(function(i){html+='<td>'+(MONTHS[i]<=cur?chip(wComps[i]):'-')+'</td>';});
  html+='<td class="td-q">'+chip(wQ3)+'</td><td class="td-q">'+chip(wQ4)+'</td><td class="td-q">'+chip(wH2)+'</td>';
  html+='</tr></tbody></table></div>';

  html+='<p class="sec-title">Targets</p><div class="card"><table><thead><tr><th style="width:65px;text-align:center">Nro KR</th><th class="th-kr">KR</th>';
  idxs.forEach(function(i){html+='<th>'+LABELS[i]+'</th>';});
  html+='</tr></thead><tbody>';
  krs.forEach(function(kr){
    html+='<tr><td style="text-align:center;font-weight:700;color:#5B21B6;white-space:nowrap;padding:11px 8px">'+krNro(kr.label)+'</td><td class="td-kr">'+krDesc(kr.label)+'</td>';
    idxs.forEach(function(i){var t=tgtOf(kr,i);html+='<td>'+(t!==null?kr.fmtT(t):'<span class="chip na">N/A</span>')+'</td>';});
    html+='</tr>';
  });
  html+='</tbody></table></div>';

  html+='<p class="sec-title">Actuals</p><div class="card"><table><thead><tr><th style="width:65px;text-align:center">Nro KR</th><th class="th-kr">KR</th>';
  idxs.forEach(function(i){html+='<th>'+LABELS[i]+'</th>';});
  html+='</tr></thead><tbody>';
  krs.forEach(function(kr){
    html+='<tr><td style="text-align:center;font-weight:700;color:#5B21B6;white-space:nowrap;padding:11px 8px">'+krNro(kr.label)+'</td><td class="td-kr">'+krDesc(kr.label)+'</td>';
    idxs.forEach(function(i){
      var a=kr.getActual(i);
      html+='<td>'+(MONTHS[i]<=cur?(a!==null?kr.fmtA(a):'<span class="chip na">N/D</span>'):'-')+'</td>';
    });
    html+='</tr>';
  });
  html+='</tbody></table></div>';

  var link='style="color:var(--purple);font-weight:600;text-decoration:none;font-size:12px;border:1px solid var(--border2);padding:4px 10px;border-radius:4px"';
  html+='<p class="sec-title">Queries</p>';
  html+='<div class="card" style="padding:0;overflow:visible"><table style="font-size:13px;width:100%;border-collapse:collapse"><tbody>';
  html+='<tr style="border-bottom:1px solid var(--border)"><td style="padding:10px 16px;font-weight:700;color:#5B21B6;white-space:nowrap;width:80px">KR 2.1</td><td style="padding:10px 12px;text-align:left">Agencias que utilizan cotizaciones</td><td style="padding:10px 16px;white-space:nowrap"><a href="https://metabase.despegar.com/question/173704" target="_blank" '+link+'>Ver en Metabase ↗</a></td></tr>';
  html+='<tr><td style="padding:10px 16px;font-weight:700;color:#5B21B6;white-space:nowrap">KR 2.2</td><td style="padding:10px 12px;text-align:left">Agencias que compran 3 o más semanas al mes</td><td style="padding:10px 16px;white-space:nowrap"><a href="https://metabase.despegar.com/question/173707" target="_blank" '+link+'>Ver en Metabase ↗</a></td></tr>';
  html+='</tbody></table></div>';
  return html;
}

function renderProgreso(){
  var krs=filteredKRS();
  var cur=nowYm();
  var latestM=MONTHS.filter(function(m){return m<=cur;}).pop()||MONTHS[0];
  var latestI=MONTHS.indexOf(latestM);
  var html='';
  html+='<p class="sec-title">Estado Actual — '+LABELS[latestI]+(latestM===cur?' (parcial)':'')+'</p>';
  html+='<div class="card" style="margin-bottom:24px">';
  html+='<table><thead><tr><th style="width:65px;text-align:center">Nro KR</th><th class="th-kr" style="width:380px">KR</th><th style="width:45px;text-align:center">Peso</th><th>Actual</th><th>Target</th><th>Cumplimiento</th><th>Delta vs Target</th></tr></thead><tbody>';
  var pesos=pesoPcts(krs);
  krs.forEach(function(kr,ki){
    var a=kr.getActual(latestI),t=tgtOf(kr,latestI);
    var comp=compliance(a,t,kr.inverted);
    var delta='—',deltaColor='var(--muted)';
    if(a!==null&&t!==null){
      var diff=kr.inverted?(t-a):(a-t);
      delta=(diff>=0?'+':'')+Math.round(diff).toLocaleString('es-AR');
      deltaColor=(kr.inverted?(a<=t):(a>=t))?'#16a34a':'#cf222e';
    }
    html+='<tr><td style="text-align:center;font-weight:700;color:#5B21B6;white-space:nowrap;padding:11px 8px">'+krNro(kr.label)+'</td><td class="td-kr">'+krDesc(kr.label)+(kr.pending?PEND_TAG:'')+'</td><td style="text-align:center;font-weight:600;color:var(--muted);white-space:nowrap;padding:11px 6px">'+pesos[ki]+'</td>';
    html+='<td style="font-weight:700">'+(a!==null?kr.fmtA(a):'<span class="chip na">N/D</span>')+'</td>';
    html+='<td>'+(t!==null?kr.fmtT(t):'<span class="chip na">N/A</span>')+'</td>';
    html+='<td>'+chip(comp)+'</td>';
    html+='<td style="font-weight:700;color:'+deltaColor+'">'+delta+'</td></tr>';
  });
  html+='</tbody></table></div>';

  html+='<p class="sec-title">Progreso al Target</p>';
  krs.forEach(function(kr){
    var a=kr.getActual(latestI),t=tgtOf(kr,latestI);
    var comp=compliance(a,t,kr.inverted);
    var barPct=comp!==null?Math.min(comp,100):0;
    var barColor=comp!==null?(comp>=100?'#22c55e':comp>=80?'#eab308':'#ef4444'):'#ddd';
    html+='<div class="card" style="padding:16px 20px;margin-bottom:8px">';
    html+='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">';
    html+='<span><span style="font-weight:700;color:#5B21B6;font-size:12px;margin-right:8px">'+krNro(kr.label)+'</span><span style="font-weight:600;font-size:13px">'+krDesc(kr.label)+(kr.pending?PEND_TAG:'')+'</span></span>';
    html+='<span style="font-size:13px">'+(a!==null?kr.fmtA(a)+' / '+(t!==null?kr.fmtT(t):'?'):'N/D')+'&nbsp;&nbsp;'+chip(comp)+'</span>';
    html+='</div>';
    html+='<div style="background:#f0f0f0;border-radius:6px;height:10px"><div style="background:'+barColor+';width:'+barPct+'%;height:10px;border-radius:6px;transition:width .4s"></div></div>';
    html+='</div>';
  });
  return html;
}

var MON_SHORT=['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
function wkLabel(s,floor){
  var d=(floor&&floor>s)?floor:s,p=String(d).split('-');
  return p[2]+'-'+MON_SHORT[parseInt(p[1],10)-1];
}
function renderSemanal(){
  var cur=nowYm();
  var krs=filteredKRS();
  var BLOCKS=[
    {id:'kr21',rows:(DATA.kr21_sem||[]).map(function(r){return{m:String(r.mes).substring(0,7),start:r.semana_inicio,floor:r.mes,sem:r.agencias_semana,acum:r.agencias_acum_mes,partial:false};}),
     semLbl:'Cotizaron en la semana',acumLbl:'Agencias únicas acumuladas del mes'},
    {id:'kr22',rows:(DATA.kr22_sem||[]).map(function(r){return{m:r.mes_comercial,start:r.semana_inicio,floor:null,sem:r.compradoras_semana,acum:r.frecuentes_acum,partial:r.estado==='EN_CURSO'};}),
     semLbl:'Compraron en la semana',acumLbl:'Con compra en 3+ semanas (acumulado)'}
  ];
  var html='<p class="sec-title">Seguimiento Semanal</p>';
  html+='<div style="display:flex;gap:10px;align-items:center;margin-bottom:14px;flex-wrap:wrap">';
  html+='<span style="font-size:11px;color:var(--muted);font-weight:600">Umbrales:</span>';
  html+='<span class="chip ok">&#8805; 100%&nbsp; en target</span><span class="chip warn">80 – 99%&nbsp; cerca</span><span class="chip bad">&lt; 80%&nbsp; lejos</span><span class="chip na">N/D&nbsp; sin dato</span>';
  html+='<span style="font-size:11px;color:var(--muted);margin-left:4px">· Acumulado del mes hasta cada semana vs target mensual · la última semana puede ser parcial</span>';
  html+='</div>';
  var shown=0;
  BLOCKS.forEach(function(b){
    var kr=krs.find(function(k){return k.id===b.id;});
    if(!kr)return;
    shown++;
    var rows=b.rows.filter(function(r){return r.m<=cur;});
    html+='<div class="card"><div class="card-hdr">'+krNro(kr.label)+' · '+krDesc(kr.label)+'</div>';
    if(!rows.length){html+='<div style="padding:20px;color:var(--muted)">Sin datos todavía.</div></div>';return;}
    html+='<table><thead><tr><th class="th-kr" style="width:260px"></th>';
    rows.forEach(function(r){html+='<th>'+wkLabel(r.start,r.floor)+'</th>';});
    html+='</tr></thead><tbody>';
    var lastOfCur=-1;rows.forEach(function(r,i){if(r.m===cur)lastOfCur=i;});
    function cell(i,r,inner){return '<td>'+inner+(i===lastOfCur||r.partial?'<span class="tag">parcial</span>':'')+'</td>';}
    html+='<tr><td class="td-kr" style="color:var(--muted)">'+b.semLbl+'</td>';
    rows.forEach(function(r,i){html+=cell(i,r,Math.round(r.sem).toLocaleString('es-AR'));});
    html+='</tr><tr style="background:var(--surface2)"><td class="td-kr" style="font-weight:700;color:var(--purple)">'+b.acumLbl+'</td>';
    rows.forEach(function(r,i){html+=cell(i,r,'<b>'+Math.round(r.acum).toLocaleString('es-AR')+'</b>');});
    html+='</tr><tr><td class="td-kr" style="color:var(--muted)">Target mensual</td>';
    rows.forEach(function(r){var t=tgtOf(kr,MONTHS.indexOf(r.m));html+='<td style="color:var(--muted)">'+(t!==null?kr.fmtT(t):'—')+'</td>';});
    html+='</tr><tr><td class="td-kr" style="font-weight:700">Cumplimiento acumulado</td>';
    rows.forEach(function(r){var t=tgtOf(kr,MONTHS.indexOf(r.m));html+='<td>'+chip(compliance(r.acum,t,false))+'</td>';});
    html+='</tr></tbody></table></div>';
  });
  if(!shown)html+='<div class="card" style="padding:20px;color:var(--muted)">Los KRs de E&amp;S están pendientes de definición.</div>';
  return html;
}

function render(){
  SRC=activeTab==='progreso'?'p':'m';
  document.getElementById('root').innerHTML=activeTab==='progreso'?renderProgreso():activeTab==='semanal'?renderSemanal():renderMensual();
}
function toggleTheme(){
  var dark=document.body.classList.toggle('dark');
  document.getElementById('theme-btn').textContent=dark?'☀':'🌙';
  try{localStorage.setItem('okrs_theme',dark?'dark':'light');}catch(e){}
}
(function(){try{if(localStorage.getItem('okrs_theme')==='dark'){document.body.classList.add('dark');document.getElementById('theme-btn').textContent='☀';}}catch(e){}})();
render();
</script>
</body>
</html>"""

def to_json_native(obj):
    if obj is None:
        return None
    if isinstance(obj, (bool, int, float)):
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
    return html.replace('__UPDATED__', updated)

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    data = run_queries()
    updated = datetime.now().strftime('%Y-%m-%d %H:%M')
    (Path(__file__).parent / 'data.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    html = build_html(data, updated)

    output = Path(__file__).parent / 'okrs_dashboard_h2.html'
    output.write_text(html, encoding='utf-8')

    print(f"\nDashboard generado: {output}")

if __name__ == '__main__':
    main()
