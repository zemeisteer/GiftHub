"""Payment webhooks must fail closed when the provider secret is not configured.

With an empty secret the Click signature and the Payme Basic credentials are
computable by anyone, so a forged "payment succeeded" call would credit a wallet.
"""

import base64
import hashlib

import pytest

from app.core.config import settings
from app.services.payments.click import click_provider
from app.services.payments.payme import payme_provider


@pytest.fixture(autouse=True)
def _production_like(monkeypatch):
    # "test" has deliberate shortcuts; check the behaviour every real deployment gets.
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")


def _click_payload(secret: str, action: int = 0) -> dict:
    base = {
        "click_trans_id": 111,
        "service_id": 1,
        "merchant_trans_id": "42",
        "amount": "25000.0",
        "action": action,
        "sign_time": "2026-11-17 12:00:00",
    }
    if action == 1:
        base["merchant_prepare_id"] = 7
        raw = f"111{1}{secret}42{7}25000.0{action}{base['sign_time']}"
    else:
        raw = f"111{1}{secret}4225000.0{action}{base['sign_time']}"
    base["sign_string"] = hashlib.md5(raw.encode("utf-8")).hexdigest()
    return base


def _basic(login: str, key: str) -> str:
    return "Basic " + base64.b64encode(f"{login}:{key}".encode("utf-8")).decode("utf-8")


@pytest.mark.parametrize("empty", ["", None, "   "])
@pytest.mark.parametrize("action", [0, 1])
def test_click_rejects_signature_forged_with_empty_secret(monkeypatch, empty, action):
    monkeypatch.setattr(settings, "CLICK_SECRET_KEY", empty)
    assert click_provider.verify_signature(_click_payload("", action)) is False


@pytest.mark.parametrize("empty", ["", None, "   "])
def test_payme_rejects_empty_credentials_when_secret_unset(monkeypatch, empty):
    monkeypatch.setattr(settings, "PAYME_SECRET_KEY", empty)
    assert payme_provider.verify_auth(_basic("Paycom", "")) is False


def test_click_accepts_valid_signature_when_secret_set(monkeypatch):
    monkeypatch.setattr(settings, "CLICK_SECRET_KEY", "real_click_secret")
    assert click_provider.verify_signature(_click_payload("real_click_secret", 0)) is True
    assert click_provider.verify_signature(_click_payload("real_click_secret", 1)) is True


def test_click_rejects_wrong_signature_when_secret_set(monkeypatch):
    monkeypatch.setattr(settings, "CLICK_SECRET_KEY", "real_click_secret")
    assert click_provider.verify_signature(_click_payload("another_secret", 0)) is False


def test_payme_accepts_valid_credentials_when_secret_set(monkeypatch):
    monkeypatch.setattr(settings, "PAYME_SECRET_KEY", "real_payme_secret")
    assert payme_provider.verify_auth(_basic("Paycom", "real_payme_secret")) is True


def test_payme_rejects_wrong_credentials_when_secret_set(monkeypatch):
    monkeypatch.setattr(settings, "PAYME_SECRET_KEY", "real_payme_secret")
    assert payme_provider.verify_auth(_basic("Paycom", "")) is False
    assert payme_provider.verify_auth(_basic("Paycom", "guess")) is False
    assert payme_provider.verify_auth(_basic("attacker", "real_payme_secret")) is False
