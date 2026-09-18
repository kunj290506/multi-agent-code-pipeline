from fastapi.testclient import TestClient

client = TestClient('http://testserver')

def test_api():
    response = client.post('/api/endpoint', json={'key': 'value'})
    assert response.status_code == 200
    assert response.json() == {'message': 'success'}

if __name__ == '__main__':
    test_api()
