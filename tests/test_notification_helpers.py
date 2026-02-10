"""
Test notification helper logic: permission filtering, data structures.
Mocks lnbits to run standalone.
"""

import asyncio
import json
import sys
import os
import types
from datetime import datetime, timezone

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

# ── Mock external dependencies BEFORE any project imports ──

# Mock loguru
loguru_mod = types.ModuleType("loguru")
class _MockLogger:
    def debug(self, *a, **kw): pass
    def info(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
    def error(self, *a, **kw): pass
    def exception(self, *a, **kw): pass
loguru_mod.logger = _MockLogger()
sys.modules["loguru"] = loguru_mod

# Mock pydantic (needed by models.py)
pydantic_mod = types.ModuleType("pydantic")
class BaseModel:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
pydantic_mod.BaseModel = BaseModel
sys.modules["pydantic"] = pydantic_mod

# Mock all lnbits modules
lnbits = types.ModuleType("lnbits")
lnbits.helpers = types.ModuleType("lnbits.helpers")
lnbits.helpers.encrypt_internal_message = lambda x: x
lnbits.settings = types.ModuleType("lnbits.settings")
lnbits.tasks = types.ModuleType("lnbits.tasks")
lnbits.tasks.register_invoice_listener = lambda q, n: None
lnbits.core = types.ModuleType("lnbits.core")
lnbits.core.crud = types.ModuleType("lnbits.core.crud")
lnbits.core.models = types.ModuleType("lnbits.core.models")
lnbits.core.services = types.ModuleType("lnbits.core.services")
lnbits.db = types.ModuleType("lnbits.db")
lnbits.exceptions = types.ModuleType("lnbits.exceptions")
lnbits.wallets = types.ModuleType("lnbits.wallets")
lnbits.wallets.base = types.ModuleType("lnbits.wallets.base")

class MockSettings:
    port = 5000
    lnbits_running = True
    lnbits_site_title = "TestLNbits"

lnbits.settings.settings = MockSettings()

class MockFilters:
    def where(self, x): pass
    def values(self, x): pass

lnbits.db.Filters = MockFilters

class MockPaymentError(Exception):
    def __init__(self, message="", status="failed"):
        self.message = message
        self.status = status

lnbits.exceptions.PaymentError = MockPaymentError

# Mock lnbits.core.crud functions
async def _mock_get_payments(*a, **kw): return []
async def _mock_get_wallet(*a, **kw): return None
async def _mock_get_wallet_payment(*a, **kw): return None
lnbits.core.crud.get_payments = _mock_get_payments
lnbits.core.crud.get_wallet = _mock_get_wallet
lnbits.core.crud.get_wallet_payment = _mock_get_wallet_payment

# Mock lnbits.core.services functions
async def _mock_svc(*a, **kw): return None
lnbits.core.services.check_transaction_status = _mock_svc
lnbits.core.services.create_invoice = _mock_svc
lnbits.core.services.pay_invoice = _mock_svc

# Mock lnbits.wallets.base.PaymentStatus
class MockPaymentStatus:
    def __init__(self, paid=False):
        self.paid = paid
lnbits.wallets.base.PaymentStatus = MockPaymentStatus

# Mock lnbits.db.Database
class MockDatabase:
    def __init__(self, *a, **kw): pass
lnbits.db.Database = MockDatabase

# Mock Payment class
class MockPayment:
    def __init__(self, **kwargs):
        self.bolt11 = kwargs.get("bolt11", "lnbc50n1...")
        self.pending = kwargs.get("pending", False)
        self.payment_hash = kwargs.get("payment_hash", "abc123")
        self.memo = kwargs.get("memo", "test payment")
        self.preimage = kwargs.get("preimage", "pre123")
        self.is_out = kwargs.get("is_out", False)
        self.is_in = kwargs.get("is_in", True)
        self.msat = kwargs.get("msat", 5000)
        self.fee = kwargs.get("fee", 0)
        self.wallet_id = kwargs.get("wallet_id", "wallet1")
        self.extra = kwargs.get("extra", {})
        self.time = kwargs.get("time", datetime(2023, 11, 14, tzinfo=timezone.utc))
        self.expiry = kwargs.get("expiry", None)
        self.success = not self.pending
        self.failed = False
        self.is_expired = False

lnbits.core.models.Payment = MockPayment

# Register all lnbits modules
for name, mod in [
    ("lnbits", lnbits),
    ("lnbits.helpers", lnbits.helpers),
    ("lnbits.settings", lnbits.settings),
    ("lnbits.tasks", lnbits.tasks),
    ("lnbits.core", lnbits.core),
    ("lnbits.core.crud", lnbits.core.crud),
    ("lnbits.core.models", lnbits.core.models),
    ("lnbits.core.services", lnbits.core.services),
    ("lnbits.db", lnbits.db),
    ("lnbits.exceptions", lnbits.exceptions),
    ("lnbits.wallets", lnbits.wallets),
    ("lnbits.wallets.base", lnbits.wallets.base),
]:
    sys.modules[name] = mod

# Mock bolt11
bolt11_mod = types.ModuleType("bolt11")

class MockDecoded:
    def __init__(self):
        self.date = 1700000000
        self.description = "test"
        self.description_hash = None
        self.amount_msat = 5000
        self.payment_hash = "abc123"

bolt11_mod.decode = lambda x: MockDecoded()
sys.modules["bolt11"] = bolt11_mod

# ── Set up the nwcprovider package so relative imports in tasks.py work ──

# Create the package module
nwcprovider_pkg = types.ModuleType("nwcprovider")
nwcprovider_pkg.__path__ = [PROJECT_DIR]
nwcprovider_pkg.__package__ = "nwcprovider"
sys.modules["nwcprovider"] = nwcprovider_pkg

# Import submodules that tasks.py needs (they're importable from sys.path)
import paranoia as _paranoia
import execution_queue as _execution_queue
import nwcp as _nwcp
import permission as _permission

# Register as package submodules
sys.modules["nwcprovider.paranoia"] = _paranoia
sys.modules["nwcprovider.nwcp"] = _nwcp
sys.modules["nwcprovider.permission"] = _permission
sys.modules["nwcprovider.execution_queue"] = _execution_queue
nwcprovider_pkg.paranoia = _paranoia
nwcprovider_pkg.nwcp = _nwcp
nwcprovider_pkg.permission = _permission
nwcprovider_pkg.execution_queue = _execution_queue

# Import models.py (needs pydantic mock above, no relative imports)
import models as _models
sys.modules["nwcprovider.models"] = _models
nwcprovider_pkg.models = _models

# Import crud.py via importlib (it uses relative imports)
import importlib

def _load_as_submodule(name, filename):
    spec = importlib.util.spec_from_file_location(
        f"nwcprovider.{name}", os.path.join(PROJECT_DIR, filename),
        submodule_search_locations=[],
    )
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "nwcprovider"
    sys.modules[f"nwcprovider.{name}"] = mod
    setattr(nwcprovider_pkg, name, mod)
    spec.loader.exec_module(mod)
    return mod

_crud = _load_as_submodule("crud", "crud.py")
_tasks_mod = _load_as_submodule("tasks", "tasks.py")

# Aliases for convenience
tasks = _tasks_mod
NWCServiceProvider = _nwcp.NWCServiceProvider
nwc_permissions = _permission.nwc_permissions


# ── Mock NWCKey for tests ──

class MockNWCKey:
    def __init__(self, pubkey, wallet, permissions_str):
        self.pubkey = pubkey
        self.wallet = wallet
        self.permissions = permissions_str

    def get_permissions(self):
        return self.permissions.split(" ")


# ── Tests ──

def test_permission_includes_notifications():
    """notifications permission exists with empty methods list."""
    assert "notifications" in nwc_permissions
    perm = nwc_permissions["notifications"]
    assert perm["methods"] == []
    assert perm["default"] is True
    assert perm["name"] == "Receive payment notifications"
    print("  PASS: notifications permission exists")


def test_build_transaction_data_settled():
    """_build_transaction_data for a settled incoming payment."""
    payment = MockPayment(
        pending=False,
        is_out=False,
        is_in=True,
        msat=5000,
        fee=0,
        payment_hash="abc123",
        preimage="pre123",
        memo="coffee",
    )
    result = tasks._build_transaction_data(payment)

    assert result["type"] == "incoming"
    assert result["state"] == "settled"
    assert result["amount"] == 5000
    assert result["payment_hash"] == "abc123"
    assert result["preimage"] == "pre123"
    assert result["settled_at"] is not None
    assert result["fees_paid"] == 0
    assert "metadata" in result
    print("  PASS: _build_transaction_data settled incoming")


def test_build_transaction_data_pending():
    """_build_transaction_data for a pending outgoing payment."""
    payment = MockPayment(
        pending=True,
        is_out=True,
        is_in=False,
        msat=-3000,
        fee=-10,
        payment_hash="def456",
        preimage=None,
    )
    result = tasks._build_transaction_data(payment)

    assert result["type"] == "outgoing"
    assert result["state"] == "pending"
    assert result["amount"] == 3000
    assert result["preimage"] is None, "Pending outgoing should have no preimage"
    assert result["settled_at"] is None
    print("  PASS: _build_transaction_data pending outgoing")


async def test_send_notification_to_wallet_filters_permissions():
    """_send_notification_to_wallet only sends to keys with notifications permission."""
    sp = NWCServiceProvider(
        "d7b5232fba0e02e32cfe26f20cdf2c803b27ecd81052c2dd5d17e5e1a333fe58",
        "ws://localhost:7777",
    )

    sent_to = []

    async def mock_send_notification(pubkey, ntype, notification):
        sent_to.append(pubkey)

    sp.send_notification = mock_send_notification

    key_with_notif1 = MockNWCKey("pub_a", "wallet1", "pay notifications")
    key_with_notif2 = MockNWCKey("pub_b", "wallet1", "invoice notifications")
    key_without_notif = MockNWCKey("pub_c", "wallet1", "pay invoice")

    original_get_wallet_nwcs = tasks.get_wallet_nwcs

    async def mock_get_wallet_nwcs(data):
        return [key_with_notif1, key_with_notif2, key_without_notif]

    tasks.get_wallet_nwcs = mock_get_wallet_nwcs

    try:
        await tasks._send_notification_to_wallet(
            sp, "wallet1", "payment_received", {"amount": 1000}
        )

        assert "pub_a" in sent_to, "Key with notifications perm should receive"
        assert "pub_b" in sent_to, "Key with notifications perm should receive"
        assert "pub_c" not in sent_to, "Key without notifications perm should NOT receive"
        assert len(sent_to) == 2
        print("  PASS: permission filtering works")
    finally:
        tasks.get_wallet_nwcs = original_get_wallet_nwcs


async def test_send_notification_excludes_pubkey():
    """_send_notification_to_wallet skips exclude_pubkey."""
    sp = NWCServiceProvider(
        "d7b5232fba0e02e32cfe26f20cdf2c803b27ecd81052c2dd5d17e5e1a333fe58",
        "ws://localhost:7777",
    )

    sent_to = []

    async def mock_send_notification(pubkey, ntype, notification):
        sent_to.append(pubkey)

    sp.send_notification = mock_send_notification

    key1 = MockNWCKey("pub_sender", "wallet1", "pay notifications")
    key2 = MockNWCKey("pub_observer", "wallet1", "notifications")

    original_get_wallet_nwcs = tasks.get_wallet_nwcs

    async def mock_get_wallet_nwcs(data):
        return [key1, key2]

    tasks.get_wallet_nwcs = mock_get_wallet_nwcs

    try:
        await tasks._send_notification_to_wallet(
            sp, "wallet1", "payment_sent", {"amount": 1000},
            exclude_pubkey="pub_sender",
        )

        assert "pub_sender" not in sent_to, "Excluded pubkey should not receive"
        assert "pub_observer" in sent_to, "Non-excluded key should receive"
        assert len(sent_to) == 1
        print("  PASS: exclude_pubkey works")
    finally:
        tasks.get_wallet_nwcs = original_get_wallet_nwcs


async def test_send_notification_error_isolation():
    """One key failing doesn't prevent other keys from getting notifications."""
    sp = NWCServiceProvider(
        "d7b5232fba0e02e32cfe26f20cdf2c803b27ecd81052c2dd5d17e5e1a333fe58",
        "ws://localhost:7777",
    )

    sent_to = []
    call_count = 0

    async def mock_send_notification(pubkey, ntype, notification):
        nonlocal call_count
        call_count += 1
        if pubkey == "pub_fail":
            raise Exception("Simulated relay error")
        sent_to.append(pubkey)

    sp.send_notification = mock_send_notification

    key_fail = MockNWCKey("pub_fail", "wallet1", "notifications")
    key_ok = MockNWCKey("pub_ok", "wallet1", "notifications")

    original_get_wallet_nwcs = tasks.get_wallet_nwcs

    async def mock_get_wallet_nwcs(data):
        return [key_fail, key_ok]

    tasks.get_wallet_nwcs = mock_get_wallet_nwcs

    try:
        await tasks._send_notification_to_wallet(
            sp, "wallet1", "payment_received", {"amount": 1000}
        )

        assert call_count == 2, "Both keys should be attempted"
        assert "pub_ok" in sent_to, "Second key should succeed despite first failing"
        assert "pub_fail" not in sent_to
        print("  PASS: error isolation between keys")
    finally:
        tasks.get_wallet_nwcs = original_get_wallet_nwcs


def main():
    print("\n=== NIP-47 Notification Helper Tests ===\n")
    passed = 0
    failed = 0

    # Sync tests
    for test_fn in [
        test_permission_includes_notifications,
        test_build_transaction_data_settled,
        test_build_transaction_data_pending,
    ]:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {test_fn.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    # Async tests
    for test_fn in [
        test_send_notification_to_wallet_filters_permissions,
        test_send_notification_excludes_pubkey,
        test_send_notification_error_isolation,
    ]:
        try:
            asyncio.run(test_fn())
            passed += 1
        except Exception as e:
            print(f"  FAIL: {test_fn.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 40}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed > 0:
        sys.exit(1)
    print("All tests passed!")


if __name__ == "__main__":
    main()
