from types import SimpleNamespace

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


def _stub_make_invoice(monkeypatch, captured: dict):
    async def fake_get_nwc(*args, **kwargs):
        return SimpleNamespace(wallet="wallet123")

    async def fake_check(nwc, method):
        return None

    async def fake_create_invoice(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(payment_hash="b" * 64, bolt11="lnbc1example")

    async def fake_check_transaction_status(wallet_id: str, payment_hash: str):
        return SimpleNamespace(preimage=None)

    monkeypatch.setattr(tasks, "get_nwc", fake_get_nwc)
    monkeypatch.setattr(tasks, "_check", fake_check)
    monkeypatch.setattr(tasks, "create_invoice", fake_create_invoice)
    monkeypatch.setattr(
        tasks, "check_transaction_status", fake_check_transaction_status
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        # rust-nostr, Alby JS SDK: unused optional fields are omitted
        {"amount": 21000},
        # Amethyst: unused optional fields are sent as explicit null
        {
            "amount": 21000,
            "description": None,
            "description_hash": None,
            "expiry": None,
        },
    ],
)
async def test_make_invoice_accepts_absent_or_null_optional_params(monkeypatch, params):
    captured: dict = {}
    _stub_make_invoice(monkeypatch, captured)

    [(result, error, _)] = await tasks._on_make_invoice(
        SimpleNamespace(), "a" * 64, {"params": params}
    )

    assert error is None
    assert result["invoice"] == "lnbc1example"
    assert result["description"] == ""
    assert "expires_at" not in result
    assert captured["memo"] == ""
    assert captured["description_hash"] is None
    assert captured["unhashed_description"] is None
    assert captured["expiry"] is None


@pytest.mark.asyncio
async def test_make_invoice_passes_description_and_expiry_through(monkeypatch):
    captured: dict = {}
    _stub_make_invoice(monkeypatch, captured)

    [(result, error, _)] = await tasks._on_make_invoice(
        SimpleNamespace(),
        "a" * 64,
        {"params": {"amount": 21000, "description": "coffee", "expiry": 600}},
    )

    assert error is None
    assert captured["memo"] == "coffee"
    assert captured["unhashed_description"] == b"coffee"
    assert captured["expiry"] == 600
    assert result["description"] == "coffee"
    assert "expires_at" in result
