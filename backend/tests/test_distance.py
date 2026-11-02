from app.services.distance import haversine_km


def test_haversine_distance_for_same_point_is_zero():
    assert haversine_km(39.9, 116.4, 39.9, 116.4) == 0


def test_haversine_distance_is_symmetric_and_reasonable():
    forward = haversine_km(39.9, 116.4, 39.91, 116.4)
    reverse = haversine_km(39.91, 116.4, 39.9, 116.4)

    assert forward == reverse
    assert 1.0 < forward < 1.2
