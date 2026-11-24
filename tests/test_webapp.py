import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.narrator import narrate
from src.setup_db import create

ROOT = Path(__file__).resolve().parents[1]


def test_narrate_skips_errors():
    assert narrate('q', {'status': 'error', 'error': 'boom'}, mock=True) is None


def test_narrate_no_rows():
    ev = {'status': 'ok', 'columns': ['a'], 'rows': []}
    text = narrate('q', ev, mock=True)
    assert text and 'no matching records' in text


def test_narrate_mock_grounded():
    ev = {'status': 'ok', 'question': 'q', 'columns': ['category', 'revenue_mxn'],
          'rows': [['Ropa', '100.0'], ['Hogar', '50.0']], 'truncated': False}
    text = narrate('q', ev, mock=True)
    assert text and '2 row(s)' in text and 'Ropa' in text


def test_webapp_flow(tmp_path, monkeypatch):
    import src.app as engine
    db = tmp_path / 'test.duckdb'
    create(db)
    monkeypatch.setattr(engine, 'DB', db)
    monkeypatch.setattr(engine, 'LOG', tmp_path / 'history.jsonl')
    monkeypatch.setenv('MOCK_LLM', '1')
    at = AppTest.from_file(str(ROOT / 'src' / 'webapp.py'))
    at.run()
    assert not at.exception
    at.text_input(key='question').set_value('ventas por categoria')
    at.button(key='ask').click().run()
    assert not at.exception
    assert at.metric[0].value == '6'
    assert (6, 2) in [d.value.shape for d in at.dataframe]
    assert 'SELECT' in at.code[0].value
    assert (tmp_path / 'history.jsonl').exists()


def test_webapp_catalog(tmp_path, monkeypatch):
    import src.app as engine
    db = tmp_path / 'test.duckdb'
    create(db)
    monkeypatch.setattr(engine, 'DB', db)
    monkeypatch.setenv('MOCK_LLM', '1')
    at = AppTest.from_file(str(ROOT / 'src' / 'webapp.py'))
    at.run()
    assert not at.exception
    at.button(key='refresh_profile').click().run()
    assert not at.exception
    overviews = [d.value for d in at.dataframe if 'table' in d.value.columns]
    assert len(overviews) == 1
    assert set(overviews[0]['table']) == {'customers', 'products', 'sales', 'stores', 'suppliers'}
    assert (overviews[0]['rows'] == 20000).any()
