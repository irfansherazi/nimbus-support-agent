from app.ratelimit import SlidingWindowLimiter, client_ip


def test_sliding_window():
    lim = SlidingWindowLimiter(2, 60)
    assert lim.hit("k") and lim.hit("k") and not lim.hit("k") and lim.hit("other")


def test_window_expires():
    now = [1000.0]
    lim = SlidingWindowLimiter(1, 10, clock=lambda: now[0])
    assert lim.hit("k") and not lim.hit("k")
    now[0] += 10.01
    assert lim.hit("k")


def test_client_ip_prefers_first_forwarded_hop():
    assert client_ip({"x-forwarded-for": "203.0.113.9, 10.0.0.1"}, "10.0.0.2") == "203.0.113.9"
    assert client_ip({}, "10.0.0.2") == "10.0.0.2"
