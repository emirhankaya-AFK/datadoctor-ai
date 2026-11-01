from fastapi.testclient import TestClient
import pytest

from datadoctor.api import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('DATADOCTOR_DB_PATH', str(tmp_path / 'history.sqlite3'))
    with TestClient(app) as client:
        yield client


def test_health_and_dashboard(client):
    assert client.get('/health').json()['status'] == 'ok'
    assert 'DataDoctor' in client.get('/').text


def test_analyze_history_no_personal_data(client):
    response = client.post('/api/analyze', files={'file': ('private.csv', b'a,b\n1,x\n1,x\n2,\n', 'text/csv')})
    assert response.status_code == 200
    assert response.json()['summary']['duplicate_rows'] == 1
    history = client.get('/api/history').json()['runs']
    assert len(history) == 1 and history[0]['action'] == 'analyze'
    assert 'private' not in str(history)


def test_clean_download(client):
    response = client.post('/api/clean', data={'missing_strategy':'fill'}, files={'file':('data.csv', b'a,b\n1,x\n1,x\n2,\n')})
    assert response.status_code == 200
    assert 'attachment;' in response.headers['content-disposition']
    assert response.headers['x-datadoctor-removed-duplicates'] == '1'
    assert response.headers['x-datadoctor-filled-cells'] == '1'
    assert len(response.content) > 0


def test_errors(client):
    invalid = client.post('/api/analyze', files={'file':('bad.txt', b'a,b', 'text/plain')})
    assert invalid.status_code == 400
    assert 'supported' in invalid.json()['detail']
    wrong = client.post('/api/clean', data={'missing_strategy':'wipe'}, files={'file':('ok.csv',b'a\n1\n')})
    assert wrong.status_code == 400


def test_large_upload_rejected(client):
    payload = b'a\n' + b'x' * (10 * 1024 * 1024)
    response = client.post('/api/analyze', files={'file':('big.csv',payload)})
    assert response.status_code == 400
    assert 'limit' in response.json()['detail']
