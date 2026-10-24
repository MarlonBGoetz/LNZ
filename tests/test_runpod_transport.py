"""Transport-header tests for RealBackend (offline, no network).

Runpod sits behind Cloudflare, which 403s urllib's default
``User-Agent: Python-urllib/3.x`` with ``error code: 1010``. Both transport
methods (``_request`` for REST and ``_graphql`` for pricing) must therefore
send a non-default User-Agent. These tests capture the ``urllib.request.Request``
each method builds WITHOUT making any network call (``urlopen`` is monkeypatched
to a stub) and assert the User-Agent header is present and is not the default
Python-urllib one. The API key is never asserted on or logged.
"""

from __future__ import annotations

import io
import urllib.request

import pytest

from overwatch import runpod_client


class _FakeResponse(io.BytesIO):
    """Minimal context-manager stand-in for an ``http.client`` response."""

    def __enter__(self):  # noqa: D401 - context manager protocol
        return self

    def __exit__(self, *exc):
        self.close()
        return False


@pytest.fixture()
def capture_request(monkeypatch):
    """Monkeypatch urlopen to capture the outgoing Request and return []."""
    captured = {}

    def fake_urlopen(req, timeout=None):  # no network: just record and reply
        captured["req"] = req
        return _FakeResponse(b"[]")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return captured


def _user_agent(req):
    # urllib stores headers capitalised (e.g. "User-agent").
    return req.get_header("User-agent")


def test_rest_request_sets_non_default_user_agent(capture_request):
    backend = runpod_client.RealBackend("secret-key")
    backend._request("GET", "/pods")

    req = capture_request["req"]
    ua = _user_agent(req)
    assert ua, "REST request must carry a User-Agent header"
    assert "python-urllib" not in ua.lower(), (
        "User-Agent must not be the default urllib signature that Cloudflare blocks"
    )
    assert ua == runpod_client.USER_AGENT
    # Auth scheme that works for curl must be preserved; key must stay secret.
    assert req.get_header("Authorization") == "Bearer secret-key"
    assert req.get_header("Accept") == "application/json"


def test_graphql_sets_non_default_user_agent(capture_request):
    backend = runpod_client.RealBackend("secret-key")
    backend._graphql("{ gpuTypes { id } }")

    req = capture_request["req"]
    ua = _user_agent(req)
    assert ua, "GraphQL request must carry a User-Agent header"
    assert "python-urllib" not in ua.lower()
    assert ua == runpod_client.USER_AGENT


def test_user_agent_constant_is_not_default():
    assert "python-urllib" not in runpod_client.USER_AGENT.lower()
