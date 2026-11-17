from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from lnbits.db import Database
from lnbits.settings import settings
from sqlalchemy import event

from ... import crud, migrations, models

PUBKEY = "a" * 64
NOW = 1_800_000_000


@pytest_asyncio.fixture
async def spending(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "lnbits_data_folder", str(tmp_path))
    db = Database("ext_nwcprovider")

    @event.listens_for(db.engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    clock = SimpleNamespace(now=NOW)
    test_time = SimpleNamespace(time=lambda: clock.now)
    monkeypatch.setattr(crud, "db", db)
    monkeypatch.setattr(crud, "time", test_time)
    monkeypatch.setattr(models, "time", test_time)

    async def run(action):
        return await action()

    monkeypatch.setattr(crud, "enqueue", run)
    try:
        await migrations.m001_initial(db)
        await migrations.m005_key_last_used(db)
        await crud.create_nwc(
            models.CreateNWCKey(
                pubkey=PUBKEY,
                wallet="wallet123",
                description="test",
                expires_at=NOW + 100,
                permissions=["pay"],
                budgets=[
                    models.NWCNewBudget(
                        budget_msats=1500, refresh_window=10, created_at=NOW
                    )
                ],
            )
        )
        yield clock
    finally:
        await db.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["deleted", "expired"])
@pytest.mark.parametrize("when", ["queued", "budget_lookup"])
async def test_tracked_spend_rechecks_connection(spending, monkeypatch, state, when):
    async def change_connection():
        if state == "deleted":
            await crud.delete_nwc(models.DeleteNWC(pubkey=PUBKEY, wallet="wallet123"))
        else:
            spending.now = NOW + 100

    if when == "queued":

        async def run(action):
            await change_connection()
            return await action()

        monkeypatch.setattr(crud, "enqueue", run)
    else:
        get_budgets = crud.get_budgets_nwc

        async def get_changed_budgets(data):
            await change_connection()
            return await get_budgets(data)

        monkeypatch.setattr(crud, "get_budgets_nwc", get_changed_budgets)

    action = AsyncMock(return_value="paid")
    result = await crud.tracked_spend_nwc(
        models.TrackedSpendNWC(pubkey=PUBKEY, amount_msats=1000), action
    )

    assert result == (False, None)
    action.assert_not_awaited()


@pytest.mark.asyncio
async def test_tracked_spend_keeps_budget_check_and_record_in_same_cycle(
    spending, monkeypatch
):
    await crud.db.execute(
        """
        INSERT INTO nwcprovider.spent (pubkey, amount_msats, created_at)
        VALUES (:pubkey, 1500, :created_at)
        """,
        {"pubkey": PUBKEY, "created_at": NOW},
    )
    spending.now = NOW + 9
    get_budgets = crud.get_budgets_nwc

    async def get_next_cycle_budgets(data):
        budgets = await get_budgets(data)
        spending.now = NOW + 10
        return budgets

    monkeypatch.setattr(crud, "get_budgets_nwc", get_next_cycle_budgets)
    action = AsyncMock(return_value="paid")
    spend = models.TrackedSpendNWC(pubkey=PUBKEY, amount_msats=1000)

    assert await crud.tracked_spend_nwc(spend, action) == (False, None)
    assert await crud.tracked_spend_nwc(spend, action) == (True, "paid")
    assert await crud.tracked_spend_nwc(spend, action) == (False, None)
    action.assert_awaited_once()
    budgets = await crud.get_budgets_nwc(
        models.GetBudgetsNWC(pubkey=PUBKEY, calculate_spent=True)
    )
    assert budgets[0].used_budget_msats == 1000
