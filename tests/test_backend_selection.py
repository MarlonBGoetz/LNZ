"""No-silent-fallback backend/inference selection (offline).

When RUNPOD_API_KEY is set and OVERWATCH_FAKE != '1' the real backend/inference
must be used and any transport failure must RAISE rather than silently falling
back to the fake implementation. When OVERWATCH_FAKE=='1' (or no key) the fake
implementation is returned. No test touches the network or imports runpod/httpx.
"""

from __future__ import annotations

import pytest

from overwatch import runpod_client
from overwatch.datagen import driver


@pytest.fixture(autouse=True)
def _clear_injected():
    runpod_client.set_backend(None)
    yield
    runpod_client.set_backend(None)


# ----------------------------------------------------------------------
# runpod_client.get_backend
# ----------------------------------------------------------------------
def test_fake_env_returns_fake_backend(monkeypatch):
    monkeypatch.setenv("OVERWATCH_FAKE", "1")
    monkeypatch.setenv("RUNPOD_API_KEY", "irrelevant-when-fake")
    backend = runpod_client.get_backend()
    assert isinstance(backend, runpod_client.FakeBackend)


def test_no_key_returns_fake_backend(monkeypatch):
    monkeypatch.delenv("OVERWATCH_FAKE", raising=False)
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    backend = runpod_client.get_backend()
    assert isinstance(backend, runpod_client.FakeBackend)


def test_key_set_returns_real_backend(monkeypatch):
    monkeypatch.delenv("OVERWATCH_FAKE", raising=False)
    monkeypatch.setenv("RUNPOD_API_KEY", "sk-live-xxxx")
    backend = runpod_client.get_backend()
    assert isinstance(backend, runpod_client.RealBackend)
    assert not isinstance(backend, runpod_client.FakeBackend)


def test_real_backend_transport_failure_raises_not_fake(monkeypatch):
    """A RealBackend whose construction fails must RAISE, not return a fake."""
    monkeypatch.delenv("OVERWATCH_FAKE", raising=False)
    monkeypatch.setenv("RUNPOD_API_KEY", "sk-live-xxxx")

    boom = RuntimeError("simulated transport/construction failure")

    def _explode(self, api_key):  # noqa: ANN001
        raise boom

    monkeypatch.setattr(runpod_client.RealBackend, "__init__", _explode)
    with pytest.raises(RuntimeError):
        runpod_client.get_backend()


def test_real_backend_requires_api_key():
    with pytest.raises(RuntimeError):
        runpod_client.RealBackend("")


def test_backend_selection_never_prints_key(monkeypatch, capsys):
    monkeypatch.delenv("OVERWATCH_FAKE", raising=False)
    monkeypatch.setenv("RUNPOD_API_KEY", "sk-live-SECRET-VALUE")
    runpod_client.get_backend()
    captured = capsys.readouterr()
    assert "SECRET" not in captured.err
    assert "SECRET" not in captured.out
    assert "RealBackend" in captured.err


# ----------------------------------------------------------------------
# datagen.driver.get_inference
# ----------------------------------------------------------------------
def test_get_inference_fake_env(monkeypatch):
    monkeypatch.setenv("OVERWATCH_FAKE", "1")
    monkeypatch.setenv("RUNPOD_API_KEY", "irrelevant-when-fake")
    inf = driver.get_inference()
    assert isinstance(inf, driver.FakeInference)


def test_get_inference_no_silent_fallback(monkeypatch):
    """Key present + not fake: a failing real inference must RAISE, not fake."""
    monkeypatch.delenv("OVERWATCH_FAKE", raising=False)
    monkeypatch.setenv("RUNPOD_API_KEY", "sk-live-xxxx")

    def _explode(self, *, endpoint_id, api_key):  # noqa: ANN001
        raise RuntimeError("simulated real inference construction failure")

    monkeypatch.setattr(driver._RealServerlessInference, "__init__", _explode)
    with pytest.raises(RuntimeError):
        driver.get_inference({})


def test_get_inference_injected_wins(monkeypatch):
    monkeypatch.delenv("OVERWATCH_FAKE", raising=False)
    monkeypatch.setenv("RUNPOD_API_KEY", "sk-live-xxxx")
    sentinel = object()
    assert driver.get_inference({}, inference=sentinel) is sentinel
