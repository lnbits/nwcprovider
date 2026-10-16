from types import SimpleNamespace
from typing import Any, cast

import pytest

from ... import tasks


@pytest.mark.asyncio
async def test_process_invoice_returns_payment_failed_on_failed_status(monkeypatch):
    async def fake_tracked_spend_nwc(*args, **kwargs):
        return True, "a" * 64

    async def fake_check_transaction_status(wallet_id: str, payment_hash: str):
        return SimpleNamespace(success=False, failed=True)

    monkeypatch.setattr(tasks, "tracked_spend_nwc", fake_tracked_spend_nwc)
    monkeypatch.setattr(
        tasks, "check_transaction_status", fake_check_transaction_status
    )

    result = await tasks._process_invoice(
        wallet_id="wallet123",
        pubkey="a" * 64,
        invoice="lnbc1example",
        amount_msats=1000,
        description="test",
    )

    assert result["error"]["code"] == "PAYMENT_FAILED"
    assert result["error"]["message"] == "Payment failed."
    assert result["in_budget"] is True


@pytest.mark.asyncio
async def test_process_invoice_backs_off_pending_payment_polling_to_configured_max(
    monkeypatch,
):
    async def fake_tracked_spend_nwc(*args, **kwargs):
        return True, "a" * 64

    pending = SimpleNamespace(success=False, failed=False)
    statuses = iter(
        [pending] * 8
        + [
            SimpleNamespace(
                success=True,
                failed=False,
                preimage="b" * 64,
                fee_msat=10,
                paid=True,
            )
        ]
    )

    async def fake_check_transaction_status(wallet_id: str, payment_hash: str):
        return next(statuses)

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float):
        sleep_calls.append(delay)

    monkeypatch.setattr(tasks, "tracked_spend_nwc", fake_tracked_spend_nwc)
    monkeypatch.setattr(
        tasks, "check_transaction_status", fake_check_transaction_status
    )
    monkeypatch.setattr(tasks.asyncio, "sleep", fake_sleep)

    result = await tasks._process_invoice(
        wallet_id="wallet123",
        pubkey="a" * 64,
        invoice="lnbc1example",
        amount_msats=1000,
        description="test",
    )

    assert sleep_calls == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]
    assert result["preimage"] == "b" * 64
    assert result["fee_msats"] == 10
    assert result["paid"] is True


async def _list_transactions_query(monkeypatch, params: dict) -> dict:
    """Run `list_transactions` and return the kwargs handed to `get_payments`."""
    captured: dict = {}

    async def fake_get_nwc(*args, **kwargs):
        return SimpleNamespace(wallet="wallet123", get_permissions=lambda: ["history"])

    async def fake_get_payments(*args, **kwargs):
        captured.update(kwargs)
        return []

    async def fake_get_wallet_payment(*args, **kwargs):
        return None

    monkeypatch.setattr(tasks, "get_nwc", fake_get_nwc)
    monkeypatch.setattr(tasks, "get_payments", fake_get_payments)
    monkeypatch.setattr(tasks, "get_wallet_payment", fake_get_wallet_payment)

    [(res, error, _)] = await tasks._on_list_transactions(
        cast(Any, None), "a" * 64, {"params": params}
    )

    assert error is None
    assert res == {"transactions": []}
    return captured


@pytest.mark.asyncio
async def test_list_transactions_applies_the_until_bound(monkeypatch):
    """`until` has to reach the query: it was built and then discarded."""
    captured = await _list_transactions_query(monkeypatch, {"until": 1791115200})

    filters = captured["filters"]
    assert filters.where([]) == "WHERE (time <= :tuntil)"
    # the raw unix timestamp, as `get_payments_paginated` passes `since`: the
    # placeholder wraps it per database, a coerced datetime would not bind
    assert filters.values({}) == {"tuntil": 1791115200}
