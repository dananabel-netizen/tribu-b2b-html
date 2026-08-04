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

# ── Queries ────────────────────────────────────────────────────────────────────

QUERY_KR21 = """
WITH base AS (
    SELECT
        r.id AS reservation_id,
        CASE WHEN bi.transaction_status = 'Cancelado' AND ca.type = 'TIMEOUT_CLIENT'
             THEN 'Time_out_client' ELSE r.status END AS status,
        DATE_TRUNC('month', CAST(dc.deadline AS DATE)) AS mes_deadline,
        r.country_code,
        SUM(bi.gb) AS gb_reserva,
        ca.type as tipo_cancel,
        bi.transaction_status as status_reserva
    FROM lake.chewie_reservation r
    LEFT JOIN lake.chewie_cancelation ca ON ca.reservation_id = r.oid
    LEFT JOIN lake.chewie_deferred_condition dc ON r.oid = dc.reservation_id
    LEFT JOIN analytics.bi_sales_fact_sales_recognition bi
        ON bi.transaction_code = CAST(r.id AS BIGINT)
        AND bi.partition_period >= '2024-01'
        AND bi.channel IN ('hoteldo-html-platinum','hoteldo-html-gold','hoteldo-html-silver','hoteldo-html-classic')
    WHERE r.last_version = TRUE
        AND r.channel LIKE 'hoteldo%'
        AND dc.reason = 'PROMISE-B2B'
        AND dc.deadline IS NOT NULL
    GROUP BY r.id, r.status, DATE_TRUNC('month', CAST(dc.deadline AS DATE)),
             r.country_code, bi.transaction_status, ca.type
)
SELECT
    mes_deadline,
    status,
    COUNT(DISTINCT reservation_id) AS reservas,
    SUM(gb_reserva) AS gb
FROM base GROUP BY 1, 2 ORDER BY 1, 2
"""

QUERY_KR22 = """
SELECT
    sum(case when coalesce(n.flg_agente_staff, 0) = 1 then 1 else 0 end) as cant_staff,
    sum(case when coalesce(n.flg_agente_staff, 0) = 0 then 1 else 0 end) as cant_no_staff,
    count(*) as cant_total,
    count(distinct trx.agency_code) as cant_agencias_unicas,
    rfh.creation_yearmonth
FROM (
    SELECT *,
        case when starts_with(created_user, 'ext.') then substr(created_user, 5)
             else created_user end as created_user_ajustado
    FROM analytics.bi_requests_fact_header
    WHERE creation_yearmonth >= '2025-01'
) rfh
INNER JOIN (
    SELECT * FROM analytics.bi_transactional_fact_transactions
    WHERE reservation_year_month IS NOT NULL AND line_of_business = 'B2B'
) trx ON trx.transaction_code = rfh.transaction_code
LEFT JOIN (
    SELECT DISTINCT
        case when starts_with(ad_username, 'ext.') then substr(ad_username, 5)
             else ad_username end as ad_username_ajustado,
        1 as flg_agente_staff
    FROM lake.asrpt_payroll
) n ON n.ad_username_ajustado = rfh.created_user_ajustado
WHERE rfh.creation_yearmonth IN ('2026-03','2026-04','2026-05','2026-06','2026-07','2026-08','2026-09','2026-10','2026-11','2026-12','2027-01','2027-02','2027-03')
  AND trx.channel LIKE '%hoteldo-html%'
GROUP BY rfh.creation_yearmonth ORDER BY rfh.creation_yearmonth
"""

QUERY_KR31 = """
WITH forecast_budget AS (
    (SELECT YEAR(DATE_PARSE(fecha, '%d/%m/%Y')) as year, CAST(no_mes_proyectado AS INTEGER) as month,
        case when producto='Cars' then 'Autos' when producto='Cruises' then 'Cruceros'
             when producto='Dest. Serv.' then 'Dest. Serv.' when producto='Flights' then 'Vuelos'
             when producto='Hotels' then 'Hoteles' when producto='Insurance' then 'Asistencia al viajero'
             when producto='Packages General' then 'Paquetes' when producto='Vacation Rentals' then 'Alquileres' end as producto,
        case when pais='Argentina' then 'AR' when pais='Brasil' then 'BR' when pais='Chile' then 'CL'
             when pais='Colombia' then 'CO' when pais='Ecuador' then 'EC' when pais='Mexico' then 'MX'
             when pais='Peru' then 'PE' when pais='Uruguay' then 'UY' else 'O' end as pais,
        'FCST' AS source, SUM(CAST(net_revenue AS DECIMAL(15,6))) as net_revenue
    FROM raw.b2bfc1_gd WHERE lob_canal = 'B2B-MIN' GROUP BY 1,2,3,4,5)
    UNION ALL
    (SELECT YEAR(DATE_PARSE(fecha, '%d-%m-%Y')) + 2000 as year, CAST(no_mes_proyectado AS INTEGER) as month,
        case when producto='Cars' then 'Autos' when producto='Cruises' then 'Cruceros'
             when producto='Dest. Serv.' then 'Dest. Serv.' when producto='Flights' then 'Vuelos'
             when producto='Hotels' then 'Hoteles' when producto='Insurance' then 'Asistencia al viajero'
             when producto='Packages General' then 'Paquetes' when producto='Vacation Rentals' then 'Alquileres' end as producto,
        case when pais='Argentina' then 'AR' when pais='Brasil' then 'BR' when pais='Chile' then 'CL'
             when pais='Colombia' then 'CO' when pais='Ecuador' then 'EC' when pais='Mexico' then 'MX'
             when pais='Peru' then 'PE' when pais='Uruguay' then 'UY' else 'O' end as pais,
        'BDGT' AS source, SUM(CAST(net_revenue AS DECIMAL(15,6))) as net_revenue
    FROM raw.b2b_budget_gd WHERE lob_canal = 'B2B-MIN' GROUP BY 1,2,3,4,5)
), real_data AS (
    SELECT DISTINCT year(fh.gestion_date) as year, month(fh.gestion_date) as month,
        CASE WHEN fh.partner_id IN ('AP12142','AP12961','AP12767','AP12539','AP12792',
                                     'AP12149','AP12148','AG00015606','AP13029','AP13030',
                                     'AP13091','AP13104','AG00015611') THEN 'O'
             WHEN fh.country_code IN ('MX','BR','CO','AR','EC','PE','CL','UY') THEN fh.country_code
             ELSE 'O' END AS pais,
        case when fh.buy_type_code in ('Bundles','Carrito') then 'Paquetes'
             when fh.buy_type_code in ('Actividades','Traslados') then 'Dest. Serv'
             else fh.buy_type_code end as producto,
        sum(CASE
            WHEN fh.country_code='BR' AND fh.parent_channel='Agencias afiliadas' AND fh.product NOT IN ('Vuelos') THEN (pnl.net_revenues_usd - pnl.affiliates_usd) * 0.92
            WHEN fh.country_code='MX' THEN pnl.net_revenues_usd * 0.85
            WHEN fh.country_code='CO' THEN pnl.net_revenues_usd * 0.84
            WHEN fh.country_code='CL' THEN pnl.net_revenues_usd * 0.92
            WHEN fh.country_code IN ('US','PA') THEN pnl.net_revenues_usd * 0.80
            WHEN fh.country_code='BR' AND fh.product IN ('Vuelos') THEN pnl.net_revenues_usd * 0.92
            ELSE pnl.net_revenues_usd * 0.97 END) as net_revenue
    FROM analytics.bi_sales_fact_sales_recognition fh
        LEFT JOIN data.analytics.bi_pnlop_fact_current_model pnl ON fh.product_id = pnl.product_id
        LEFT JOIN data.analytics.bi_transactional_fact_transactions t ON t.transaction_code = CAST(pnl.transaction_code AS VARCHAR)
        LEFT JOIN data.tmp.correccion_be be ON CAST(be.product_id AS VARCHAR) = CAST(pnl.product_id AS VARCHAR)
        LEFT JOIN data.tmp.mktg_funds d ON CAST(d.product_id AS VARCHAR) = CAST(pnl.product_id AS VARCHAR)
        LEFT JOIN data.tmp.mkt_funds_bd1 mkt ON mkt.product_id = fh.product_id
    WHERE fh.gestion_date >= CAST('2025-01-01' AS DATE)
        AND fh.partition_period >= '2025-01-01'
        AND fh.lob_gestion IN ('stg__sales_b2bnohoteldo','stg_sales__b2bhoteldo')
        AND pnl.line_of_business = 'B2B'
        AND t.reservation_year_month >= CAST('2025-01-01' AS DATE)
        AND pnl.date_reservation_year_month >= '2025-01'
        AND fh.parent_channel = 'Agencias afiliadas'
    GROUP BY 1,2,3,4
), main AS (
    SELECT COALESCE(f.year,rd.year) as year, COALESCE(f.month,rd.month) as month,
        CONCAT(CAST(COALESCE(f.year,rd.year) AS VARCHAR),'-',LPAD(CAST(COALESCE(f.month,rd.month) AS VARCHAR),2,'0')) as periodo,
        ROUND(f.net_revenue,2) as net_revenue_target, ROUND(rd.net_revenue,2) as net_revenue_real
    FROM forecast_budget f
        FULL JOIN real_data rd ON f.year=rd.year AND f.month=rd.month AND f.pais=rd.pais AND f.producto=rd.producto
    WHERE COALESCE(f.year,rd.year) IN (2025,2026)
    ORDER BY year, month
)
SELECT periodo, SUM(net_revenue_real) as net_rev_real, SUM(net_revenue_target) as net_rev_target
FROM main GROUP BY 1 ORDER BY 1
"""

QUERY_KR32 = """
WITH parametros AS (
    SELECT DATE '2026-01-01' AS fecha_inicio, CURRENT_DATE AS fecha_fin
),
cotizaciones AS (
    SELECT DATE_TRUNC('month', CAST(created_at AS DATE)) AS mes,
           UPPER(agency_code) AS agency_code,
           COUNT(*) AS cotizaciones_realizadas
    FROM raw.socrates_trip_quotations CROSS JOIN parametros p
    WHERE CAST(created_at AS DATE) BETWEEN p.fecha_inicio AND p.fecha_fin
      AND channel_code IN ('hoteldo-html-classic','hoteldo-html-gold','hoteldo-html-platinum','hoteldo-html-silver')
      AND agency_code IS NOT NULL AND agency_code != ''
    GROUP BY 1, 2
),
ventas AS (
    SELECT DISTINCT DATE_TRUNC('month', bi.creation_date) AS mes, UPPER(bi.agency_code) AS agency_code
    FROM analytics.bi_sales_fact_sales_recognition bi CROSS JOIN parametros p
    WHERE bi.creation_date BETWEEN p.fecha_inicio AND p.fecha_fin
      AND bi.transaction_status = 'Confirmado'
      AND bi.channel IN ('hoteldo-html-classic','hoteldo-html-gold','hoteldo-html-platinum','hoteldo-html-silver')
      AND bi.partition_period >= '2026-01' AND bi.agency_code IS NOT NULL
)
SELECT c.mes,
    COUNT(DISTINCT c.agency_code) AS agencias_cotizadoras,
    COUNT(DISTINCT CASE WHEN v.agency_code IS NOT NULL THEN c.agency_code END) AS agencias_cotizaron_y_vendieron,
    SUM(c.cotizaciones_realizadas) AS cotizaciones_realizadas,
    ROUND(100.0 * COUNT(DISTINCT CASE WHEN v.agency_code IS NOT NULL THEN c.agency_code END)
        / NULLIF(COUNT(DISTINCT c.agency_code),0), 2) AS pct_activacion_comercial
FROM cotizaciones c LEFT JOIN ventas v ON c.agency_code=v.agency_code AND c.mes=v.mes
GROUP BY 1 ORDER BY 1
"""

QUERY_KR33 = """
WITH base_reservas AS (
  SELECT
    YEAR(bi.creation_date) * 100 + CAST(MONTH(bi.creation_date) AS INT) AS mes,
    bi.partner_id AS partner_id,
    COUNT(DISTINCT bi.transaction_code) AS reservas
  FROM analytics.bi_sales_fact_sales_recognition bi
  LEFT JOIN lake.chewie_reservation c
    ON bi.transaction_code = CAST(c.id AS BIGINT) AND c.last_version = TRUE
  LEFT JOIN lake.channels_bo_product product
    ON bi.origin_product_id = product.transaction_id
  WHERE bi.channel IN (
      'hoteldo-html-platinum', 'hoteldo-html-gold', 'hoteldo-html-silver',
      'hoteldo-html-classic', 'travel-agency-bo', 'travel-agency-whitelabel'
    )
    AND bi.creation_date > DATE '2023-01-01'
    AND bi.partition_period >= '2023-01'
    AND c.status NOT IN ('TO_CANCEL')
  GROUP BY 1, 2
),
agencias_1_3 AS (
  SELECT
    mes AS mes_previo,
    partner_id,
    reservas AS reservas_previo,
    CASE WHEN mes % 100 = 12 THEN (CAST(mes / 100 AS INT) + 1) * 100 + 1 ELSE mes + 1 END AS mes_evaluacion
  FROM base_reservas
  WHERE reservas BETWEEN 1 AND 3
),
totales_mes AS (
  SELECT mes, COUNT(DISTINCT partner_id) AS total_agencias
  FROM base_reservas
  GROUP BY mes
)
SELECT
  prev.mes_previo,
  prev.mes_evaluacion,
  ta_prev.total_agencias AS agencias_total_previo,
  ta_eval.total_agencias AS agencias_total_evaluado,
  COUNT(DISTINCT prev.partner_id) AS agencias_1_3_previo,
  COUNT(DISTINCT CASE WHEN COALESCE(eval.reservas, 0) >= prev.reservas_previo + 2 THEN prev.partner_id END) AS agencias_aumentaron,
  ROUND(
    COUNT(DISTINCT CASE WHEN COALESCE(eval.reservas, 0) >= prev.reservas_previo + 2 THEN prev.partner_id END) * 100.0
    / NULLIF(COUNT(DISTINCT prev.partner_id), 0), 2
  ) AS pct_aumento,
  25.0 AS target_pct,
  ROUND(
    COUNT(DISTINCT CASE WHEN COALESCE(eval.reservas, 0) >= prev.reservas_previo + 2 THEN prev.partner_id END) * 100.0
    / NULLIF(COUNT(DISTINCT prev.partner_id), 0) / 25.0 * 100, 2
  ) AS pct_cumplimiento_target
FROM agencias_1_3 prev
LEFT JOIN base_reservas eval ON prev.partner_id = eval.partner_id AND eval.mes = prev.mes_evaluacion
LEFT JOIN totales_mes ta_prev ON ta_prev.mes = prev.mes_previo
LEFT JOIN totales_mes ta_eval ON ta_eval.mes = prev.mes_evaluacion
WHERE prev.mes_previo >= 202501
GROUP BY 1, 2, 3, 4
ORDER BY 1 ASC
LIMIT 1048575
"""

QUERY_KR33_SEM = """
WITH base_reservas AS (
  SELECT
    YEAR(bi.creation_date) * 100 + CAST(MONTH(bi.creation_date) AS INT) AS mes,
    bi.partner_id,
    COUNT(DISTINCT bi.transaction_code) AS reservas
  FROM analytics.bi_sales_fact_sales_recognition bi
  LEFT JOIN lake.chewie_reservation c ON bi.transaction_code = CAST(c.id AS BIGINT) AND c.last_version = TRUE
  LEFT JOIN lake.channels_bo_product product ON bi.origin_product_id = product.transaction_id
  WHERE bi.channel IN ('hoteldo-html-platinum','hoteldo-html-gold','hoteldo-html-silver','hoteldo-html-classic','travel-agency-bo','travel-agency-whitelabel')
    AND bi.creation_date > DATE '2023-01-01'
    AND bi.partition_period >= '2023-01'
    AND c.status NOT IN ('TO_CANCEL')
  GROUP BY 1, 2
),
agencias_1_3 AS (
  SELECT
    mes AS mes_previo,
    partner_id,
    reservas AS reservas_previo,
    CASE WHEN mes % 100 = 12 THEN (CAST(mes / 100 AS INT) + 1) * 100 + 1 ELSE mes + 1 END AS mes_evaluacion
  FROM base_reservas
  WHERE reservas BETWEEN 1 AND 3
),
mensual AS (
  SELECT
    prev.mes_evaluacion,
    ROUND(COUNT(DISTINCT CASE WHEN COALESCE(eval.reservas, 0) >= prev.reservas_previo + 2 THEN prev.partner_id END) * 100.0
      / NULLIF(COUNT(DISTINCT prev.partner_id), 0), 2) AS pct_aumento
  FROM agencias_1_3 prev
  LEFT JOIN base_reservas eval ON prev.partner_id = eval.partner_id AND eval.mes = prev.mes_evaluacion
  WHERE prev.mes_previo >= 202501
  GROUP BY 1
),
semanas AS (
  SELECT DISTINCT DATE_TRUNC('week', bi.creation_date) AS semana_inicio,
    YEAR(bi.creation_date) * 100 + CAST(MONTH(bi.creation_date) AS INT) AS mes
  FROM analytics.bi_sales_fact_sales_recognition bi
  WHERE bi.creation_date >= DATE '2026-04-01' AND bi.partition_period >= '2026-04'
)
SELECT s.semana_inicio, m.pct_aumento
FROM semanas s
JOIN mensual m ON m.mes_evaluacion = s.mes
ORDER BY 1
LIMIT 1048575
"""

QUERY_KR33_SEM_CUM = """
WITH base_reservas_mes AS (
  SELECT
    YEAR(bi.creation_date) * 100 + CAST(MONTH(bi.creation_date) AS INT) AS mes,
    bi.partner_id,
    COUNT(DISTINCT bi.transaction_code) AS reservas
  FROM analytics.bi_sales_fact_sales_recognition bi
  LEFT JOIN lake.chewie_reservation c ON bi.transaction_code = CAST(c.id AS BIGINT) AND c.last_version = TRUE
  WHERE bi.channel IN ('hoteldo-html-platinum','hoteldo-html-gold','hoteldo-html-silver','hoteldo-html-classic','travel-agency-bo','travel-agency-whitelabel')
    AND bi.creation_date > DATE '2023-01-01'
    AND bi.partition_period >= '2023-01'
    AND c.status NOT IN ('TO_CANCEL')
  GROUP BY 1, 2
),
agencias_1_3 AS (
  SELECT
    mes AS mes_previo,
    partner_id,
    reservas AS reservas_previo,
    CASE WHEN mes % 100 = 12 THEN (CAST(mes / 100 AS INT) + 1) * 100 + 1 ELSE mes + 1 END AS mes_evaluacion
  FROM base_reservas_mes
  WHERE reservas BETWEEN 1 AND 3 AND mes >= 202501
),
base_semanal AS (
  SELECT
    DATE_TRUNC('week', bi.creation_date) AS semana_inicio,
    YEAR(bi.creation_date) * 100 + CAST(MONTH(bi.creation_date) AS INT) AS mes,
    bi.partner_id,
    COUNT(DISTINCT bi.transaction_code) AS reservas
  FROM analytics.bi_sales_fact_sales_recognition bi
  LEFT JOIN lake.chewie_reservation c ON bi.transaction_code = CAST(c.id AS BIGINT) AND c.last_version = TRUE
  WHERE bi.channel IN ('hoteldo-html-platinum','hoteldo-html-gold','hoteldo-html-silver','hoteldo-html-classic','travel-agency-bo','travel-agency-whitelabel')
    AND bi.creation_date >= DATE '2026-04-01'
    AND bi.partition_period >= '2026-04'
    AND c.status NOT IN ('TO_CANCEL')
  GROUP BY 1, 2, 3
),
semanas AS (SELECT DISTINCT semana_inicio, mes FROM base_semanal),
reservas_acum AS (
  SELECT s.semana_inicio, s.mes, bs.partner_id, SUM(bs.reservas) AS reservas_acum
  FROM semanas s
  JOIN base_semanal bs ON bs.mes = s.mes AND bs.semana_inicio <= s.semana_inicio
  GROUP BY 1, 2, 3
)
SELECT
  s.semana_inicio,
  COUNT(DISTINCT prev.partner_id) AS agencias_1_3_previo,
  COUNT(DISTINCT CASE WHEN COALESCE(ra.reservas_acum, 0) >= prev.reservas_previo + 2 THEN prev.partner_id END) AS agencias_aumentaron,
  ROUND(
    COUNT(DISTINCT CASE WHEN COALESCE(ra.reservas_acum, 0) >= prev.reservas_previo + 2 THEN prev.partner_id END) * 100.0
    / NULLIF(COUNT(DISTINCT prev.partner_id), 0), 2
  ) AS pct_aumento_acum
FROM semanas s
JOIN agencias_1_3 prev ON prev.mes_evaluacion = s.mes
LEFT JOIN reservas_acum ra ON ra.partner_id = prev.partner_id AND ra.semana_inicio = s.semana_inicio
GROUP BY 1
ORDER BY 1
LIMIT 1048575
"""

QUERY_KR21_SEM = """
WITH base AS (
    SELECT
        r.id AS reservation_id,
        CASE WHEN bi.transaction_status = 'Cancelado' AND ca.type = 'TIMEOUT_CLIENT'
             THEN 'Time_out_client' ELSE r.status END AS status,
        DATE_TRUNC('week', CAST(dc.deadline AS DATE)) AS semana_inicio
    FROM data.lake.chewie_reservation r
    LEFT JOIN data.lake.chewie_cancelation ca ON ca.reservation_id = r.oid
    LEFT JOIN data.lake.chewie_deferred_condition dc ON r.oid = dc.reservation_id
    LEFT JOIN data.analytics.bi_sales_fact_sales_recognition bi
        ON bi.transaction_code = CAST(r.id AS BIGINT)
        AND bi.partition_period >= '2024-01'
        AND bi.channel IN ('hoteldo-html-platinum','hoteldo-html-gold','hoteldo-html-silver','hoteldo-html-classic')
    WHERE r.last_version = TRUE
        AND r.channel LIKE 'hoteldo%'
        AND dc.reason = 'PROMISE-B2B'
        AND dc.deadline IS NOT NULL
        AND CAST(dc.deadline AS DATE) >= DATE '2026-04-01'
    GROUP BY r.id, r.status, DATE_TRUNC('week', CAST(dc.deadline AS DATE)),
             bi.transaction_status, ca.type
)
SELECT
    semana_inicio,
    COUNT(DISTINCT reservation_id) AS total_reservas,
    COUNT(DISTINCT CASE WHEN status = 'Time_out_client' THEN reservation_id END) AS reservas_timeout_client,
    ROUND(100.0 * COUNT(DISTINCT CASE WHEN status = 'Time_out_client' THEN reservation_id END)
        / NULLIF(COUNT(DISTINCT reservation_id), 0), 2) AS pct_timeout_client
FROM base GROUP BY 1 ORDER BY 1
"""

QUERY_KR21_SEM_CUM = """
WITH base AS (
    SELECT
        r.id AS reservation_id,
        DATE_TRUNC('month', CAST(dc.deadline AS DATE)) AS mes_deadline,
        DATE_TRUNC('week',  CAST(dc.deadline AS DATE)) AS semana_inicio,
        CASE WHEN bi.transaction_status = 'Cancelado' AND ca.type = 'TIMEOUT_CLIENT'
             THEN 'Time_out_client' ELSE r.status END AS status
    FROM data.lake.chewie_reservation r
    LEFT JOIN data.lake.chewie_cancelation ca ON ca.reservation_id = r.oid
    LEFT JOIN data.lake.chewie_deferred_condition dc ON r.oid = dc.reservation_id
    LEFT JOIN data.analytics.bi_sales_fact_sales_recognition bi
        ON bi.transaction_code = CAST(r.id AS BIGINT)
        AND bi.partition_period >= '2024-01'
        AND bi.channel IN ('hoteldo-html-platinum','hoteldo-html-gold','hoteldo-html-silver','hoteldo-html-classic')
    WHERE r.last_version = TRUE
        AND r.channel LIKE 'hoteldo%'
        AND dc.reason = 'PROMISE-B2B'
        AND dc.deadline IS NOT NULL
        AND CAST(dc.deadline AS DATE) >= DATE '2026-04-01'
    GROUP BY 1, 2, 3, 4
),
semanas AS (SELECT DISTINCT semana_inicio, mes_deadline FROM base)
SELECT
    s.semana_inicio,
    s.mes_deadline,
    COUNT(DISTINCT b.reservation_id) AS total_reservas_acum,
    COUNT(DISTINCT CASE WHEN b.status = 'Time_out_client' THEN b.reservation_id END) AS timeouts_acum,
    ROUND(100.0 * COUNT(DISTINCT CASE WHEN b.status = 'Time_out_client' THEN b.reservation_id END)
        / NULLIF(COUNT(DISTINCT b.reservation_id), 0), 2) AS pct_timeout_acum
FROM semanas s
JOIN base b ON b.mes_deadline = s.mes_deadline AND b.semana_inicio <= s.semana_inicio
GROUP BY 1, 2
ORDER BY 1, 2
"""

QUERY_KR22_SEM = """
SELECT
    DATE_TRUNC('week', rfh.creation_date) AS semana_inicio,
    count(distinct trx.agency_code) AS cant_agencias_unicas
FROM (
    SELECT *,
        case when starts_with(created_user, 'ext.') then substr(created_user, 5)
             else created_user end as created_user_ajustado
    FROM data.analytics.bi_requests_fact_header
    WHERE creation_yearmonth >= '2026-04'
) rfh
INNER JOIN (
    SELECT * FROM data.analytics.bi_transactional_fact_transactions
    WHERE reservation_year_month IS NOT NULL AND line_of_business = 'B2B'
) trx ON trx.transaction_code = rfh.transaction_code
WHERE rfh.creation_yearmonth IN ('2026-04','2026-05','2026-06','2026-07','2026-08','2026-09')
  AND trx.channel LIKE '%hoteldo-html%'
GROUP BY 1 ORDER BY 1
"""

QUERY_KR22_SEM_CUM = """
WITH base AS (
    SELECT
        DATE_TRUNC('month', rfh.creation_date) AS mes_inicio,
        DATE_TRUNC('week',  rfh.creation_date) AS semana_inicio,
        trx.agency_code
    FROM (
        SELECT creation_date, transaction_code
        FROM data.analytics.bi_requests_fact_header
        WHERE creation_yearmonth IN ('2026-04','2026-05','2026-06','2026-07','2026-08','2026-09')
    ) rfh
    INNER JOIN (
        SELECT transaction_code, agency_code, channel
        FROM data.analytics.bi_transactional_fact_transactions
        WHERE reservation_year_month IS NOT NULL AND line_of_business = 'B2B'
    ) trx ON trx.transaction_code = rfh.transaction_code
    WHERE trx.channel LIKE '%hoteldo-html%'
    GROUP BY 1, 2, 3
),
semanas AS (
    SELECT DISTINCT semana_inicio, mes_inicio FROM base
)
SELECT
    s.semana_inicio,
    COUNT(DISTINCT b.agency_code) AS cant_agencias_acum_mes
FROM semanas s
JOIN base b ON b.mes_inicio = s.mes_inicio AND b.semana_inicio <= s.semana_inicio
GROUP BY 1
ORDER BY 1
"""

QUERY_KR31_SEM = """
SELECT
    DATE_TRUNC('week', fh.gestion_date) AS semana_inicio,
    ROUND(SUM(CASE
        WHEN fh.country_code='BR' AND fh.parent_channel='Agencias afiliadas' AND fh.product NOT IN ('Vuelos')
            THEN (pnl.net_revenues_usd - pnl.affiliates_usd) * 0.92
        WHEN fh.country_code='MX' THEN pnl.net_revenues_usd * 0.85
        WHEN fh.country_code='CO' THEN pnl.net_revenues_usd * 0.84
        WHEN fh.country_code='CL' THEN pnl.net_revenues_usd * 0.92
        WHEN fh.country_code IN ('US','PA') THEN pnl.net_revenues_usd * 0.80
        WHEN fh.country_code='BR' AND fh.product IN ('Vuelos') THEN pnl.net_revenues_usd * 0.92
        ELSE pnl.net_revenues_usd * 0.97
    END), 2) AS net_revenue_real
FROM data.analytics.bi_sales_fact_sales_recognition fh
    LEFT JOIN data.analytics.bi_pnlop_fact_current_model pnl ON fh.product_id = pnl.product_id
    LEFT JOIN data.analytics.bi_transactional_fact_transactions t
        ON t.transaction_code = CAST(pnl.transaction_code AS VARCHAR)
    LEFT JOIN data.tmp.correccion_be be ON CAST(be.product_id AS VARCHAR) = CAST(pnl.product_id AS VARCHAR)
    LEFT JOIN data.tmp.mktg_funds d ON CAST(d.product_id AS VARCHAR) = CAST(pnl.product_id AS VARCHAR)
    LEFT JOIN data.tmp.mkt_funds_bd1 mkt ON mkt.product_id = fh.product_id
WHERE fh.gestion_date >= CAST('2026-04-01' AS DATE)
    AND fh.partition_period >= '2025-01-01'
    AND fh.lob_gestion IN ('stg__sales_b2bnohoteldo','stg_sales__b2bhoteldo')
    AND pnl.line_of_business = 'B2B'
    AND t.reservation_year_month >= CAST('2025-01-01' AS DATE)
    AND pnl.date_reservation_year_month >= '2025-01'
    AND fh.parent_channel = 'Agencias afiliadas'
GROUP BY 1 ORDER BY 1
"""

QUERY_KR31_SEM_CUM = """
WITH real_data AS (
    SELECT
        DATE_TRUNC('month', fh.gestion_date) AS mes_inicio,
        DATE_TRUNC('week',  fh.gestion_date) AS semana_inicio,
        CASE WHEN fh.partner_id IN ('AP12142','AP12961','AP12767','AP12539','AP12792',
                                     'AP12149','AP12148','AG00015606','AP13029','AP13030',
                                     'AP13091','AP13104','AG00015611') THEN 'O'
             WHEN fh.country_code IN ('MX','BR','CO','AR','EC','PE','CL','UY') THEN fh.country_code
             ELSE 'O' END AS pais,
        CASE WHEN fh.buy_type_code IN ('Bundles','Carrito') THEN 'Paquetes'
             WHEN fh.buy_type_code IN ('Actividades','Traslados') THEN 'Dest. Serv'
             ELSE fh.buy_type_code END AS producto,
        SUM(CASE
            WHEN fh.country_code='BR' AND fh.parent_channel='Agencias afiliadas' AND fh.product NOT IN ('Vuelos')
                THEN (pnl.net_revenues_usd - pnl.affiliates_usd) * 0.92
            WHEN fh.country_code='MX' THEN pnl.net_revenues_usd * 0.85
            WHEN fh.country_code='CO' THEN pnl.net_revenues_usd * 0.84
            WHEN fh.country_code='CL' THEN pnl.net_revenues_usd * 0.92
            WHEN fh.country_code IN ('US','PA') THEN pnl.net_revenues_usd * 0.80
            WHEN fh.country_code='BR' AND fh.product IN ('Vuelos') THEN pnl.net_revenues_usd * 0.92
            ELSE pnl.net_revenues_usd * 0.97 END) AS net_revenue
    FROM data.analytics.bi_sales_fact_sales_recognition fh
        LEFT JOIN data.analytics.bi_pnlop_fact_current_model pnl ON fh.product_id = pnl.product_id
        LEFT JOIN data.analytics.bi_transactional_fact_transactions t
            ON t.transaction_code = CAST(pnl.transaction_code AS VARCHAR)
        LEFT JOIN data.tmp.correccion_be be ON CAST(be.product_id AS VARCHAR) = CAST(pnl.product_id AS VARCHAR)
        LEFT JOIN data.tmp.mktg_funds d ON CAST(d.product_id AS VARCHAR) = CAST(pnl.product_id AS VARCHAR)
        LEFT JOIN data.tmp.mkt_funds_bd1 mkt ON mkt.product_id = fh.product_id
    WHERE fh.gestion_date >= CAST('2026-04-01' AS DATE)
        AND fh.partition_period >= '2025-01-01'
        AND fh.lob_gestion IN ('stg__sales_b2bnohoteldo','stg_sales__b2bhoteldo')
        AND pnl.line_of_business = 'B2B'
        AND t.reservation_year_month >= CAST('2025-01-01' AS DATE)
        AND pnl.date_reservation_year_month >= '2025-01'
        AND fh.parent_channel = 'Agencias afiliadas'
    GROUP BY 1, 2, 3, 4
),
semanas AS (SELECT DISTINCT semana_inicio, mes_inicio FROM real_data)
SELECT
    s.semana_inicio,
    ROUND(SUM(rd.net_revenue), 2) AS net_revenue_acum_mes
FROM semanas s
JOIN real_data rd ON rd.mes_inicio = s.mes_inicio AND rd.semana_inicio <= s.semana_inicio
GROUP BY 1
ORDER BY 1
"""

QUERY_KR32_SEM = """
WITH parametros AS (SELECT DATE '2026-04-01' AS fecha_inicio, DATE '2026-09-30' AS fecha_fin),
cotizaciones AS (
    SELECT DATE_TRUNC('week', CAST(created_at AS DATE)) AS semana, UPPER(agency_code) AS agency_code
    FROM data.raw.socrates_trip_quotations CROSS JOIN parametros p
    WHERE CAST(created_at AS DATE) BETWEEN p.fecha_inicio AND p.fecha_fin
      AND channel_code IN ('hoteldo-html-classic','hoteldo-html-gold','hoteldo-html-platinum','hoteldo-html-silver')
      AND agency_code IS NOT NULL AND agency_code != ''
    GROUP BY 1, 2
),
ventas AS (
    SELECT DISTINCT DATE_TRUNC('week', bi.creation_date) AS semana, UPPER(bi.agency_code) AS agency_code
    FROM data.analytics.bi_sales_fact_sales_recognition bi CROSS JOIN parametros p
    WHERE bi.creation_date BETWEEN p.fecha_inicio AND p.fecha_fin
      AND bi.transaction_status = 'Confirmado'
      AND bi.channel IN ('hoteldo-html-classic','hoteldo-html-gold','hoteldo-html-platinum','hoteldo-html-silver')
      AND bi.partition_period >= '2026-04' AND bi.agency_code IS NOT NULL
)
SELECT
    c.semana AS semana_inicio,
    COUNT(DISTINCT c.agency_code) AS agencias_cotizadoras,
    COUNT(DISTINCT CASE WHEN v.agency_code IS NOT NULL THEN c.agency_code END) AS agencias_cotizaron_y_vendieron,
    ROUND(100.0 * COUNT(DISTINCT CASE WHEN v.agency_code IS NOT NULL THEN c.agency_code END)
        / NULLIF(COUNT(DISTINCT c.agency_code), 0), 2) AS pct_activacion_comercial
FROM cotizaciones c LEFT JOIN ventas v ON c.agency_code=v.agency_code AND c.semana=v.semana
GROUP BY 1 ORDER BY 1
"""

QUERY_KR32_SEM_CUM = """
WITH parametros AS (SELECT DATE '2026-04-01' AS fecha_inicio, DATE '2026-09-30' AS fecha_fin),
cotizaciones AS (
    SELECT
        DATE_TRUNC('month', CAST(created_at AS DATE)) AS mes_inicio,
        DATE_TRUNC('week',  CAST(created_at AS DATE)) AS semana_cotiz,
        UPPER(agency_code) AS agency_code
    FROM data.raw.socrates_trip_quotations CROSS JOIN parametros p
    WHERE CAST(created_at AS DATE) BETWEEN p.fecha_inicio AND p.fecha_fin
      AND channel_code IN ('hoteldo-html-classic','hoteldo-html-gold','hoteldo-html-platinum','hoteldo-html-silver')
      AND agency_code IS NOT NULL AND agency_code != ''
    GROUP BY 1, 2, 3
),
ventas AS (
    SELECT DISTINCT
        DATE_TRUNC('month', bi.creation_date) AS mes_inicio,
        DATE_TRUNC('week',  bi.creation_date) AS semana_venta,
        UPPER(bi.agency_code) AS agency_code
    FROM data.analytics.bi_sales_fact_sales_recognition bi CROSS JOIN parametros p
    WHERE bi.creation_date BETWEEN p.fecha_inicio AND p.fecha_fin
      AND bi.transaction_status = 'Confirmado'
      AND bi.channel IN ('hoteldo-html-classic','hoteldo-html-gold','hoteldo-html-platinum','hoteldo-html-silver')
      AND bi.partition_period >= '2026-04' AND bi.agency_code IS NOT NULL
),
semanas AS (
    SELECT DISTINCT semana_cotiz AS semana_inicio, mes_inicio FROM cotizaciones
)
SELECT
    s.semana_inicio,
    COUNT(DISTINCT c.agency_code) AS agencias_cotizadoras_acum,
    COUNT(DISTINCT CASE WHEN v.agency_code IS NOT NULL THEN c.agency_code END) AS agencias_compraron_acum,
    ROUND(100.0 * COUNT(DISTINCT CASE WHEN v.agency_code IS NOT NULL THEN c.agency_code END)
        / NULLIF(COUNT(DISTINCT c.agency_code), 0), 2) AS pct_activacion_acum
FROM semanas s
JOIN cotizaciones c ON c.mes_inicio = s.mes_inicio AND c.semana_cotiz <= s.semana_inicio
LEFT JOIN ventas v
    ON v.agency_code = c.agency_code
    AND v.mes_inicio = s.mes_inicio
    AND v.semana_venta <= s.semana_inicio
GROUP BY 1
ORDER BY 1
"""

QUERIES = [
    ('kr21', QUERY_KR21),
    ('kr22', QUERY_KR22),
    ('kr31', QUERY_KR31),
    ('kr32', QUERY_KR32),
    ('kr33', QUERY_KR33),
    ('kr21_sem', QUERY_KR21_SEM),
    ('kr21_sem_cum', QUERY_KR21_SEM_CUM),
    ('kr22_sem', QUERY_KR22_SEM),
    ('kr22_sem_cum', QUERY_KR22_SEM_CUM),
    ('kr31_sem', QUERY_KR31_SEM),
    ('kr31_sem_cum', QUERY_KR31_SEM_CUM),
    ('kr32_sem', QUERY_KR32_SEM),
    ('kr32_sem_cum', QUERY_KR32_SEM_CUM),
    ('kr33_sem', QUERY_KR33_SEM),
    ('kr33_sem_cum', QUERY_KR33_SEM_CUM),
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

HTML_TEMPLATE = """<!DOCTYPE html>
<!-- v3 -->
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tablero Producto B2B - HTML · H1 FY27</title>
<style>
:root{--bg:#f4f5f7;--surface:#fff;--surface2:#f8f9fa;--border:#e8e0f0;--border2:#d5c8e8;--purple:#6D28D9;--text:#1f2328;--muted:#57606a;--radius:8px;--shadow:0 1px 4px rgba(0,0,0,.08),0 4px 16px rgba(0,0,0,.06)}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:-apple-system,'Segoe UI',sans-serif;font-size:14px;min-height:100vh}
header{background:linear-gradient(90deg,#5B21B6,#7C3AED);padding:0 28px;height:72px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:300;box-shadow:0 2px 12px rgba(91,33,182,.4)}
.logo-main{color:#fff;font-size:15px;font-weight:700}.logo-main span{color:#C4B5FD}
.logo-sub{color:rgba(196,181,253,.65);font-size:10px;font-weight:500;letter-spacing:.05em;text-transform:uppercase;margin-top:2px}
.upd{color:rgba(255,255,255,.5);font-size:11px}
.filter-bar{display:flex;gap:24px;padding:14px 28px;background:#fff;border-bottom:1px solid var(--border);align-items:center;flex-wrap:wrap;position:sticky;top:72px;z-index:200;box-shadow:0 1px 4px rgba(0,0,0,.06)}
.filter-group{display:flex;align-items:center;gap:8px}
.filter-label{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;white-space:nowrap}
.pill{padding:5px 16px;border-radius:20px;border:1.5px solid var(--border2);background:#fff;color:var(--muted);font-size:12px;font-weight:600;cursor:pointer;transition:all .15s;line-height:1.4}
.pill:hover{border-color:var(--purple);color:var(--purple)}
.pill.active{background:var(--purple);border-color:var(--purple);color:#fff}
main{padding:28px;max-width:1200px;margin:0 auto}
.sec-title{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:14px;padding-bottom:8px;border-bottom:2px solid var(--border);margin-top:28px}
.sec-title:first-child{margin-top:0}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow);overflow:auto;margin-bottom:8px}
.card-hdr{background:#5457D9;color:#fff;padding:14px 20px;font-size:15px;font-weight:700}
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:#7C7FFF;color:#fff;padding:10px 8px;text-align:center;font-weight:700;font-size:11px;white-space:nowrap;border-right:1px solid rgba(255,255,255,.15)}
th.th-kr{text-align:left;padding-left:16px;width:340px}
th.th-q{background:#5457D9;border-left:2px solid rgba(255,255,255,.25)}
td{padding:11px 8px;text-align:center;border-bottom:1px solid var(--border);border-right:1px solid var(--border)}
td.td-kr{text-align:left;padding-left:16px;font-weight:500}
td.td-q{border-left:2px solid var(--border2);font-weight:700}
tbody tr:hover{background:var(--surface2)}
tbody tr:last-child td{border-bottom:none}
.chip{display:inline-block;padding:4px 10px;border-radius:5px;font-size:12px;font-weight:700;min-width:44px;text-align:center}
.ok{background:#d4f4dd;color:#16a34a}.warn{background:#fff7cd;color:#b45309}.bad{background:#ffd8d3;color:#cf222e}.na{background:#f0f0f0;color:#999;font-size:11px;font-weight:400}
footer{text-align:center;padding:20px;font-size:11px;color:var(--muted)}
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
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
</head>
<body>
<header>
  <div>
    <div class="logo-main">Tablero Producto B2B <span>HTML</span></div>
    <div class="logo-sub">H1 FY27 · Abril — Septiembre 2026</div>
  </div>
  <div style="display:flex;align-items:center;gap:14px">
    <span class="upd">Actualizado: __UPDATED__</span>
    <button id="theme-btn" onclick="toggleTheme()" title="Modo noche/día">🌙</button>
  </div>
</header>
<div class="filter-bar">
  <div class="filter-group" id="sq-filter" style="display:none">
    <span class="filter-label">Squad</span>
    <button class="pill sqpill active" onclick="setSq('all',this)">Todos</button>
    <button class="pill sqpill" onclick="setSq('ce',this)">C&amp;E</button>
    <button class="pill sqpill" onclick="setSq('es',this)">E&amp;S</button>
  </div>
  <div class="filter-group" id="mes-filter" style="display:none">
    <span class="filter-label">Mes</span>
    <button class="pill mespill" data-mes="all" onclick="setPulsoMes('all',this)">Todos</button>
    <button class="pill mespill" data-mes="2026-04" onclick="setPulsoMes('2026-04',this)">Abr</button>
    <button class="pill mespill" data-mes="2026-05" onclick="setPulsoMes('2026-05',this)">May</button>
    <button class="pill mespill" data-mes="2026-06" onclick="setPulsoMes('2026-06',this)">Jun</button>
    <button class="pill mespill" data-mes="2026-07" onclick="setPulsoMes('2026-07',this)">Jul</button>
    <button class="pill mespill" data-mes="2026-08" onclick="setPulsoMes('2026-08',this)">Ago</button>
    <button class="pill mespill" data-mes="2026-09" onclick="setPulsoMes('2026-09',this)">Sep</button>
  </div>
  <div class="filter-group" style="margin-left:auto">
    <button class="pill tabpill active" onclick="setTab('mensual',this)">Mensual</button>
    <button class="pill tabpill" onclick="setTab('semanal',this)">Semanal</button>
    <button class="pill tabpill" onclick="setTab('progreso',this)">Progreso</button>
    <button class="pill tabpill" onclick="setTab('monitor',this)">Monitor</button>
  </div>
</div>
<main id="root"></main>
<footer>Datos del Datalake de Despegar (Trino)</footer>
<script>
var DATA = __DATA__;

var MONTHS=["2026-04","2026-05","2026-06","2026-07","2026-08","2026-09"];
var LABELS=["Abr","May","Jun","Jul","Ago","Sep"];

var KRS=[
  {id:"kr21",squad:"es",peso:7,label:"KR 2.1 - Disminuir cancelación de bookings por falta pago",targets:[22,20,18.25,16.85,15.75,15],inverted:true,
   fmtA:function(v){return v!==null?v.toFixed(2)+"%":null;},fmtT:function(v){return v+"%";},
   getActual:function(i){
     var m=MONTHS[i],rows=DATA.kr21.filter(function(r){return String(r.mes_deadline||"").substring(0,7)===m;});
     if(!rows.length)return null;
     var total=rows.reduce(function(s,r){return s+(r.reservas||0);},0);
     var timeout=rows.reduce(function(s,r){return r.status==='Time_out_client'?s+(r.reservas||0):s;},0);
     return total>0?timeout/total*100:null;
   }},
  {id:"kr22",squad:"es",peso:13,label:"KR 2.2 - Aumentar la cantidad de agencias que utilizan herramientas de gestión/postventa",targets:[4500,4500,5025,5445,5775,6000],inverted:false,
   fmtA:function(v){return v!==null?Math.round(v).toLocaleString("es-AR"):null;},fmtT:function(v){return v.toLocaleString("es-AR");},
   getActual:function(i){
     var m=MONTHS[i],row=DATA.kr22.find(function(r){return String(r.creation_yearmonth||"").substring(0,7)===m;});
     return row?row.cant_agencias_unicas:null;
   }},
  {id:"kr31",squad:"ce",peso:16,label:"KR 3.1 - Net Revenue B2B Minorista",targets:null,inverted:false,
   fmtA:function(v){return v!==null?"$"+Math.round(v).toLocaleString("es-AR"):null;},fmtT:function(v){return v!==null?"$"+Math.round(v).toLocaleString("es-AR"):"N/A";},
   getActual:function(i){
     var m=MONTHS[i],row=DATA.kr31.find(function(r){return String(r.periodo||"").substring(0,7)===m;});
     return row?row.net_rev_real:null;
   },
   getTarget:function(i){
     var m=MONTHS[i],row=DATA.kr31.find(function(r){return String(r.periodo||"").substring(0,7)===m;});
     return row?row.net_rev_target:null;
   }},
  {id:"kr32",squad:"ce",peso:7,label:"KR 3.2 - Aumentar agencias compradoras que utilizan cotizaciones",targets:[70,70,73,74,75,77],inverted:false,
   fmtA:function(v){return v!==null?v.toFixed(1)+"%":null;},fmtT:function(v){return v+"%";},
   getActual:function(i){
     var m=MONTHS[i],row=DATA.kr32.find(function(r){return String(r.mes||"").substring(0,7)===m;});
     return row?row.pct_activacion_comercial:null;
   }},
  {id:"kr33",squad:"ce",peso:7,label:"KR 3.3 - Frecuencia de compra",targets:[25,25,25,25,25,25],inverted:false,
   fmtA:function(v){return v!==null?v.toFixed(1)+"%":null;},fmtT:function(v){return v+"%";},
   getActual:function(i){
     var m=MONTHS[i];
     var ym=parseInt(m.slice(0,4)+m.slice(5,7),10);
     var row=DATA.kr33.find(function(r){return r.mes_evaluacion===ym;});
     return row?row.pct_aumento:null;
   }}
];

function krNro(label){return label.split(/ - | — /)[0].trim();}
function krDesc(label){var p=label.split(/ - | — /);return p.slice(1).join(' - ').trim();}
var SQ_TOT={};KRS.forEach(function(kr){SQ_TOT[kr.squad]=(SQ_TOT[kr.squad]||0)+kr.peso;});
function pesoGlobalPct(kr){return Math.round(kr.peso/50*100)+'%';}
function pesoSquadPct(kr){return (kr.peso/(SQ_TOT[kr.squad]||1)*100).toFixed(1)+'%';}
var activeTab='mensual', activeSq='all';

function setTab(tab,btn){
  activeTab=tab;
  document.querySelectorAll('.tabpill').forEach(function(b){b.classList.remove('active');});
  btn.classList.add('active');
  var showSq=tab==='progreso'||tab==='mensual'||tab==='semanal';
  document.getElementById('sq-filter').style.display=showSq?'flex':'none';
  document.getElementById('mes-filter').style.display=tab==='monitor'?'flex':'none';
  if(tab==='monitor'){
    document.querySelectorAll('.mespill').forEach(function(b){b.classList.toggle('active',(b.dataset.mes||'all')===activePulsoMes);});
  }
  if(window._pulsoChart){window._pulsoChart.destroy();window._pulsoChart=null;}
  render();
}
function setSq(sq,btn){
  activeSq=sq;
  document.querySelectorAll('.sqpill').forEach(function(b){b.classList.remove('active');});
  btn.classList.add('active');
  render();
}
function filteredKRS(){
  return activeSq==='ce'?KRS.filter(function(k){return k.squad==='ce';}):
         activeSq==='es'?KRS.filter(function(k){return k.squad==='es';}):KRS;
}
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

function renderMensual(){
  var idxs=[0,1,2,3,4,5];
  var krs=filteredKRS();
  var closed=nowYm();
  var html='';

  html+='<p class="sec-title">OKR Status FY27</p>';
  html+='<div style="display:flex;gap:10px;align-items:center;margin-bottom:14px;flex-wrap:wrap">';
  html+='<span style="font-size:11px;color:var(--muted);font-weight:600">Umbrales:</span>';
  html+='<span class="chip ok">&#8805; 100%&nbsp; en target</span>';
  html+='<span class="chip warn">80 – 99%&nbsp; cerca</span>';
  html+='<span class="chip bad">&lt; 80%&nbsp; lejos</span>';
  html+='<span class="chip na">N/D&nbsp; sin dato</span>';
  html+='</div>';
  html+='<div class="card"><div class="card-hdr">Tablero Producto B2B - HTML · H1 FY27</div>';
  html+='<table><thead><tr><th style="width:65px;text-align:center">Nro KR</th><th class="th-kr">KR</th><th style="width:45px;text-align:center">Peso</th>';
  idxs.forEach(function(i){html+='<th>'+LABELS[i]+'</th>';});
  html+='<th class="th-q">Q1</th><th class="th-q">Q2</th>';
  html+='</tr></thead><tbody>';
  var totalPesoM=krs.reduce(function(s,k){return s+k.peso;},0);
  var cumPM=0,pesoPM=krs.map(function(k,i){if(i===krs.length-1)return(100-cumPM).toFixed(1)+'%';var p=parseFloat((k.peso/totalPesoM*100).toFixed(1));cumPM+=p;return p.toFixed(1)+'%';});
  krs.forEach(function(kr,ki){
    var comps=MONTHS.map(function(m,i){
      var a=kr.getActual(i);
      var t=kr.targets!==null?kr.targets[i]:(kr.getTarget?kr.getTarget(i):null);
      return m<closed?compliance(a,t,kr.inverted):null;
    });
    var q1=avg([comps[0],comps[1],comps[2]]),q2=avg([comps[3],comps[4],comps[5]]);
    html+='<tr><td style="text-align:center;font-weight:700;color:#5B21B6;white-space:nowrap;padding:11px 8px">'+krNro(kr.label)+'</td><td class="td-kr">'+krDesc(kr.label)+'</td><td style="text-align:center;font-weight:600;color:var(--muted);white-space:nowrap;padding:11px 6px">'+pesoPM[ki]+'</td>';
    idxs.forEach(function(i){html+='<td>'+(MONTHS[i]<closed?chip(comps[i]):'-')+'</td>';});
    html+='<td class="td-q">'+chip(q1)+'</td><td class="td-q">'+chip(q2)+'</td>';
    html+='</tr>';
  });
  var wComps=idxs.map(function(i){
    if(MONTHS[i]>=closed)return null;
    var num=0,den=0;
    krs.forEach(function(kr){
      var a=kr.getActual(i);
      var t=kr.targets!==null?kr.targets[i]:(kr.getTarget?kr.getTarget(i):null);
      var c=effComp(compliance(a,t,kr.inverted));
      if(c!==null){num+=c*kr.peso;den+=kr.peso;}
    });
    return den>0?num/den:null;
  });
  var wQ1=avg([wComps[0],wComps[1],wComps[2]]),wQ2=avg([wComps[3],wComps[4],wComps[5]]);
  var sepStyle='border-top:2px solid var(--border2);background:var(--surface2)';
  html+='<tr style="'+sepStyle+'">';
  html+='<td colspan="2" style="text-align:left;padding-left:16px;font-weight:700;font-size:12px;color:var(--purple)">Cumplimiento Total Ponderado</td>';
  html+='<td style="text-align:center;font-weight:700;font-size:11px;color:var(--purple)">100%</td>';
  idxs.forEach(function(i){html+='<td>'+(MONTHS[i]<=closed?chip(wComps[i]):'-')+'</td>';});
  html+='<td class="td-q">'+chip(wQ1)+'</td><td class="td-q">'+chip(wQ2)+'</td>';
  html+='</tr>';
  html+='</tbody></table></div>';

  html+='<p class="sec-title">Targets</p><div class="card"><table><thead><tr><th style="width:65px;text-align:center">Nro KR</th><th class="th-kr">KR</th>';
  idxs.forEach(function(i){html+='<th>'+LABELS[i]+'</th>';});
  html+='</tr></thead><tbody>';
  krs.forEach(function(kr){
    html+='<tr><td style="text-align:center;font-weight:700;color:#5B21B6;white-space:nowrap;padding:11px 8px">'+krNro(kr.label)+'</td><td class="td-kr">'+krDesc(kr.label)+'</td>';
    idxs.forEach(function(i){
      var t=kr.targets!==null?kr.targets[i]:(kr.getTarget?kr.getTarget(i):null);
      html+='<td>'+(t!==null?kr.fmtT(t):'<span class="chip na">N/A</span>')+'</td>';
    });
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
      html+='<td>'+(MONTHS[i]<=closed?(a!==null?kr.fmtA(a):'<span class="chip na">N/D</span>'):'-')+'</td>';
    });
    html+='</tr>';
  });
  html+='</tbody></table></div>';

  return html;
}

function renderSemanal(){
  var weeks=(DATA.kr22_sem||[]).map(function(r){return r.semana_inicio;})
    .filter(function(w){return w&&semMes(w)>='2026-04'&&semMes(w)<nowYm();})
    .sort()
    .filter(function(w,i,a){return a.indexOf(w)===i;});
  var lastWm=weeks.length?semMes(weeks[weeks.length-1]):null;
  var todayLbl=lastWm?(LABELS[MONTHS.indexOf(lastWm)]||lastWm):(LABELS[MONTHS.indexOf(nowYm())]||nowYm());

  function mIdx(ym){return MONTHS.indexOf(ym);}
  function upTo(data,w){return data.filter(function(r){return r.semana_inicio&&semMes(r.semana_inicio)===semMes(w)&&r.semana_inicio<=w;});}

  function acum21(w){
    var wm=semMes(w);
    var r=(DATA.kr21_sem_cum||[]).find(function(x){
      return x.semana_inicio===w&&String(x.mes_deadline||'').substring(0,7)===wm;
    });
    if(!r||!r.total_reservas_acum)return null;
    var mi=mIdx(wm);
    return{v:r.pct_timeout_acum.toFixed(1)+'%',comp:compliance(r.pct_timeout_acum,KRS[0].targets[mi<0?0:mi],true)};
  }
  function acum22(w){
    var r=(DATA.kr22_sem_cum||[]).find(function(x){return x.semana_inicio===w;});
    var mi=mIdx(semMes(w));
    if(!r||r.cant_agencias_acum_mes===null||mi<0)return null;
    var n=r.cant_agencias_acum_mes;
    return{v:Math.round(n).toLocaleString('es-AR'),comp:compliance(n,KRS[1].targets[mi],false)};
  }
  function acum31(w){
    var r=(DATA.kr31_sem_cum||[]).find(function(x){return x.semana_inicio===w;});
    var mr=DATA.kr31.find(function(x){return String(x.periodo||'').substring(0,7)===semMes(w);});
    if(!r||r.net_revenue_acum_mes===null||!mr||!mr.net_rev_target)return null;
    var tot=r.net_revenue_acum_mes;
    return{v:'$'+(tot>=1e6?(tot/1e6).toFixed(1)+'M':(tot/1e3).toFixed(0)+'K'),comp:compliance(tot,mr.net_rev_target,false)};
  }
  function acum32(w){
    var r=(DATA.kr32_sem_cum||[]).find(function(x){return x.semana_inicio===w;});
    var mi=mIdx(semMes(w));
    if(!r||r.pct_activacion_acum===null||mi<0)return null;
    return{v:r.pct_activacion_acum.toFixed(1)+'%',comp:compliance(r.pct_activacion_acum,KRS[3].targets[mi],false)};
  }
  function acum33(w){
    var r=(DATA.kr33_sem_cum||[]).find(function(x){return x.semana_inicio===w;});
    if(!r||r.pct_aumento_acum===null)return null;
    return{v:r.pct_aumento_acum.toFixed(1)+'%',comp:compliance(r.pct_aumento_acum,25,false)};
  }

  function sem21(w){
    var wm=semMes(w);
    var wi=weeks.indexOf(w);
    var cur=(DATA.kr21_sem_cum||[]).find(function(x){return x.semana_inicio===w&&String(x.mes_deadline||'').substring(0,7)===wm;});
    if(!cur||!cur.total_reservas_acum)return null;
    var prv=wi>0&&semMes(weeks[wi-1])===wm?(DATA.kr21_sem_cum||[]).find(function(x){return x.semana_inicio===weeks[wi-1]&&String(x.mes_deadline||'').substring(0,7)===wm;}):null;
    var tot=cur.total_reservas_acum-(prv?prv.total_reservas_acum:0);
    var tou=cur.timeouts_acum-(prv?prv.timeouts_acum:0);
    if(!tot)return null;
    return{v:(tou/tot*100).toFixed(1)+'%'};
  }
  function sem22(w){
    var r=(DATA.kr22_sem||[]).find(function(x){return x.semana_inicio===w;});
    if(!r||r.cant_agencias_unicas===null)return null;
    return{v:Math.round(r.cant_agencias_unicas).toLocaleString('es-AR')};
  }
  function sem31(w){
    var r=(DATA.kr31_sem||[]).find(function(x){return x.semana_inicio===w;});
    if(!r||r.net_revenue_real===null)return null;
    var v=r.net_revenue_real;
    return{v:'$'+(v>=1e6?(v/1e6).toFixed(1)+'M':(v/1e3).toFixed(0)+'K')};
  }
  function sem32(w){
    var r=(DATA.kr32_sem||[]).find(function(x){return x.semana_inicio===w;});
    if(!r||r.pct_activacion_comercial===null)return null;
    return{v:r.pct_activacion_comercial.toFixed(1)+'%'};
  }
  function sem33(w){
    var r=(DATA.kr33_sem||[]).find(function(x){return x.semana_inicio===w;});
    if(!r||r.pct_aumento===null)return null;
    return{v:r.pct_aumento.toFixed(1)+'%'};
  }

  var SEM_KRS=[
    {label:KRS[0].label,squad:'es',peso:7,fn:acum21,semFn:sem21,
     tgtFn:function(w){var mi=mIdx(semMes(w));return mi>=0?KRS[0].targets[mi]+'%':null;}},
    {label:KRS[1].label,squad:'es',peso:13,fn:acum22,semFn:sem22,
     tgtFn:function(w){var mi=mIdx(semMes(w));return mi>=0?KRS[1].targets[mi].toLocaleString('es-AR')+' ag.':null;}},
    {label:KRS[2].label,squad:'ce',peso:16,fn:acum31,semFn:sem31,
     tgtFn:function(w){var mr=DATA.kr31.find(function(x){return String(x.periodo||'').substring(0,7)===semMes(w);});return mr&&mr.net_rev_target?'$'+(mr.net_rev_target>=1e6?(mr.net_rev_target/1e6).toFixed(1)+'M':(mr.net_rev_target/1e3).toFixed(0)+'K'):null;}},
    {label:KRS[3].label,squad:'ce',peso:7,fn:acum32,semFn:sem32,
     tgtFn:function(w){var mi=mIdx(semMes(w));return mi>=0?KRS[3].targets[mi]+'%':null;}},
    {label:KRS[4].label,squad:'ce',peso:7,fn:acum33,semFn:sem33,
     tgtFn:function(){return'25%';}},
  ];
  var filtSemKRS=activeSq==='all'?SEM_KRS:SEM_KRS.filter(function(k){return k.squad===activeSq;});

  var html='';
  html+='<p class="sec-title">Seguimiento Semanal — '+todayLbl+' 2026</p>';
  html+='<div style="display:flex;gap:10px;align-items:center;margin-bottom:14px;flex-wrap:wrap">';
  html+='<span style="font-size:11px;color:var(--muted);font-weight:600">Umbrales:</span>';
  html+='<span class="chip ok">&#8805; 100%&nbsp; en target</span>';
  html+='<span class="chip warn">80 – 99%&nbsp; cerca</span>';
  html+='<span class="chip bad">&lt; 80%&nbsp; lejos</span>';
  html+='<span class="chip na">N/D&nbsp; sin dato</span>';
  html+='<span style="font-size:11px;color:var(--muted);margin-left:4px">· Acumulado del mes hasta cada semana vs target mensual</span>';
  html+='</div>';

  html+='<div class="card"><div class="card-hdr">Progreso semanal — '+todayLbl+' 2026</div>';
  var stHdr='position:sticky;z-index:3;background:#7C7FFF';
  var stCell='position:sticky;z-index:1;background:var(--surface)';
  var shadow='box-shadow:3px 0 6px -2px rgba(0,0,0,.15)';
  html+='<div style="overflow-x:auto"><table style="white-space:nowrap"><thead><tr>';
  html+='<th style="width:65px;text-align:center;left:0;border-right:none;'+stHdr+'">Nro KR</th>';
  html+='<th style="width:340px;min-width:340px;white-space:normal;text-align:left;padding-left:16px;left:65px;border-right:none;'+stHdr+'">KR</th>';
  html+='<th style="width:45px;text-align:center;left:405px;border-right:2px solid rgba(255,255,255,.25);'+stHdr+';'+shadow+'">Peso</th>';
  weeks.forEach(function(w){html+='<th>'+semLabel(w)+'</th>';});
  html+='</tr></thead><tbody>';
  var totalPesoS=filtSemKRS.reduce(function(s,k){return s+k.peso;},0);
  var cumPS=0,pesoPS=filtSemKRS.map(function(k,i){if(i===filtSemKRS.length-1)return(100-cumPS).toFixed(1)+'%';var p=parseFloat((k.peso/totalPesoS*100).toFixed(1));cumPS+=p;return p.toFixed(1)+'%';});
  filtSemKRS.forEach(function(kr,ki){
    html+='<tr>';
    html+='<td style="text-align:center;font-weight:700;color:#5B21B6;white-space:nowrap;padding:11px 8px;left:0;border-right:none;'+stCell+'">'+krNro(kr.label)+'</td>';
    html+='<td style="width:340px;min-width:340px;white-space:normal;text-align:left;padding-left:16px;font-weight:500;left:65px;border-right:none;'+stCell+'">'+krDesc(kr.label)+'</td>';
    html+='<td style="text-align:center;font-weight:600;color:var(--muted);white-space:nowrap;padding:11px 6px;left:405px;border-right:2px solid var(--border);'+stCell+';'+shadow+'">'+pesoPS[ki]+'</td>';
    weeks.forEach(function(w){
      var d=kr.fn(w);
      var cls,txt;
      if(!d||d.comp===null){cls='na';txt='N/D';}
      else{cls=d.comp>=100?'ok':d.comp>=80?'warn':'bad';txt=Math.round(d.comp)+'%';}
      html+='<td><span class="chip '+cls+'">'+txt+'</span></td>';
    });
    html+='</tr>';
  });
  html+='</tbody></table></div></div>';

  html+='<p class="sec-title" style="margin-top:24px">Detalle por KR — '+todayLbl+' 2026</p>';
  var st2Hdr='position:sticky;z-index:3;background:#7C7FFF';
  var st2='position:sticky;left:0;z-index:1;min-width:405px;'+shadow;
  html+='<div class="card" style="overflow-x:auto"><table style="white-space:nowrap;border-collapse:collapse"><thead>';
  html+='<tr>';
  html+='<th style="width:65px;text-align:center;left:0;border-right:none;'+st2Hdr+'">Nro KR</th>';
  html+='<th style="width:340px;min-width:340px;white-space:normal;text-align:left;padding-left:16px;left:65px;border-right:2px solid rgba(255,255,255,.25);'+st2Hdr+';'+shadow+'">KR</th>';
  weeks.forEach(function(w){html+='<th style="min-width:90px">'+semLabel(w)+'</th>';});
  html+='</tr></thead><tbody>';

  filtSemKRS.forEach(function(kr,ki){
    var isLast=ki===filtSemKRS.length-1;
    var hdrBg='background:linear-gradient(90deg,#5B21B6,#7C3AED)';
    html+='<tr>';
    html+='<td style="'+hdrBg+';color:#fff;font-weight:700;font-size:11px;padding:9px 8px;text-align:center;white-space:nowrap;border-right:none;position:sticky;left:0;z-index:2;width:65px">'+krNro(kr.label)+'</td>';
    html+='<td style="'+hdrBg+';color:#fff;font-weight:700;font-size:12px;padding:9px 16px;letter-spacing:.02em;white-space:normal;border-right:none;position:sticky;left:65px;z-index:2;width:340px;min-width:340px;'+shadow+'">'+krDesc(kr.label)+'</td>';
    html+='<td colspan="'+weeks.length+'" style="'+hdrBg+';padding:0;border:none"></td>';
    html+='</tr>';
    html+='<tr style="background:var(--surface)">';
    html+='<td colspan="2" style="font-size:11px;padding:7px 8px 7px 20px;color:var(--muted);font-weight:600;border-right:3px solid var(--border2);white-space:nowrap;background:var(--surface);'+st2+'">Semana</td>';
    weeks.forEach(function(w){
      var d=kr.semFn(w);
      if(!d){html+='<td style="text-align:center;padding:7px 8px;font-size:13px"><span class="chip na">N/D</span></td>';return;}
      html+='<td style="text-align:center;padding:7px 8px;font-size:13px;color:var(--text)">'+d.v+'</td>';
    });
    html+='</tr>';
    html+='<tr style="background:var(--surface2)">';
    html+='<td colspan="2" style="font-size:11px;padding:7px 8px 7px 20px;color:var(--purple);font-weight:700;border-right:3px solid #C4B5FD;white-space:nowrap;background:var(--surface2);'+st2+'">Acumulado</td>';
    weeks.forEach(function(w){
      var d=kr.fn(w);
      if(!d){html+='<td style="text-align:center;padding:7px 8px;font-size:13px"><span class="chip na">N/D</span></td>';return;}
      html+='<td style="text-align:center;padding:7px 8px;font-size:14px;font-weight:700;color:var(--text)">'+d.v+'</td>';
    });
    html+='</tr>';
    var sepBot=isLast?'border-bottom:none':'border-bottom:2px solid var(--border2)';
    html+='<tr style="background:var(--surface2)">';
    html+='<td colspan="2" style="font-size:11px;padding:5px 8px 5px 20px;color:var(--muted);font-weight:500;'+sepBot+';white-space:nowrap;background:var(--surface2);'+st2+'">Target mensual</td>';
    weeks.forEach(function(w){
      html+='<td style="text-align:center;font-size:11px;padding:5px 8px;color:var(--muted);'+sepBot+'">'+(kr.tgtFn(w)||'—')+'</td>';
    });
    html+='</tr>';
  });

  html+='</tbody></table></div>';
  return html;
}

function renderProgreso(){
  var krs=filteredKRS();
  var closed=nowYm();
  var latestM=MONTHS.filter(function(m){return m<=closed;}).pop()||MONTHS[0];
  var latestI=MONTHS.indexOf(latestM);
  var html='';

  html+='<p class="sec-title">Estado Actual — '+LABELS[latestI]+' 2026</p>';
  html+='<div class="card" style="margin-bottom:24px">';
  html+='<table><thead><tr><th style="width:65px;text-align:center">Nro KR</th><th class="th-kr" style="width:380px">KR</th><th style="width:45px;text-align:center">Peso</th><th>Actual</th><th>Target</th><th>Cumplimiento</th><th>Delta vs Target</th></tr></thead><tbody>';
  var totalPesoP=krs.reduce(function(s,k){return s+k.peso;},0);
  var cumPP=0,pesoPP=krs.map(function(k,i){if(i===krs.length-1)return(100-cumPP).toFixed(1)+'%';var p=parseFloat((k.peso/totalPesoP*100).toFixed(1));cumPP+=p;return p.toFixed(1)+'%';});
  krs.forEach(function(kr,ki){
    var a=kr.getActual(latestI);
    var t=kr.targets!==null?kr.targets[latestI]:(kr.getTarget?kr.getTarget(latestI):null);
    var comp=compliance(a,t,kr.inverted);
    var delta='—',deltaColor='var(--muted)';
    if(a!==null&&t!==null){
      var diff=a-t;
      var fmtSample=kr.fmtA(1)||'';
      if(fmtSample.indexOf('%')>=0){
        delta=(diff>=0?'+':'')+diff.toFixed(2)+'pp';
      } else if(fmtSample.indexOf('$')>=0){
        delta=(diff>=0?'+':'-')+'$'+Math.round(Math.abs(diff)).toLocaleString('es-AR');
      } else {
        delta=(diff>=0?'+':'')+Math.round(diff).toLocaleString('es-AR');
      }
      var isGood=kr.inverted?(a<=t):(a>=t);
      deltaColor=isGood?'#16a34a':'#cf222e';
    }
    html+='<tr>';
    html+='<td style="text-align:center;font-weight:700;color:#5B21B6;white-space:nowrap;padding:11px 8px">'+krNro(kr.label)+'</td><td class="td-kr">'+krDesc(kr.label)+'</td><td style="text-align:center;font-weight:600;color:var(--muted);white-space:nowrap;padding:11px 6px">'+pesoPP[ki]+'</td>';
    html+='<td style="font-weight:700">'+(a!==null?kr.fmtA(a):'<span class="chip na">N/D</span>')+'</td>';
    html+='<td>'+(t!==null?kr.fmtT(t):'<span class="chip na">N/A</span>')+'</td>';
    html+='<td>'+chip(comp)+'</td>';
    html+='<td style="font-weight:700;color:'+deltaColor+'">'+delta+'</td>';
    html+='</tr>';
  });
  html+='</tbody></table></div>';

  html+='<p class="sec-title">Progreso al Target</p>';
  krs.forEach(function(kr){
    var a=kr.getActual(latestI);
    var t=kr.targets!==null?kr.targets[latestI]:(kr.getTarget?kr.getTarget(latestI):null);
    var comp=compliance(a,t,kr.inverted);
    var barPct=comp!==null?Math.min(comp,100):0;
    var barColor=comp!==null?(comp>=100?'#22c55e':comp>=80?'#eab308':'#ef4444'):'#ddd';
    html+='<div class="card" style="padding:16px 20px;margin-bottom:8px">';
    html+='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">';
    html+='<span style="font-weight:700;color:#5B21B6;font-size:12px;margin-right:8px">'+krNro(kr.label)+'</span><span style="font-weight:600;font-size:13px">'+krDesc(kr.label)+'</span>';
    html+='<span style="font-size:13px">'+(a!==null?kr.fmtA(a)+' / '+(t!==null?kr.fmtT(t):'?'):'N/D')+'&nbsp;&nbsp;'+chip(comp)+'</span>';
    html+='</div>';
    html+='<div style="background:#f0f0f0;border-radius:6px;height:10px">';
    html+='<div style="background:'+barColor+';width:'+barPct+'%;height:10px;border-radius:6px;transition:width .4s"></div>';
    html+='</div>';
    html+='</div>';
  });

  return html;
}

function render(){
  if(window._pulsoChart){window._pulsoChart.destroy();window._pulsoChart=null;}
  if(activeTab==='progreso'){document.getElementById('root').innerHTML=renderProgreso();}
  else if(activeTab==='monitor'){document.getElementById('root').innerHTML=renderPulso();setTimeout(buildPulsoChart,0);}
  else if(activeTab==='semanal'){document.getElementById('root').innerHTML=renderSemanal();}
  else{document.getElementById('root').innerHTML=renderMensual();}
}

function toggleTheme(){
  var dark=document.body.classList.toggle('dark');
  document.getElementById('theme-btn').textContent=dark?'☀':'🌙';
  try{localStorage.setItem('okrs_theme',dark?'dark':'light');}catch(e){}
}
(function(){try{if(localStorage.getItem('okrs_theme')==='dark'){document.body.classList.add('dark');document.getElementById('theme-btn').textContent='☀';}}catch(e){}})();

// ── Tab Monitor ────────────────────────────────────────────────────────────

var activePulsoKR='kr21',activePulsoMes=nowYm();
var MON_SHORT=['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];

var PULSO_KRS=[
  {id:'kr21',label:'2.1 · Cancelaciones'},
  {id:'kr22',label:'2.2 · Agencias'},
  {id:'kr31',label:'3.1 · Net Revenue'},
  {id:'kr32',label:'3.2 · Cotizaciones'},
  {id:'kr33',label:'3.3 · Frecuencia'},
];

var PULSO_DESCS={
  kr21:'<b>Semanal</b> — el % de cancelaciones varia semana a semana y tiene targets mensuales escalonados. El monitoreo semanal es esencial para detectar picos antes de que el mes cierre mal.',
  kr22:'<b>Semanal + acumulado</b> — barras: agencias unicas esa semana; linea verde: acumulado de agencias unicas en el mes (sin repetir); linea roja: target mensual. La linea verde es la metrica oficial.',
  kr31:'<b>Semanal + acumulado</b> — barras: revenue semanal; linea violeta: acumulado del mes; linea roja: forecast mensual. Util para detectar semanas debiles y proyectar el cierre del mes.',
  kr32:'<b>Semanal</b> — % de agencias que cotizaron Y compraron sobre el total que cotizo esa semana. La brecha con el target (70-77%) es significativa; el monitoreo semanal permite intervenir a tiempo.',
  kr33:'<b>Referencia mensual</b> — este KR compara el mes N vs el mes N+1 y no tiene granularidad semanal. Se muestra el resultado de cada mes cerrado. Verde = supero el target del 35%.',
};

function setPulsoKR(kr){
  activePulsoKR=kr;
  render();
}
function setPulsoMes(mes,btn){
  activePulsoMes=mes;
  document.querySelectorAll('.mespill').forEach(function(b){b.classList.toggle('active',(b.dataset.mes||'all')===mes);});
  render();
}

function semLabel(s){if(!s)return'';var p=String(s).split('-');return p[2]+'-'+MON_SHORT[parseInt(p[1],10)-1];}
function semMes(s){return String(s||'').substring(0,7);}
function semTarget(s,tgts){var mi=MONTHS.indexOf(semMes(s));return(mi>=0&&tgts)?tgts[mi]:null;}
function semRows(rows,field){
  field=field||'semana_inicio';
  if(activePulsoMes==='all')return rows;
  return rows.filter(function(r){return semMes(r[field])===activePulsoMes;});
}

function _statCards(cards){
  var sc='flex:1;min-width:140px;padding:16px 20px;background:#fff;border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow)';
  var sl='font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px';
  var sv='font-size:26px;font-weight:800;line-height:1.1;margin-bottom:4px';
  var ss='font-size:11px;color:var(--muted)';
  var html='<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:14px">';
  cards.forEach(function(c){
    html+='<div style="'+sc+'"><div style="'+sl+'">'+c.lbl+'</div>'
      +'<div style="'+sv+';color:'+(c.col||'#1F2328')+'">'+c.val+'</div>'
      +'<div style="'+ss+'">'+c.sub+'</div></div>';
  });
  return html+'</div>';
}

function _curMesInfo(lastSem){
  var cm=activePulsoMes!=='all'?activePulsoMes:semMes(lastSem);
  var mi=MONTHS.indexOf(cm);
  return{mes:cm,idx:mi,lab:mi>=0?LABELS[mi]:'mes'};
}

function renderKR21Stats(){
  var rows=semRows(DATA.kr21_sem);
  var tA=[22,20,18.25,16.85,15.75,15];
  var valid=rows.filter(function(r){return r.pct_timeout_client!==null;});
  if(!valid.length)return'';
  var picoVal=valid.reduce(function(mx,r){return r.pct_timeout_client>mx?r.pct_timeout_client:mx;},-Infinity);
  var picoRow=valid.find(function(r){return r.pct_timeout_client===picoVal;});
  var lastRow=valid[valid.length-1];
  var lastVal=lastRow.pct_timeout_client;
  var cm=_curMesInfo(lastRow.semana_inicio);
  var curTgt=cm.idx>=0?tA[cm.idx]:null;
  var brecha=(lastVal!==null&&curTgt!==null)?lastVal-curTgt:null;
  var bStr=brecha!==null?((brecha>=0?'+':'')+brecha.toFixed(1)+'pp'):'--';
  var bCol=brecha!==null&&brecha>0?'#CF222E':'#16a34a';
  return _statCards([
    {lbl:'Pico de cancelaciones',val:picoVal.toFixed(1)+'%',sub:'semana '+semLabel(picoRow.semana_inicio),col:'#CF222E'},
    {lbl:'Ultimo dato real',val:lastVal.toFixed(1)+'%',sub:'semana '+semLabel(lastRow.semana_inicio)},
    {lbl:'Target '+cm.lab,val:curTgt!==null?curTgt+'%':'N/A',sub:'meta mensual',col:'#5B21B6'},
    {lbl:'Brecha',val:bStr,sub:'sobre target '+cm.lab,col:bCol},
  ]);
}

function renderKR22Stats(){
  var rows=semRows(DATA.kr22_sem);
  var tA=[4500,4500,5025,5445,5775,6000];
  var valid=rows.filter(function(r){return r.cant_agencias_unicas!==null;});
  if(!valid.length)return'';
  var maxRow=valid.reduce(function(mx,r){return r.cant_agencias_unicas>mx.cant_agencias_unicas?r:mx;},valid[0]);
  var lastRow=valid[valid.length-1];
  var cm=_curMesInfo(lastRow.semana_inicio);
  var curTgt=cm.idx>=0?tA[cm.idx]:null;
  var semsEnMes=DATA.kr22_sem.filter(function(r){return semMes(r.semana_inicio)===cm.mes;}).length;
  var fmt=function(v){return Math.round(v).toLocaleString('es-AR');};
  return _statCards([
    {lbl:'Max semana',val:fmt(maxRow.cant_agencias_unicas),sub:'semana '+semLabel(maxRow.semana_inicio),col:'#2563EB'},
    {lbl:'Target '+cm.lab,val:curTgt!==null?curTgt.toLocaleString('es-AR'):'N/A',sub:'agencias unicas',col:'#5B21B6'},
    {lbl:'Semanas en '+cm.lab,val:semsEnMes+' de 4',sub:'datos completos'},
    {lbl:'Ultimo dato',val:fmt(lastRow.cant_agencias_unicas),sub:'sem '+semLabel(lastRow.semana_inicio)},
  ]);
}

function renderKR31Stats(){
  var rows=semRows(DATA.kr31_sem);
  var valid=rows.filter(function(r){return r.net_revenue_real!==null;});
  if(!valid.length)return'';
  var lastRow=valid[valid.length-1];
  var cm=_curMesInfo(lastRow.semana_inicio);
  var cumRows=semRows(DATA.kr31_sem_cum||[]);
  var lastCum=cumRows.length?cumRows[cumRows.length-1]:null;
  var total=lastCum?lastCum.net_revenue_acum_mes:null;
  var bestRow=valid.reduce(function(mx,r){return r.net_revenue_real>mx.net_revenue_real?r:mx;},valid[0]);
  var worstRow=valid.reduce(function(mn,r){return r.net_revenue_real<mn.net_revenue_real?r:mn;},valid[0]);
  var completos=valid.filter(function(r,i){return i<valid.length-1;});
  var prom=completos.length?completos.reduce(function(s,r){return s+(r.net_revenue_real||0);},0)/completos.length:0;
  var fmtM=function(v){return v===null?'N/D':'$'+(v>=1000000?(v/1000000).toFixed(1)+'M':(v/1000).toFixed(0)+'K');};
  return _statCards([
    {lbl:'Revenue acumulado',val:fmtM(total),sub:cm.lab+' hasta sem '+semLabel(lastRow.semana_inicio),col:'#2563EB'},
    {lbl:'Mejor semana',val:fmtM(bestRow.net_revenue_real),sub:semLabel(bestRow.semana_inicio),col:'#16a34a'},
    {lbl:'Semana mas baja',val:fmtM(worstRow.net_revenue_real),sub:semLabel(worstRow.semana_inicio),col:'#CF222E'},
    {lbl:'Promedio semanal',val:fmtM(prom),sub:'semanas completas',col:'#5B21B6'},
  ]);
}

function renderKR32Stats(){
  var rows=semRows(DATA.kr32_sem);
  var tA=[70,70,73,74,75,77];
  var valid=rows.filter(function(r){return r.pct_activacion_comercial!==null;});
  if(!valid.length)return'';
  var vals=valid.map(function(r){return r.pct_activacion_comercial;});
  var minV=Math.min.apply(null,vals),maxV=Math.max.apply(null,vals);
  var bestRow=valid.find(function(r){return r.pct_activacion_comercial===maxV;});
  var cm=_curMesInfo(valid[valid.length-1].semana_inicio);
  var refTgt=70;
  var prom=vals.reduce(function(s,v){return s+v;},0)/vals.length;
  var brecha=prom-refTgt;
  return _statCards([
    {lbl:'Rango observado',val:Math.round(minV)+'–'+Math.round(maxV)+'%',sub:'sem completas'},
    {lbl:'Target mensual',val:'70%+',sub:'abr–may: 70%',col:'#CF222E'},
    {lbl:'Mejor semana',val:maxV.toFixed(1)+'%',sub:semLabel(bestRow.semana_inicio),col:'#16a34a'},
    {lbl:'Brecha vs target',val:(brecha>=0?'+':'')+brecha.toFixed(0)+'pp',sub:'promedio vs 70%',col:brecha>=0?'#16a34a':'#CF222E'},
  ]);
}

function renderKR33Stats(){
  var rows=DATA.kr33;
  if(!rows||!rows.length)return'';
  var vals=rows.map(function(r){return r.pct_aumento;});
  var bestIdx=vals.indexOf(Math.max.apply(null,vals));
  var lastRow=rows[rows.length-1];
  var lastVal=lastRow.pct_aumento;
  function kr33Label(r){
    var m=String(r.mes_evaluacion||'');
    if(m.length===6){
      var ym=m.substring(0,4)+'-'+m.substring(4,6);
      var mi=MONTHS.indexOf(ym);
      var prev=mi>0?LABELS[mi-1]:LABELS[mi];
      return prev+(mi>=0?'→'+LABELS[mi]:'');
    }
    return m;
  }
  var curMI=MONTHS.indexOf(nowYm());
  var hasCurrent=rows.some(function(r){
    var m=String(r.mes_evaluacion||'');
    if(m.length===6){var ym=m.substring(0,4)+'-'+m.substring(4,6);return ym===nowYm();}
    return false;
  });
  return _statCards([
    {lbl:'Target fijo',val:'35%',sub:'todos los meses',col:'#5B21B6'},
    {lbl:'Mejor mes',val:Math.max.apply(null,vals).toFixed(1)+'%',sub:kr33Label(rows[bestIdx]),col:'#16a34a'},
    {lbl:'Ultimo cerrado',val:lastVal.toFixed(1)+'%',sub:kr33Label(lastRow),col:lastVal>=35?'#16a34a':'#CF222E'},
    {lbl:'Mes en curso',val:hasCurrent?vals[vals.length-1].toFixed(1)+'%':'0%',sub:hasCurrent?'datos parciales':'sin datos aun',col:'#6B7280'},
  ]);
}

function buildPulsoChart(){
  if(window._pulsoChart){window._pulsoChart.destroy();window._pulsoChart=null;}
  var canvas=document.getElementById('pulso-canvas');
  if(!canvas||typeof Chart==='undefined')return;
  var G='rgba(22,163,74,.85)',R='rgba(207,34,46,.85)',BL='#2563EB',GR='#16a34a';
  var base={responsive:true,plugins:{legend:{position:'top'},tooltip:{mode:'index',intersect:false}}};

  if(activePulsoKR==='kr21'){
    var rows=semRows(DATA.kr21_sem);
    var tA=[22,20,18.25,16.85,15.75,15];
    var labs=rows.map(function(r){return semLabel(r.semana_inicio);});
    var vals=rows.map(function(r){return r.pct_timeout_client;});
    var tgt=rows.map(function(r){return semTarget(r.semana_inicio,tA);});
    window._pulsoChart=new Chart(canvas,{type:'line',data:{labels:labs,datasets:[
      {label:'% timeout real',data:vals,borderColor:BL,backgroundColor:'rgba(37,99,235,.12)',borderWidth:2,pointRadius:3,fill:true,tension:0.3,order:2},
      {label:'target mensual',data:tgt,borderColor:'#CF222E',borderWidth:1.5,borderDash:[6,3],pointRadius:0,fill:false,tension:0,order:1}
    ]},options:{responsive:true,plugins:{legend:{position:'top'},tooltip:{mode:'index',intersect:false},title:{display:true,text:'% cancelaciones por falta de pago — semana a semana'}},scales:{y:{ticks:{callback:function(v){return v+'%';}}}}}}); return;
  }

  if(activePulsoKR==='kr22'){
    var rows=semRows(DATA.kr22_sem);
    var tA=[4500,4500,5025,5445,5775,6000];
    var labs=rows.map(function(r){return semLabel(r.semana_inicio);});
    var vals=rows.map(function(r){return r.cant_agencias_unicas;});
    var tgt=rows.map(function(r){return semTarget(r.semana_inicio,tA);});
    var cum=rows.map(function(r){var c=(DATA.kr22_sem_cum||[]).find(function(x){return x.semana_inicio===r.semana_inicio;});return c?c.cant_agencias_acum_mes:null;});
    window._pulsoChart=new Chart(canvas,{type:'bar',data:{labels:labs,datasets:[
      {label:'agencias unicas/semana',data:vals,backgroundColor:'rgba(37,99,235,.75)',borderRadius:4,order:3},
      {label:'acumulado mensual',data:cum,type:'line',borderColor:GR,backgroundColor:'rgba(22,163,74,.08)',borderWidth:2.5,pointRadius:3,fill:false,tension:0.4,order:2},
      {label:'target mensual',data:tgt,type:'line',borderColor:'#CF222E',borderWidth:1.5,borderDash:[6,3],pointRadius:0,fill:false,tension:0,order:1}
    ]},options:Object.assign({},base,{plugins:Object.assign({},base.plugins,{title:{display:true,text:'Agencias unicas semanales + acumulado mensual + target'}}),scales:{y:{beginAtZero:true}}})}); return;
  }

  if(activePulsoKR==='kr31'){
    var rows=activePulsoMes==='all'?DATA.kr31_sem:semRows(DATA.kr31_sem);
    var labs=rows.map(function(r){return semLabel(r.semana_inicio);});
    var wV=rows.map(function(r){return r.net_revenue_real;});
    var cum=rows.map(function(r){var c=(DATA.kr31_sem_cum||[]).find(function(x){return x.semana_inicio===r.semana_inicio;});return c?c.net_revenue_acum_mes:null;});
    var tgt=rows.map(function(r){var d=DATA.kr31.find(function(x){return semMes(x.periodo)===semMes(r.semana_inicio);});return d?d.net_rev_target:null;});
    window._pulsoChart=new Chart(canvas,{type:'bar',data:{labels:labs,datasets:[
      {label:'revenue semanal',data:wV,backgroundColor:'rgba(37,99,235,.75)',borderRadius:4,yAxisID:'y',order:3},
      {label:'acumulado mensual',data:cum,type:'line',borderColor:GR,backgroundColor:'rgba(22,163,74,.08)',borderWidth:2.5,pointRadius:3,fill:true,tension:0.4,yAxisID:'y2',order:2},
      {label:'forecast mensual',data:tgt,type:'line',borderColor:'#CF222E',borderWidth:1.5,borderDash:[6,3],pointRadius:0,fill:false,tension:0,yAxisID:'y2',order:1}
    ]},options:Object.assign({},base,{plugins:Object.assign({},base.plugins,{title:{display:true,text:'Net revenue semanal y acumulado mensual'}}),scales:{y:{position:'left',ticks:{color:'#2563EB',callback:function(v){return'$'+Math.round(v/1000)+'K';}}},y2:{position:'right',grid:{drawOnChartArea:false},ticks:{color:GR,callback:function(v){return'$'+(v/1000000).toFixed(1)+'M';}}}}})}); return;
  }

  if(activePulsoKR==='kr32'){
    var rows=semRows(DATA.kr32_sem);
    var tA=[70,70,73,74,75,77];
    var labs=rows.map(function(r){return semLabel(r.semana_inicio);});
    var vals=rows.map(function(r){return r.pct_activacion_comercial;});
    var tgt=rows.map(function(r){return semTarget(r.semana_inicio,tA)||70;});
    window._pulsoChart=new Chart(canvas,{type:'line',data:{labels:labs,datasets:[
      {label:'% activacion real',data:vals,borderColor:BL,backgroundColor:'rgba(37,99,235,.12)',borderWidth:2,pointRadius:3,fill:true,tension:0.3,order:2},
      {label:'target 70%',data:tgt,borderColor:'#CF222E',borderWidth:1.5,borderDash:[6,3],pointRadius:0,fill:false,tension:0,order:1}
    ]},options:{responsive:true,plugins:{legend:{position:'top'},tooltip:{mode:'index',intersect:false},title:{display:true,text:'% agencias que cotizaron y compraron — semanal'}},scales:{y:{min:30,ticks:{callback:function(v){return v+'%';}}}}}}); return;
  }

  if(activePulsoKR==='kr33'){
    var rows=DATA.kr33;
    function kr33L(r){var m=String(r.mes_evaluacion||'');if(m.length===6){var ym=m.substring(0,4)+'-'+m.substring(4,6);var mi=MONTHS.indexOf(ym);return mi>=0?LABELS[mi]:m;}return m;}
    var labs=rows.map(kr33L);
    var vals=rows.map(function(r){return r.pct_aumento;});
    window._pulsoChart=new Chart(canvas,{type:'bar',data:{labels:labs,datasets:[
      {label:'% agencias que aumentaron',data:vals,backgroundColor:vals.map(function(v){return v>=35?G:R;}),borderRadius:4},
      {label:'target 35%',data:labs.map(function(){return 35;}),type:'line',borderColor:'#CF222E',borderWidth:1.5,borderDash:[6,3],pointRadius:0,fill:false}
    ]},options:Object.assign({},base,{plugins:Object.assign({},base.plugins,{title:{display:true,text:'Frecuencia de compra — valores mensuales cerrados'}}),scales:{y:{min:30,max:40,ticks:{callback:function(v){return v+'%';}}}}})});
  }
}

var _statsRenderers={kr21:renderKR21Stats,kr22:renderKR22Stats,kr31:renderKR31Stats,kr32:renderKR32Stats,kr33:renderKR33Stats};

function getKRTrend(krId){
  var cfg={
    kr21:{rows:DATA.kr21_sem,f:'pct_timeout_client',inv:true},
    kr22:{rows:DATA.kr22_sem,f:'cant_agencias_unicas',inv:false},
    kr31:{rows:DATA.kr31_sem,f:'net_revenue_real',inv:false},
    kr32:{rows:DATA.kr32_sem,f:'pct_activacion_comercial',inv:false},
  }[krId];
  if(!cfg)return null;
  var vals=cfg.rows.map(function(r){return r[cfg.f];}).filter(function(v){return v!==null;});
  if(vals.length<2)return null;
  var n=vals.length,last=vals[n-1],prev=vals[n-2],prev2=n>2?vals[n-3]:null;
  var worse=function(a,b){return cfg.inv?a>b:a<b;};
  return{last:last,prev:prev,inv:cfg.inv,up:cfg.inv?last<prev:last>prev,declining:worse(last,prev)&&prev2!==null&&worse(prev,prev2)};
}

function renderTrendAlert(krId){
  var t=getKRTrend(krId);
  if(!t||!t.declining)return'';
  return'<div style="padding:10px 16px;margin-bottom:12px;background:#fef2f2;border:1px solid #fecaca;border-radius:var(--radius);font-size:12px;color:#b91c1c;display:flex;align-items:center;gap:8px"><span style="font-size:16px">&#9888;</span><span><b>Tendencia bajista</b> — 2 semanas consecutivas empeorando.</span></div>';
}


function renderPulso(){
  var html='<p class="sec-title">Monitor Semanal — H1 FY27</p>';
  html+='<div class="card" style="padding:14px 20px;margin-bottom:14px"><div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">';
  html+='<span class="filter-label" style="margin-right:4px">KR</span>';
  PULSO_KRS.forEach(function(kr){
    var a=activePulsoKR===kr.id?' active':'';
    var t=getKRTrend(kr.id);
    var dot=t&&t.declining?'<span style="display:inline-block;width:6px;height:6px;background:#ef4444;border-radius:50%;margin-left:4px;vertical-align:middle"></span>':'';
    html+='<button class="pill krpill'+a+'" data-kr="'+kr.id+'" onclick="setPulsoKR(this.dataset.kr)">'+kr.label+dot+'</button>';
  });
  html+='</div></div>';
  html+='<div id="monitor-desc" style="padding:12px 16px;margin-bottom:14px;background:#EEF2FF;border:1px solid #C7D2FE;border-radius:var(--radius);font-size:12px;color:#3730A3">'+PULSO_DESCS[activePulsoKR]+'</div>';
  html+=renderTrendAlert(activePulsoKR);
  var fn=_statsRenderers[activePulsoKR];
  if(fn)html+=fn();
  html+='<div class="card" style="padding:20px 20px 16px"><canvas id="pulso-canvas" style="max-height:380px"></canvas></div>';
  return html;
}

document.querySelectorAll('.mespill[data-mes]').forEach(function(b){
  if(b.dataset.mes!=='all'&&b.dataset.mes>nowYm())b.style.display='none';
});
render();
</script>
</body>
</html>"""

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

def main():
    data = run_queries()
    updated = datetime.now().strftime('%Y-%m-%d %H:%M')
    html = build_html(data, updated)

    output = Path(__file__).parent.parent.parent / 'okrs_dashboard.html'
    output.write_text(html, encoding='utf-8')

    print(f"\nDashboard generado: {output}")
    print(f"Abrilo en el navegador: {output}")

if __name__ == '__main__':
    main()
