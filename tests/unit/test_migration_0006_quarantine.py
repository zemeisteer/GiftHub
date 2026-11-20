"""0006 quarantines in-flight wallet-paid gift orders from the old (Fragment) catalog flow."""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0006_telegram_gifts.py"


@pytest.fixture(scope="module")
def quarantine_sql():
    spec = importlib.util.spec_from_file_location("migration_0006", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.QUARANTINE_LEGACY_GIFTS_SQL


def _db():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE orders (id INTEGER PRIMARY KEY, product_type TEXT, status TEXT, fulfillment_status TEXT, "
        "fulfillment_error TEXT, recipient_user_id BIGINT)"
    )
    return conn


QUARANTINED = ["pending", "processing", "retry_scheduled", "waiting_payment", "failed"]


@pytest.mark.parametrize("fulfillment_status", QUARANTINED)
def test_in_flight_paid_legacy_gift_is_quarantined(quarantine_sql, fulfillment_status):
    conn = _db()
    conn.execute(
        "INSERT INTO orders (id, product_type, status, fulfillment_status) VALUES (1, 'gift', 'paid', ?)",
        (fulfillment_status,),
    )
    conn.execute(quarantine_sql)
    status, error = conn.execute("SELECT fulfillment_status, fulfillment_error FROM orders").fetchone()
    assert status == "manual_review"
    assert error


@pytest.mark.parametrize(
    "row",
    [
        ("gift", "completed", "fulfilled", None),
        ("gift", "refunded", "failed", None),  # already refunded: nothing to review
        ("gift", "paid", "fulfilled", None),
        ("gift", "paid", "pending", 777),  # new-flow order (has a numeric recipient)
        ("stars", "paid", "pending", None),
        ("premium", "paid", "failed", None),
    ],
)
def test_other_orders_are_untouched(quarantine_sql, row):
    conn = _db()
    conn.execute(
        "INSERT INTO orders (id, product_type, status, fulfillment_status, recipient_user_id) VALUES (1, ?, ?, ?, ?)",
        row,
    )
    conn.execute(quarantine_sql)
    assert conn.execute("SELECT fulfillment_status, fulfillment_error FROM orders").fetchone() == (row[2], None)
