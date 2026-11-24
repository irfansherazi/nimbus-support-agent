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


def test_client_ip_uses_the_hop_our_proxy_appended():
    # Review I4: the first X-Forwarded-For entry is whatever the caller sent; the proxy appends the real address.
    assert client_ip({"x-forwarded-for": "1.2.3.4, 203.0.113.9"}, "10.0.0.2") == "203.0.113.9"
    assert client_ip({"x-forwarded-for": "203.0.113.9"}, "10.0.0.2") == "203.0.113.9"
    assert client_ip({}, "10.0.0.2") == "10.0.0.2"


def test_client_ip_with_two_trusted_proxies():
    assert client_ip({"x-forwarded-for": "6.6.6.6, 203.0.113.9, 10.1.1.1"}, None, trusted_hops=2) == "203.0.113.9"
