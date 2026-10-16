from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest
from lnbits.core.models import Payment

from ... import tasks


def _payment(
    status: str,
    amount: int,
    expires_in: int | None = None,
    preimage: str | None = None,
) -> Payment:
    expiry = (
        datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        if expires_in is not None
        else None
    )
    return Payment(
        checking_id="c" * 64,
        payment_hash="b" * 64,
        wallet_id="wallet123",
        amount=amount,
        fee=0,
        bolt11="lnbc1example",
        status=status,
        expiry=expiry,
        preimage=preimage,
    )


def _patch_nwc(monkeypatch, payments: list[Payment], permission: str) -> None:
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


async def _lookup_invoice(monkeypatch, payments: list[Payment]) -> dict:
    _patch_nwc(monkeypatch, payments, permission="lookup")
    [(res, error, _)] = await tasks._on_lookup_invoice(
        cast(Any, None), "a" * 64, {"params": {"payment_hash": "b" * 64}}
    )
    assert error is None
    assert isinstance(res, dict)
    return res


async def _list_transactions(monkeypatch, payments: list[Payment]) -> dict:
    _patch_nwc(monkeypatch, payments, permission="history")
    [(res, error, _)] = await tasks._on_list_transactions(
        cast(Any, None), "a" * 64, {"params": {"limit": 10}}
    )
    assert error is None
    assert isinstance(res, dict)
    return res


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


@pytest.mark.parametrize(
    "status,amount,expires_in,expected",
    [
        ("success", 123000, 3600, "settled"),  # settled incoming invoice
        ("success", -123000, None, "settled"),  # settled outgoing payment
        ("pending", 123000, 3600, "pending"),  # unpaid incoming invoice
        ("pending", -123000, None, "pending"),  # in-flight outgoing payment
        ("failed", 123000, -3600, "expired"),  # expired incoming invoice
        ("failed", 123000, 3600, "failed"),  # canceled incoming payment
        ("failed", -123000, -3600, "failed"),  # failed outgoing payment
    ],
)
def test_nip47_state(status, amount, expires_in, expected):
    payment = _payment(status, amount, expires_in)
    assert tasks._nip47_state(payment) == expected


def test_failed_incoming_invoice_is_not_reported_as_settled():
    """`is_settled = not payment.pending` was true for a failed payment too."""
    payment = _payment("failed", 123000, expires_in=-3600)
    assert not payment.pending
    assert tasks._nip47_state(payment) == "expired"


@pytest.mark.asyncio
async def test_lookup_invoice_expired_has_no_settlement_fields(monkeypatch):
    res = await _lookup_invoice(monkeypatch, [_payment("failed", 123000, -3600)])

    assert res["state"] == "expired"
    assert "settled_at" not in res
    assert "preimage" not in res


@pytest.mark.asyncio
async def test_lookup_invoice_pending_has_no_settlement_fields(monkeypatch):
    res = await _lookup_invoice(monkeypatch, [_payment("pending", 123000, 3600)])

    assert res["state"] == "pending"
    assert "settled_at" not in res
    assert "preimage" not in res


@pytest.mark.asyncio
async def test_lookup_invoice_settled_keeps_settlement_fields(monkeypatch):
    payment = _payment("success", 123000, expires_in=3600, preimage="d" * 64)
    res = await _lookup_invoice(monkeypatch, [payment])

    assert res["state"] == "settled"
    assert res["settled_at"] == int(payment.time.timestamp())
    assert res["preimage"] == "d" * 64


@pytest.mark.asyncio
async def test_list_transactions_states(monkeypatch):
    pending_outgoing = _payment("pending", -123000)
    settled_incoming = _payment("success", 123000, preimage="d" * 64)
    res = await _list_transactions(monkeypatch, [pending_outgoing, settled_incoming])

    transactions = res["transactions"]
    assert [tx["state"] for tx in transactions] == ["pending", "settled"]
    assert "settled_at" not in transactions[0]
    assert "preimage" not in transactions[0]
    assert transactions[1]["settled_at"] == int(settled_incoming.time.timestamp())
    assert transactions[1]["preimage"] == "d" * 64
