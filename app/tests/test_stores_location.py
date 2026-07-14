from fastapi.testclient import TestClient


def test_stores_include_location_fields(client: TestClient):
    response = client.get("/stores")
    assert response.status_code == 200

    store = response.json()["stores"][0]
    assert store["address"]
    assert store["latitude"] is not None
    assert store["longitude"] is not None


def test_stores_can_be_sorted_and_filtered_by_current_location(client: TestClient):
    response = client.get("/stores", params={"lat": 36.36234, "lng": 127.34486, "radius_km": 0.2})
    assert response.status_code == 200

    stores = response.json()["stores"]
    assert [store["name"] for store in stores] == ["\ub3d9\ub124\ucee4\ud53c \uc720\uc131\uc810"]
    assert stores[0]["distance_m"] == 0


def test_stores_can_search_by_name(client: TestClient):
    response = client.get("/stores", params={"q": "\ubd84\uc2dd"})
    assert response.status_code == 200

    stores = response.json()["stores"]
    assert len(stores) == 1
    assert stores[0]["name"] == "\uc6b0\ub9ac\ubd84\uc2dd"
