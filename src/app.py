"""Console NL2SQL: MaaS generates SQL; DuckDB supplies all facts and calculations."""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import duckdb
import sqlglot
from sqlglot import exp
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
DB = ROOT / 'retail.duckdb'
LOG = ROOT / 'query_history.jsonl'
console = Console()
SCHEMA = '''
stores(store_id INTEGER, store_name VARCHAR, city VARCHAR, region VARCHAR, opened_date DATE)
suppliers(supplier_id INTEGER, supplier_name VARCHAR, country VARCHAR, lead_time_days INTEGER)
products(product_id INTEGER, product_name VARCHAR, category VARCHAR, unit_cost DECIMAL(12,2), list_price DECIMAL(12,2), supplier_id INTEGER)
customers(customer_id INTEGER, customer_name VARCHAR, city VARCHAR, segment VARCHAR, signup_date DATE)
sales(sale_id INTEGER, sale_date DATE, store_id INTEGER, product_id INTEGER, customer_id INTEGER,
      quantity INTEGER, unit_price DECIMAL(12,2), discount_pct DECIMAL(5,2), channel VARCHAR, returned BOOLEAN)
Relationships: sales.store_id = stores.store_id; sales.product_id = products.product_id;
sales.customer_id = customers.customer_id (NULL for anonymous in-store purchases);
products.supplier_id = suppliers.supplier_id.
A row in sales is a transaction line; returned=TRUE means entirely returned.
Customer segments are Premium, Frecuente, Ocasional; channels are Tienda and Online.
Net revenue MXN (excluding returned lines): SUM(CASE WHEN NOT s.returned THEN s.quantity * s.unit_price * (1-s.discount_pct) ELSE 0 END).
Gross profit MXN (excluding returns): SUM(CASE WHEN NOT s.returned THEN s.quantity * (s.unit_price*(1-s.discount_pct) - p.unit_cost) ELSE 0 END), joining products p on s.product_id.
These are simplified accounting metrics; no tax, shipping, overhead, or partial returns.
Data covers January 1 to December 31, 2026. All data is synthetic.
'''
TABLES={'sales','stores','products','customers','suppliers'}
ALLOWED=(exp.Select, exp.Union)

class GuardrailError(ValueError): pass


def check_sql(sql):
    """Defensive SQL gate, not a general-purpose sandbox; use read-only DB and OS controls too."""
    if not isinstance(sql,str) or len(sql)>12000: raise GuardrailError('SQL is missing or too long')
    # Disallow comments and multiple statements before parsing.
    if '--' in sql or '/*' in sql or '*/' in sql or ';' in sql:
        raise GuardrailError('Comments and semicolons are not allowed')
    try: statements=sqlglot.parse(sql, read='duckdb')
    except Exception as exc: raise GuardrailError(f'SQL parsing failed: {exc}') from exc
    if len(statements)!=1 or not isinstance(statements[0], ALLOWED):
        raise GuardrailError('Only a single SELECT query is allowed')
    tree=statements[0]
    # Recursive structural denylist, including SQL embedded in subqueries.
    prohibited=[getattr(exp,name,None) for name in ('Insert','Update','Delete','Create','Drop','Alter','Command','Copy','Attach','Transaction','Pragma','Set','Merge')]
    for cls in (c for c in prohibited if c is not None):
        if tree.find(cls): raise GuardrailError(f'Prohibited SQL operation: {cls.__name__}')
    # CTE alias names are not physical data objects.
    ctes={c.alias.lower() for c in tree.find_all(exp.CTE) if c.alias}
    used={t.name.lower() for t in tree.find_all(exp.Table)}
    unknown=used-TABLES-ctes
    if unknown: raise GuardrailError(f'Non-allowlisted tables: {sorted(unknown)}')
    if not used: raise GuardrailError('Query must reference retail tables')
    # Block table functions, extension functions, remote access and local filesystem access.
    blocked={'read_csv','read_csv_auto','read_json','read_parquet','sqlite_scan','postgres_scan',
             'httpfs','query','query_table','write_file','read_text','read_blob','glob',
             'current_setting','getenv','load_extension','install','shell','secret'}
    for fn in tree.find_all(exp.Func):
        name=fn.sql_name().lower()
        if name in blocked: raise GuardrailError(f'Blocked function: {name}')
    return tree.sql(dialect='duckdb')


def run_query(sql):
    sql=check_sql(sql)
    con=duckdb.connect(str(DB),read_only=True)
    try:
        con.execute('SET memory_limit = \'512MB\'')
        con.execute('SET threads = 2')
        con.execute('SET enable_external_access = false')
        # Outer limit bounds returned evidence, even if model forgot a LIMIT.
        cur=con.execute(f'SELECT * FROM ({sql}) AS answer_rows LIMIT 51')
        columns=[x[0] for x in cur.description]
        rows=cur.fetchall()
        truncated=len(rows)>50
        return columns, rows[:50], truncated
    finally: con.close()


def normalize_llm_sql(sql):
    """Strip markdown fences and trailing semicolons that models habitually append.

    Only trailing semicolons are removed, so a semicolon inside the statement
    (for example an injected second statement) still fails check_sql.
    """
    s = sql.strip()
    if s.startswith('```'):
        end = s.find('\n')
        if end != -1:
            s = s[end + 1:]
            if s.rstrip().endswith('```'):
                s = s.rstrip()[:-3]
            s = s.strip()
    while s.endswith(';'):
        s = s[:-1].rstrip()
    return s


def llm_sql(question, mock=False):
    if mock:
        q=question.lower()
        if 'beneficio' in q or 'profit' in q:
            return "SELECT p.category, ROUND(SUM(CASE WHEN NOT s.returned THEN s.quantity*(s.unit_price*(1-s.discount_pct)-p.unit_cost) ELSE 0 END),2) AS gross_profit_mxn FROM sales s JOIN products p USING(product_id) GROUP BY p.category ORDER BY gross_profit_mxn DESC LIMIT 10"
        if 'top' in q:
            return "SELECT c.customer_name, c.city, ROUND(SUM(CASE WHEN NOT s.returned THEN s.quantity*s.unit_price*(1-s.discount_pct) ELSE 0 END),2) AS revenue_mxn FROM sales s JOIN customers c USING(customer_id) GROUP BY 1,2 ORDER BY revenue_mxn DESC LIMIT 10"
        if 'proveedor' in q or 'supplier' in q:
            return "SELECT sup.supplier_name, sup.country, ROUND(SUM(CASE WHEN NOT s.returned THEN s.quantity*s.unit_price*(1-s.discount_pct) ELSE 0 END),2) AS revenue_mxn FROM sales s JOIN products p USING(product_id) JOIN suppliers sup USING(supplier_id) GROUP BY 1,2 ORDER BY revenue_mxn DESC LIMIT 10"
        if 'cliente' in q or 'customer' in q or 'segment' in q:
            return "SELECT c.segment, ROUND(SUM(CASE WHEN NOT s.returned THEN s.quantity*s.unit_price*(1-s.discount_pct) ELSE 0 END),2) AS revenue_mxn, COUNT(DISTINCT s.customer_id) AS customers FROM sales s JOIN customers c USING(customer_id) GROUP BY 1 ORDER BY revenue_mxn DESC LIMIT 10"
        if 'region' in q:
            return "SELECT st.region, ROUND(SUM(CASE WHEN NOT s.returned THEN s.quantity*s.unit_price*(1-s.discount_pct) ELSE 0 END),2) AS revenue_mxn FROM sales s JOIN stores st USING(store_id) GROUP BY 1 ORDER BY revenue_mxn DESC LIMIT 10"
        if 'canal' in q or 'channel' in q:
            return "SELECT channel, ROUND(100.0*SUM(CASE WHEN returned THEN 1 ELSE 0 END)/COUNT(*),2) AS returned_pct, COUNT(*) AS lines FROM sales GROUP BY 1 ORDER BY 2 DESC"
        if 'compara' in q:
            return "SELECT DATE_TRUNC('month', sale_date)::DATE AS month, ROUND(SUM(CASE WHEN NOT returned THEN quantity*unit_price*(1-discount_pct) ELSE 0 END),2) AS revenue_mxn FROM sales WHERE sale_date BETWEEN DATE '2026-08-01' AND DATE '2026-09-30' GROUP BY 1 ORDER BY 1"
        if 'categor' in q:
            return "SELECT p.category, ROUND(SUM(CASE WHEN NOT s.returned THEN s.quantity*s.unit_price*(1-s.discount_pct) ELSE 0 END),2) AS revenue_mxn FROM sales s JOIN products p USING(product_id) GROUP BY p.category ORDER BY revenue_mxn DESC LIMIT 10"
        if 'mes' in q or 'month' in q:
            return "SELECT DATE_TRUNC('month', sale_date)::DATE AS month, ROUND(SUM(CASE WHEN NOT returned THEN quantity*unit_price*(1-discount_pct) ELSE 0 END),2) AS revenue_mxn FROM sales GROUP BY 1 ORDER BY 1"
        if 'tienda' in q or 'store' in q:
            return "SELECT st.store_name, st.city, ROUND(SUM(CASE WHEN NOT s.returned THEN s.quantity*s.unit_price*(1-s.discount_pct) ELSE 0 END),2) AS revenue_mxn FROM sales s JOIN stores st USING(store_id) GROUP BY 1,2 ORDER BY revenue_mxn DESC"
        return "SELECT COUNT(*) AS transaction_lines, SUM(CASE WHEN returned THEN 1 ELSE 0 END) AS returned_lines FROM sales"
    key=os.getenv('MAAS_API_KEY','')
    model=os.getenv('MAAS_MODEL','')
    base=os.getenv('MAAS_BASE_URL','')
    if not key or key=='replace-me' or not model or model=='replace-with-enabled-model-id' or not base:
        raise RuntimeError('Configure MAAS_BASE_URL, MAAS_MODEL and MAAS_API_KEY in .env')
    client=OpenAI(api_key=key,base_url=base,timeout=45,max_retries=1)
    prompt=f'''Translate the user's natural-language business question into ONE DuckDB SELECT statement.
Return JSON only with one key named "sql". No markdown fences, commentary, SQL comments, or trailing semicolons.
Only read sales, stores, products, customers, suppliers. Use join keys accurately, provide clear aliases,
use explicit calendar periods, honor business metric definitions; LIMIT at most 50 for detail listings.
Never invent columns or use external files. If the question cannot be answered using this schema,
return {{"sql":""}}.
Schema and metrics:\n{SCHEMA}'''
    out=client.chat.completions.create(model=model,messages=[{'role':'system','content':prompt},
                   {'role':'user','content':question}],temperature=0)
    content=out.choices[0].message.content or ''
    # Accept a JSON object only, not a freeform SQL blob.
    obj=json.loads(content)
    if not isinstance(obj,dict) or not isinstance(obj.get('sql'),str):
        raise GuardrailError('MaaS did not return expected JSON with sql string')
    if not obj['sql'].strip(): raise GuardrailError('Question cannot be answered from these tables')
    return obj['sql']


def answer(question, mock=False):
    started=time.time(); event={'timestamp_utc':datetime.now(timezone.utc).isoformat(),
                               'question':question,'mock':mock}
    proposed=None
    try:
        t0=time.time(); sql=llm_sql(question,mock); event['sql_generation_s']=round(time.time()-t0,3)
        proposed=sql
        normalized=check_sql(normalize_llm_sql(sql))
        t0=time.time(); cols,rows,truncated=run_query(normalized); event['sql_execution_s']=round(time.time()-t0,3)
        event.update(status='ok',sql=normalized,columns=cols,rows=[[str(v) if v is not None else None for v in r] for r in rows],truncated=truncated)
        return event
    except Exception as exc:
        event.update(status='error',error=str(exc))
        if proposed is not None: event['rejected_sql']=proposed
        return event
    finally:
        event['elapsed_s']=round(time.time()-started,3)
        with LOG.open('a',encoding='utf-8') as f: f.write(json.dumps(event,ensure_ascii=False)+'\n')


def print_result(event):
    if event['status']!='ok':
        console.print(f"[red]Unable to answer safely:[/red] {event['error']}")
        if event.get('rejected_sql'):
            console.print('[bold]Rejected SQL proposal[/bold]'); console.print(event['rejected_sql'])
        return
    console.print('[bold]Executed SQL[/bold]'); console.print(event['sql'])
    tbl=Table(show_header=True,header_style='bold cyan')
    for col in event['columns']: tbl.add_column(col)
    for row in event['rows']: tbl.add_row(*[str(v) if v is not None else 'NULL' for v in row])
    console.print(tbl)
    if not event['rows']: console.print('No matching records. No business conclusion can be supported.')
    else:
        console.print('[green]Evidence:[/green] Values above were returned by DuckDB, not generated by the LLM.')
        if event['truncated']: console.print('[yellow]Showing first 50 rows; output truncated.[/yellow]')
        console.print('Conclusion: interpret only the displayed measures and their stated date/filter scope.')


def main():
    mock=os.getenv('MOCK_LLM','1')=='1'
    if not DB.exists():
        console.print('[red]Database missing. Run python -m src.setup_db first.[/red]'); sys.exit(1)
    console.print(f'[bold]Retail NL2SQL[/bold] | mode={"MOCK" if mock else "Huawei MaaS"} | :quit to exit')
    console.print('Try: ventas por categoria | ventas por tienda | beneficio por categoria | ingresos por segmento de cliente | ventas por proveedor | cuantas ventas')
    while True:
        try: question=input('\nRetail BI> ').strip()
        except (EOFError,KeyboardInterrupt): break
        if question.lower() in (':quit',':exit','exit','quit'):break
        if not question:continue
        print_result(answer(question,mock))

if __name__=='__main__': main()
