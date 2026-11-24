"""Streamlit web interface for the Retail NL2SQL lab.

Same trust model as the console app (src/app.py): MaaS proposes SQL, sqlglot
guardrails validate it, DuckDB executes it read-only and remains the only
source of numbers, and every question is logged to query_history.jsonl.
The optional summary only restates evidence rows that DuckDB returned.

Launch from the project root:
    python -m streamlit run src/webapp.py
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import duckdb
import pandas as pd
import streamlit as st

import src.app as engine
from src.app import SCHEMA, TABLES, answer
from src.narrator import narrate

st.set_page_config(page_title='Retail NL2SQL Lab', layout='wide')

MOCK = os.getenv('MOCK_LLM', '1') == '1'
SAMPLES = [
    'Que categoria genera mas ingresos netos?',
    'Muestra las ventas netas mensuales en 2026',
    'Cuales son las tres tiendas con mayores ingresos netos?',
    'Que categoria tiene el mayor beneficio bruto?',
    'Cual es el porcentaje de lineas devueltas por canal?',
    'Compara los ingresos de agosto contra septiembre',
    'Ingresos netos por segmento de cliente',
    'Top 10 clientes por ingresos netos',
    'Que proveedor genera mas ingresos netos?',
    'Ingresos netos por region',
    'Ingresos netos por ciudad de tienda',
    'Cuantas lineas de venta hay en total?',
]


def get_summary(event, enabled):
    """Memoized grounded summary so reruns and history clicks do not repeat MaaS calls."""
    if not enabled:
        return None
    key = (event.get('timestamp_utc'), event.get('question'))
    cache = st.session_state.setdefault('summaries', {})
    if key not in cache:
        try:
            cache[key] = narrate(event['question'], event, MOCK)
        except Exception as exc:
            cache[key] = None
            st.warning(f'Answer summary unavailable: {exc}')
    return cache[key]


def render_event(event):
    st.subheader('Q: ' + event['question'])
    if event['status'] != 'ok':
        st.error('Unable to answer safely: ' + str(event.get('error', '')))
        if event.get('rejected_sql'):
            st.caption('The guardrails rejected this SQL proposal from the model:')
            st.code(event['rejected_sql'], language='sql')
        st.info('Rephrase the question. The guardrails and the read-only database stay on.')
        return
    m1, m2, m3, m4 = st.columns(4)
    m1.metric('Rows returned', len(event['rows']))
    m2.metric('SQL generation', f"{event.get('sql_generation_s', 0)} s")
    m3.metric('SQL execution', f"{event.get('sql_execution_s', 0)} s")
    m4.metric('Total time', f"{event.get('elapsed_s', 0)} s")
    st.markdown('#### Answer')
    summary = get_summary(event, st.session_state.get('summarize', True))
    if summary:
        st.info(summary)
        st.caption('Model-generated summary grounded only in the evidence rows below; '
                   'verify every number against the table.')
    else:
        st.info('Read the evidence table and state a conclusion using only the displayed '
                'measures and their scope.')
    left, right = st.columns([2, 3])
    with left:
        st.markdown('#### SQL applied')
        st.code(event['sql'], language='sql')
        st.caption('Validated by sqlglot guardrails; executed read-only on DuckDB.')
    with right:
        st.markdown('#### Query result')
        df = pd.DataFrame(event['rows'], columns=event['columns'])
        st.dataframe(df, hide_index=True)
        if event.get('truncated'):
            st.warning('Showing the first 50 rows; output was truncated by the safety limit.')
        if df.empty:
            st.info('No matching records. No business conclusion can be supported.')
        else:
            if len(df.columns) == 2:
                values = pd.to_numeric(df.iloc[:, 1], errors='coerce')
                if values.notna().all():
                    chart = pd.DataFrame({str(df.columns[1]): values.values},
                                         index=df.iloc[:, 0].astype(str))
                    st.bar_chart(chart)
            st.download_button('Download result as CSV', df.to_csv(index=False).encode('utf-8'),
                                file_name='query_result.csv', mime='text/csv')


def compute_profile():
    """Table inventory and per-column stats straight from read-only DuckDB; no LLM involved."""
    con = duckdb.connect(str(engine.DB), read_only=True)
    try:
        names = [r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main' ORDER BY table_name").fetchall()]
        profile = {'computed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                   'tables': {}}
        for name in names:
            cols = con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema='main' AND table_name=? ORDER BY ordinal_position",
                [name]).fetchall()
            col_stats = []
            for col, dtype in cols:
                d = dtype.upper()
                if d.startswith(('INTEGER', 'BIGINT', 'SMALLINT', 'TINYINT', 'HUGEINT',
                                 'DECIMAL', 'DOUBLE', 'REAL')):
                    kind = 'numeric'
                elif d.startswith(('DATE', 'TIMESTAMP')):
                    kind = 'date'
                elif d.startswith('BOOLEAN'):
                    kind = 'boolean'
                elif d.startswith(('VARCHAR', 'CHAR', 'TEXT')):
                    kind = 'text'
                else:
                    kind = 'other'
                selects = ['COUNT(*) AS n', f'COUNT("{col}") AS non_null',
                           f'COUNT(DISTINCT "{col}") AS distinct_values']
                if kind == 'numeric':
                    selects += [f'MIN("{col}") AS lo', f'ROUND(AVG("{col}"), 2) AS av',
                                f'MAX("{col}") AS hi']
                elif kind == 'date':
                    selects += [f'MIN("{col}") AS lo', f'MAX("{col}") AS hi']
                elif kind == 'boolean':
                    selects += [f'ROUND(100.0 * AVG(CASE WHEN "{col}" THEN 1.0 ELSE 0.0 END), 1) AS true_pct']
                elif kind == 'text':
                    selects += [f'MODE("{col}") AS top_value']
                n, non_null, distinct, *extra = con.execute(
                    f'SELECT {", ".join(selects)} FROM "{name}"').fetchone()
                if kind == 'numeric':
                    summary = f'min {extra[0]}, avg {extra[1]}, max {extra[2]}'
                elif kind == 'date':
                    summary = f'{extra[0]} to {extra[1]}'
                elif kind == 'boolean':
                    summary = f'{extra[0]}% TRUE'
                elif kind == 'text':
                    summary = f'most frequent: {extra[0]}' if extra[0] is not None else 'all NULL'
                else:
                    summary = ''
                col_stats.append({'column': col, 'type': dtype,
                                  'null_pct': round(100.0 * (n - non_null) / n, 1) if n else 0.0,
                                  'distinct': distinct, 'summary': summary})
            rows = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            profile['tables'][name] = {'rows': rows, 'columns': col_stats}
        return profile
    finally:
        con.close()


def ask_sample(sample):
    """on_click callback: runs before the question widget exists, so it may set its state."""
    st.session_state['question'] = sample
    st.session_state['pending'] = sample


st.title('Retail NL2SQL')
st.caption(f'Mode: {"MOCK" if MOCK else "Huawei MaaS"} · MaaS generates SQL, guardrails validate it, '
           'DuckDB executes it read-only and returns the evidence.')
if not engine.DB.exists():
    st.error('retail.duckdb not found. Run `python -m src.setup_db` and reload this page.')
    st.stop()

ask_tab, catalog_tab = st.tabs(['Ask a question', 'Data catalog'])

with ask_tab:
    question = st.text_input('Your business question', key='question',
                             placeholder='e.g. ventas por categoria')
    ask_col, opt_col = st.columns([1, 2])
    ask = ask_col.button('Ask', key='ask', type='primary')
    opt_col.checkbox('Generate grounded answer summary', key='summarize', value=True,
                     help='Extra MaaS call that may only restate values returned by DuckDB. '
                          'In mock mode it shows a deterministic summary instead.')

    st.markdown('**Try a sample question:**')
    sample_cols = st.columns(3)
    for i, sample in enumerate(SAMPLES):
        sample_cols[i % 3].button(sample, key=f'sample_{i}', on_click=ask_sample, args=(sample,))

    to_ask = None
    if ask:
        to_ask = (st.session_state.get('question') or '').strip()
        if not to_ask:
            st.warning('Type a question first.')
            to_ask = None
    elif 'pending' in st.session_state:
        to_ask = st.session_state.pop('pending')
    if to_ask:
        with st.spinner('Generating SQL, checking guardrails and querying DuckDB...'):
            event = answer(to_ask, MOCK)
        st.session_state['last_event'] = event
        st.session_state.setdefault('history', []).insert(0, event)

    event = st.session_state.get('last_event')
    if event is None:
        st.info('Ask a question above (or click a sample) to see the generated SQL and the DuckDB evidence.')
    else:
        render_event(event)

with catalog_tab:
    st.markdown('#### Tables available in this workshop')
    st.caption(f'LLM queries are restricted by the guardrail allowlist to: {", ".join(sorted(TABLES))}. '
               'Join keys and metric definitions are in the sidebar schema. '
               'This profile is computed locally by read-only DuckDB, never by the LLM.')
    if st.button('Refresh table list and data profile', key='refresh_profile'):
        st.session_state['data_profile'] = compute_profile()
    if st.session_state.get('data_profile') is None:
        st.session_state['data_profile'] = compute_profile()
    profile = st.session_state['data_profile']
    st.caption(f"Profile computed at {profile['computed_at']} UTC. Rebuild the database with "
               '`python -m src.setup_db`, then click Refresh to see the new tables and counts.')
    overview = pd.DataFrame([{'table': name, 'rows': info['rows'], 'columns': len(info['columns'])}
                            for name, info in profile['tables'].items()])
    st.dataframe(overview, hide_index=True)
    for name, info in profile['tables'].items():
        with st.expander(f"{name} — {info['rows']:,} rows, {len(info['columns'])} columns"):
            st.dataframe(pd.DataFrame(info['columns']), hide_index=True)

with st.sidebar:
    st.header('Retail NL2SQL Lab')
    if MOCK:
        st.warning('Engine mode: MOCK (offline keyword templates). Set MOCK_LLM=0 in .env to use Huawei MaaS.')
    else:
        st.success('Engine mode: Huawei MaaS (the LLM generates SQL).')
    with st.expander('Schema and business metrics'):
        st.code(SCHEMA, language='text')
    st.subheader('Session history')
    history = st.session_state.get('history', [])
    if not history:
        st.caption('No questions yet in this session.')
    for i, ev in enumerate(history[:10]):
        status = 'OK' if ev['status'] == 'ok' else 'ERROR'
        label = f"[{status}] {ev['question'][:60]}"
        if st.button(label, key=f'history_{i}', help=f"{ev.get('elapsed_s', 0)} s"):
            st.session_state['last_event'] = ev
            st.rerun()
    st.caption('Every question is also logged to query_history.jsonl with SQL, rows and timings.')
