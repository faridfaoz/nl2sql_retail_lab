import pytest
from src.app import check_sql, GuardrailError, normalize_llm_sql, answer
from src.setup_db import create
import duckdb

def test_readonly_queries():
    assert 'SELECT' in check_sql('SELECT COUNT(*) FROM sales')
    for sql in ['DROP TABLE sales','SELECT * FROM read_csv(\'/etc/passwd\')',
                'SELECT * FROM sales; DELETE FROM sales','SELECT * FROM secrets',
                'SELECT * FROM sales -- comment']:
        with pytest.raises(GuardrailError): check_sql(sql)

def test_normalize_llm_sql():
    assert normalize_llm_sql('SELECT 1;') == 'SELECT 1'
    assert normalize_llm_sql('SELECT 1 ;  ') == 'SELECT 1'
    assert normalize_llm_sql('```sql\nSELECT COUNT(*) FROM sales;\n```') == 'SELECT COUNT(*) FROM sales'
    assert 'SELECT' in check_sql(normalize_llm_sql('SELECT COUNT(*) FROM sales;'))
    with pytest.raises(GuardrailError): check_sql(normalize_llm_sql('SELECT 1; DELETE FROM sales;'))
    with pytest.raises(GuardrailError): check_sql(normalize_llm_sql('SELECT * FROM sales -- c'))

def test_answer_normalizes_and_audits(tmp_path, monkeypatch):
    import src.app as engine
    db=tmp_path/'test.duckdb'; create(db)
    monkeypatch.setattr(engine,'DB',db)
    monkeypatch.setattr(engine,'LOG',tmp_path/'history.jsonl')
    monkeypatch.setattr(engine,'llm_sql',lambda q,mock:'SELECT COUNT(*) FROM sales;')
    ev=answer('q',mock=False)
    assert ev['status']=='ok' and ';' not in ev['sql'] and 'rejected_sql' not in ev
    monkeypatch.setattr(engine,'llm_sql',lambda q,mock:'SELECT 1; DROP TABLE sales')
    ev=answer('q',mock=False)
    assert ev['status']=='error' and ev['rejected_sql']=='SELECT 1; DROP TABLE sales'

def test_generated_warehouse(tmp_path):
    path=tmp_path/'test.duckdb';create(path)
    con=duckdb.connect(str(path),read_only=True)
    assert con.execute('SELECT COUNT(*) FROM sales').fetchone()[0]==20000
    assert con.execute('SELECT COUNT(*) FROM products').fetchone()[0]==24
    assert con.execute('SELECT COUNT(*) FROM stores').fetchone()[0]==8
    assert con.execute('SELECT COUNT(*) FROM customers').fetchone()[0]==150
    assert con.execute('SELECT COUNT(*) FROM suppliers').fetchone()[0]==6
    assert con.execute('SELECT MIN(sale_date), MAX(sale_date) FROM sales').fetchone()[0].year==2026
    con.close()

def test_referential_integrity(tmp_path):
    path=tmp_path/'test.duckdb';create(path)
    con=duckdb.connect(str(path),read_only=True)
    assert con.execute('''SELECT COUNT(*) FROM sales s LEFT JOIN stores st USING(store_id)
                          WHERE st.store_id IS NULL''').fetchone()[0]==0
    assert con.execute('''SELECT COUNT(*) FROM sales s LEFT JOIN products p USING(product_id)
                          WHERE p.product_id IS NULL''').fetchone()[0]==0
    assert con.execute('''SELECT COUNT(*) FROM sales s LEFT JOIN customers c USING(customer_id)
                          WHERE s.customer_id IS NOT NULL AND c.customer_id IS NULL''').fetchone()[0]==0
    assert con.execute('''SELECT COUNT(*) FROM products p LEFT JOIN suppliers sup USING(supplier_id)
                          WHERE sup.supplier_id IS NULL''').fetchone()[0]==0
    assert con.execute('SELECT COUNT(*) FROM sales WHERE customer_id IS NULL').fetchone()[0]>0
    con.close()

def test_join_queries_allowed(tmp_path):
    path=tmp_path/'test.duckdb';create(path)
    con=duckdb.connect(str(path),read_only=True)
    sql='''SELECT sup.supplier_name, ROUND(SUM(CASE WHEN NOT s.returned
           THEN s.quantity*s.unit_price*(1-s.discount_pct) ELSE 0 END),2) AS revenue_mxn
           FROM sales s JOIN products p USING(product_id) JOIN suppliers sup USING(supplier_id)
           GROUP BY 1 ORDER BY revenue_mxn DESC LIMIT 10'''
    con.execute(check_sql(sql))
    assert con.fetchone()[0] is not None
    con.close()
