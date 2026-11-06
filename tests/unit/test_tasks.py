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


async def _make_invoice(monkeypatch, backend_preimage: str | None) -> dict:
    async def fake_get_nwc(*args, **kwargs):
        return SimpleNamespace(wallet="wallet123", get_permissions=lambda: ["invoice"])

    async def fake_create_invoice(*args, **kwargs):
        return SimpleNamespace(payment_hash="b" * 64, bolt11="lnbc1example")

    async def fake_check_transaction_status(wallet_id, payment_hash):
        return SimpleNamespace(preimage=backend_preimage)

    monkeypatch.setattr(tasks, "get_nwc", fake_get_nwc)
    monkeypatch.setattr(tasks, "create_invoice", fake_create_invoice)
    monkeypatch.setattr(
        tasks, "check_transaction_status", fake_check_transaction_status
    )

    [(res, error, _)] = await tasks._on_make_invoice(
        cast(Any, None), "a" * 64, {"params": {"amount": 123000, "description": "test"}}
    )
    assert error is None
    assert isinstance(res, dict)
    return res


@pytest.mark.asyncio
async def test_make_invoice_omits_preimage_when_backend_has_none(monkeypatch):
    """The invoice is unpaid: a zero-filled preimage is not a verifiable receipt."""
    res = await _make_invoice(monkeypatch, backend_preimage=None)

    assert "preimage" not in res
    assert res["payment_hash"] == "b" * 64
    assert res["amount"] == 123000


@pytest.mark.asyncio
async def test_make_invoice_keeps_preimage_the_backend_returns(monkeypatch):
    res = await _make_invoice(monkeypatch, backend_preimage="d" * 64)

    assert res["preimage"] == "d" * 64
