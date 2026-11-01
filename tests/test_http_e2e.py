"""Actual loopback HTTP tests: launch uvicorn in a subprocess, not TestClient."""
import io
import os
import socket
import subprocess
import sys
import time

import httpx
import pandas as pd
import pytest


@pytest.fixture(scope='module')
def server(tmp_path_factory):
    temp = tmp_path_factory.mktemp('http_data')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    env = {**os.environ, 'DATADOCTOR_DB_PATH': str(temp / 'history.sqlite3')}
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'datadoctor.api:app', '--host', '127.0.0.1', '--port', str(port)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    try:
        for _ in range(100):
            if proc.poll() is not None:
                raise RuntimeError(f'Uvicorn exited: {proc.stderr.read().decode(errors="replace")[-1200:]}')
            try:
                if httpx.get(base + '/health', timeout=0.2).status_code == 200:
                    break
            except httpx.RequestError:
                time.sleep(0.1)
        else:
            raise RuntimeError('Uvicorn did not become ready')
        yield base, temp
    finally:
        proc.terminate()
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate(timeout=5)


def test_http_dashboard_and_health(server):
    base, _ = server
    with httpx.Client(base_url=base) as client:
        assert client.get('/health').json()['status'] == 'ok'
        assert 'DataDoctor' in client.get('/').text


def test_http_csv_analyze_clean_download_and_sqlite(server):
    base, temp = server
    payload = b'id,price\n001,10\n001,10\n002,\n'
    with httpx.Client(base_url=base, timeout=15) as client:
        audit = client.post('/api/analyze', files={'file': ('private.csv', payload, 'text/csv')})
        assert audit.status_code == 200, audit.text
        assert audit.json()['summary']['duplicate_rows'] == 1
        assert audit.json()['summary']['missing_cells'] == 1
        cleaned = client.post('/api/clean', data={'missing_strategy': 'fill'}, files={'file': ('private.csv', payload, 'text/csv')})
        assert cleaned.status_code == 200, cleaned.text
        assert cleaned.headers['content-disposition'].startswith('attachment;')
        assert cleaned.headers['x-datadoctor-removed-duplicates'] == '1'
        assert cleaned.headers['x-datadoctor-filled-cells'] == '1'
        assert cleaned.content.decode('utf-8-sig').splitlines()[1].startswith('001,')
        runs = client.get('/api/history').json()['runs']
        assert len(runs) >= 2
        assert 'private.csv' not in str(runs)
    import sqlite3
    with sqlite3.connect(temp / 'history.sqlite3') as conn:
        assert conn.execute('select count(*) from runs').fetchone()[0] >= 2
        names = [column[1] for column in conn.execute('pragma table_info(runs)')]
        assert not any(x in names for x in ['filename', 'raw_data', 'upload', 'content'])


def test_http_excel_analyze_download(server):
    base, _ = server
    buf = io.BytesIO()
    pd.DataFrame({'product': ['A', 'B'], 'price': [12, None]}).to_excel(buf, index=False)
    with httpx.Client(base_url=base, timeout=15) as client:
        audited = client.post('/api/analyze', files={'file': ('data.xlsx', buf.getvalue(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
        assert audited.status_code == 200, audited.text
        assert audited.json()['summary']['missing_cells'] == 1
        cleaned = client.post('/api/clean', files={'file': ('data.xlsx', buf.getvalue(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
        assert cleaned.status_code == 200, cleaned.text
        assert cleaned.content.startswith(b'PK')
        output = pd.read_excel(io.BytesIO(cleaned.content))
        assert len(output) == 2


def test_http_oversized_and_corrupt_files(server):
    base, _ = server
    with httpx.Client(base_url=base, timeout=30) as client:
        too_large = client.post('/api/analyze', files={'file': ('large.csv', b'a\n' + b'x' * (10 * 1024 * 1024), 'text/csv')})
        assert too_large.status_code == 400
        assert 'limit' in too_large.json()['detail']
        for name, content in [('bad.xlsx', b'not-an-excel-file'), ('bad.csv', b'\xff\xfe\xfd')]:
            reply = client.post('/api/analyze', files={'file': (name, content)})
            assert reply.status_code == 400, (name, reply.status_code, reply.text[:300])


def test_http_formula_safety_and_non_destructive_outliers(server):
    base, _ = server
    original = b'comment,amount\n"=1+2",10\nsafe,11\nsafe,12\nsafe,13\nsafe,14\nsafe,300\n'
    with httpx.Client(base_url=base, timeout=15) as client:
        clean = client.post('/api/clean', data={'drop_duplicates': 'false'}, files={'file': ('data.csv', original)})
        assert clean.status_code == 200, clean.text
        text = clean.content.decode('utf-8-sig')
        assert "'=1+2" in text
        assert '300' in text
        assert clean.headers['x-datadoctor-capped-outliers'] == '0'


def test_http_valid_zip_without_workbook_is_rejected(server):
    import zipfile
    base, _ = server
    fake = io.BytesIO()
    with zipfile.ZipFile(fake, 'w') as archive:
        archive.writestr('not_a_workbook.txt', 'hello')
    reply = httpx.post(base + '/api/analyze', files={'file': ('corrupt.xlsx', fake.getvalue())}, timeout=15)
    assert reply.status_code == 400, (reply.status_code, reply.text[:500])


def test_http_column_limit_rejected(server):
    base, _ = server
    extra_columns = (','.join('c'+str(n) for n in range(101)) + '\n' + ','.join('x' for _ in range(101)) + '\n').encode()
    reply = httpx.post(base + '/api/analyze', files={'file': ('wide.csv', extra_columns)}, timeout=15)
    assert reply.status_code == 400
    assert 'Maximum table size' in reply.json()['detail']
