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


def test_graphql_sends_key_via_auth_header_not_url(capture_request):
    """The GraphQL key must travel in an Authorization: Bearer header only.

    Regression guard: the key must never be appended to the URL as a
    ``?api_key=`` query string, where it would leak into logs/referrers.
    """
    backend = runpod_client.RealBackend("secret-key")
    backend._graphql("{ gpuTypes { id } }")

    req = capture_request["req"]
    # (a) key delivered via the Bearer header, exactly like REST _request.
    assert req.get_header("Authorization") == "Bearer secret-key"
    # (b) key is absent from the URL; no query string smuggling the key.
    assert "secret-key" not in req.full_url
    assert "?api_key=" not in req.full_url
    assert req.full_url == runpod_client.GRAPHQL_URL
    # Content negotiation headers preserved alongside the auth change.
    assert req.get_header("Content-type") == "application/json"
    assert req.get_header("Accept") == "application/json"


def test_user_agent_constant_is_not_default():
    assert "python-urllib" not in runpod_client.USER_AGENT.lower()
