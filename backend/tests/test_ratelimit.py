from fastapi.testclient import TestClient

from grounded_rag.api import ratelimit
from grounded_rag.api.main import app
from grounded_rag.api.ratelimit import TokenBucketLimiter


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_bucket_allows_the_rate_then_asks_to_wait():
    clock = Clock()
    limiter = TokenBucketLimiter(2, clock=clock)
    assert limiter.check("1.2.3.4") is None
    assert limiter.check("1.2.3.4") is None
    wait = limiter.check("1.2.3.4")
    assert wait is not None and 0 < wait <= 30
    assert limiter.check("5.6.7.8") is None     # another client has its own bucket
    clock.t += 30                               # 2 per minute: one token back
    assert limiter.check("1.2.3.4") is None


def test_zero_turns_the_limit_off():
    limiter = TokenBucketLimiter(0, clock=Clock())
    assert all(limiter.check("x") is None for _ in range(100))


def test_route_answers_429_with_retry_after(monkeypatch):
    monkeypatch.setattr(ratelimit, "limiter", TokenBucketLimiter(1, clock=Clock()))
    client = TestClient(app)
    body = {"question": "Thời giờ làm việc?"}
    assert client.post("/api/chat", json=body).status_code == 200
    r = client.post("/api/chat", json=body)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"
    assert int(r.headers["retry-after"]) >= 1
    # the limit is on asking, not on reading
    assert client.get("/api/conversations").status_code == 200


def test_forwarded_for_counts_only_behind_a_trusted_proxy(monkeypatch):
    from grounded_rag.config import settings

    monkeypatch.setattr(ratelimit, "limiter", TokenBucketLimiter(1, clock=Clock()))
    client = TestClient(app)
    body = {"question": "Thời giờ làm việc?"}
    spoofed = {"X-Forwarded-For": "9.9.9.9"}
    assert client.post("/api/chat", json=body).status_code == 200
    # untrusted: the header is ignored, so it is the same client again
    assert client.post("/api/chat", json=body, headers=spoofed).status_code == 429
    monkeypatch.setattr(settings, "trust_proxy", True)
    assert client.post("/api/chat", json=body, headers=spoofed).status_code == 200


def test_a_spoofed_first_hop_does_not_buy_a_new_bucket(monkeypatch):
    """nginx appends the address it saw to whatever X-Forwarded-For the client
    sent: only the last hop is the proxy's word."""
    from grounded_rag.config import settings

    monkeypatch.setattr(ratelimit, "limiter", TokenBucketLimiter(1, clock=Clock()))
    monkeypatch.setattr(settings, "trust_proxy", True)
    client = TestClient(app)
    body = {"question": "Thời giờ làm việc?"}
    assert client.post("/api/chat", json=body,
                       headers={"X-Forwarded-For": "1.1.1.1, 7.7.7.7"}).status_code == 200
    again = client.post("/api/chat", json=body, headers={"X-Forwarded-For": "2.2.2.2, 7.7.7.7"})
    assert again.status_code == 429


def test_ipv6_clients_are_counted_per_slash_64():
    """One home network gets a /64; counting each address would give it 2^64 buckets."""
    from starlette.requests import Request

    def key(host):
        return ratelimit.client_key(Request({"type": "http", "headers": [], "client": (host, 1)}))

    assert key("2001:db8:1:2:aaaa::1") == key("2001:db8:1:2:bbbb::9")
    assert key("2001:db8:1:2::1") != key("2001:db8:1:3::1")
    assert key("203.0.113.7") == "203.0.113.7"
