from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest
from lnbits.core.models import Payment

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


def _settlement_payment(*, created: datetime, updated: datetime) -> Payment:
    return Payment(
        checking_id="c" * 64,
        payment_hash="b" * 64,
        wallet_id="wallet123",
        amount=123000,
        fee=0,
        bolt11="lnbc1example",
        status="success",
        time=created,
        updated_at=updated,
    )


def _patch_payment_reads(monkeypatch, payments: list[Payment], permission: str) -> None:
    async def fake_get_nwc(*args, **kwargs):
        return SimpleNamespace(wallet="wallet123", get_permissions=lambda: [permission])

    async def fake_get_wallet_payment(*args, **kwargs):
        return payments[0]

    async def fake_get_payments(*args, **kwargs):
        return payments

    monkeypatch.setattr(tasks, "get_nwc", fake_get_nwc)
    monkeypatch.setattr(tasks, "get_wallet_payment", fake_get_wallet_payment)
    monkeypatch.setattr(tasks, "get_payments", fake_get_payments)
    monkeypatch.setattr(
        tasks,
        "bolt11_decode",
        lambda *args, **kwargs: SimpleNamespace(
            description="test 123", description_hash=None, date=0
        ),
    )


@pytest.mark.asyncio
async def test_lookup_invoice_settled_at_is_the_state_change_not_creation(monkeypatch):
    created = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    settled = created + timedelta(days=3)
    _patch_payment_reads(
        monkeypatch, [_settlement_payment(created=created, updated=settled)], "lookup"
    )

    [(res, error, _)] = await tasks._on_lookup_invoice(
        cast(Any, None), "a" * 64, {"params": {"payment_hash": "b" * 64}}
    )

    assert error is None
    assert isinstance(res, dict)
    assert res["created_at"] == int(created.timestamp())
    assert res["settled_at"] == int(settled.timestamp())


@pytest.mark.asyncio
async def test_list_transactions_settled_at_is_the_state_change_not_creation(
    monkeypatch,
):
    created = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    settled = created + timedelta(days=3)
    _patch_payment_reads(
        monkeypatch, [_settlement_payment(created=created, updated=settled)], "history"
    )

    [(res, error, _)] = await tasks._on_list_transactions(
        cast(Any, None), "a" * 64, {"params": {"limit": 10}}
    )

    assert error is None
    assert isinstance(res, dict)
    transaction = res["transactions"][0]
    assert transaction["created_at"] == int(created.timestamp())
    assert transaction["settled_at"] == int(settled.timestamp())
