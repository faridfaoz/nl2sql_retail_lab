"""Grounded answer narration: the model may only restate values DuckDB returned.

This implements the workshop stretch task (c): a separate narration stage that
receives the question plus the evidence rows and refuses unsupported claims.
It never produces numbers on its own; DuckDB remains the only source of facts.
"""
import os

from openai import OpenAI


def _evidence_text(event, max_rows=50):
    columns = event.get('columns') or []
    rows = event.get('rows') or []
    lines = [','.join(str(c) for c in columns)]
    lines += [','.join('' if v is None else str(v) for v in row) for row in rows[:max_rows]]
    return '\n'.join(lines)


def narrate(question, event, mock=False):
    """Return a short answer grounded strictly in the evidence rows, or None."""
    if event.get('status') != 'ok':
        return None
    rows = event.get('rows') or []
    columns = event.get('columns') or []
    if not rows:
        return ('DuckDB returned no matching records, so no business conclusion '
                'can be supported for this question.')
    if mock:
        first = '; '.join(f'{c}={v}' for c, v in zip(columns, rows[0]) if v is not None)
        return (f'Mock mode: DuckDB returned {len(rows)} row(s) for this question. '
                f'First row: {first}. Set MOCK_LLM=0 to use MaaS for a natural-language summary.')
    key = os.getenv('MAAS_API_KEY', '')
    model = os.getenv('MAAS_MODEL', '')
    base = os.getenv('MAAS_BASE_URL', '')
    if not key or key == 'replace-me' or not model or model == 'replace-with-enabled-model-id' or not base:
        return None
    client = OpenAI(api_key=key, base_url=base, timeout=45, max_retries=1)
    system = ('You are a business analyst narrator. Answer the user question in at most 80 words, '
              'using ONLY the values that appear in the CSV evidence provided. Never invent, estimate, '
              'round differently or extrapolate numbers. Name the metric and scope of every value you '
              'cite. If the evidence cannot answer the question, state that explicitly. Plain text only.')
    user = (f'Question: {question}\n\n'
            f'Evidence (columns and rows returned by DuckDB):\n{_evidence_text(event)}')
    out = client.chat.completions.create(model=model,
                                         messages=[{'role': 'system', 'content': system},
                                                   {'role': 'user', 'content': user}],
                                         temperature=0)
    text = (out.choices[0].message.content or '').strip()
    return text or None
