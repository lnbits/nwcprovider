"""
Standalone test for NIP-47 notification event construction.
Runs without lnbits installed - tests nwcp.py directly.
"""

import asyncio
import json
import os
import sys

# Add parent to path so we can import nwcp directly
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

# Mock lnbits modules before importing nwcp
import types

# Create mock lnbits.helpers
lnbits = types.ModuleType("lnbits")
lnbits.helpers = types.ModuleType("lnbits.helpers")
lnbits.helpers.encrypt_internal_message = lambda x: x
lnbits.settings = types.ModuleType("lnbits.settings")


class MockSettings:
    port = 5000
    lnbits_running = True


lnbits.settings.settings = MockSettings()
sys.modules["lnbits"] = lnbits
sys.modules["lnbits.helpers"] = lnbits.helpers
sys.modules["lnbits.settings"] = lnbits.settings

from nwcp import NWCServiceProvider  # noqa: E402


def test_supported_notifications():
    """supported_notifications list contains both types."""
    sp = NWCServiceProvider(
        "d7b5232fba0e02e32cfe26f20cdf2c803b27ecd81052c2dd5d17e5e1a333fe58",
        "ws://localhost:7777",
    )
    assert "payment_received" in sp.supported_notifications
    assert "payment_sent" in sp.supported_notifications
    print("  PASS: supported_notifications")


def test_info_event_tags():
    """Info event includes notifications tag."""
    sp = NWCServiceProvider(
        "d7b5232fba0e02e32cfe26f20cdf2c803b27ecd81052c2dd5d17e5e1a333fe58",
        "ws://localhost:7777",
    )
    sp.add_request_listener("pay_invoice", lambda *a: None)

    # Build the tags the same way _on_connection does
    tags = [["p", sp.public_key_hex]]
    if sp.supported_notifications:
        tags.append(["notifications", " ".join(sp.supported_notifications)])

    notif_tags = [t for t in tags if t[0] == "notifications"]
    assert len(notif_tags) == 1
    assert "payment_received" in notif_tags[0][1]
    assert "payment_sent" in notif_tags[0][1]
    print("  PASS: info event notifications tag")


async def test_send_notification():
    """send_notification builds correct kind 23196 event."""
    sp1 = NWCServiceProvider(
        "d7b5232fba0e02e32cfe26f20cdf2c803b27ecd81052c2dd5d17e5e1a333fe58",
        "ws://localhost:7777",
    )
    sp2 = NWCServiceProvider(
        "ce40821040275f72f3074a89770db3e2744b189f204807c867840eb58565de51",
        "ws://localhost:7777",
    )

    sent_events = []

    async def capture_send(data):
        sent_events.append(data)

    sp1._send = capture_send

    notification = {
        "type": "incoming",
        "state": "settled",
        "invoice": "lnbc1000n1...",
        "payment_hash": "abc123def456",
        "amount": 5000,
        "created_at": 1700000000,
        "settled_at": 1700000000,
    }

    await sp1.send_notification(sp2.public_key_hex, "payment_received", notification)

    assert len(sent_events) == 1
    event_data = sent_events[0]

    # Should be ["EVENT", {...}]
    assert event_data[0] == "EVENT"
    event = event_data[1]

    # Kind 23196
    assert event["kind"] == 23196, f"Expected kind 23196, got {event['kind']}"

    # Valid signature
    assert sp2._verify_event(event), "Event signature verification failed"

    # Tags: only p tag, no e tag
    tags = event["tags"]
    p_tags = [t for t in tags if t[0] == "p"]
    e_tags = [t for t in tags if t[0] == "e"]
    assert len(p_tags) == 1, f"Expected 1 p tag, got {len(p_tags)}"
    assert p_tags[0][1] == sp2.public_key_hex
    assert len(e_tags) == 0, f"Notifications must not have e tags, got {len(e_tags)}"

    # Decrypt and verify content
    content = sp2.private_key.decrypt_message(event["content"], sp1.public_key_hex)
    content = json.loads(content)
    assert content["notification_type"] == "payment_received"
    assert content["notification"]["type"] == "incoming"
    assert content["notification"]["state"] == "settled"
    assert content["notification"]["payment_hash"] == "abc123def456"
    assert content["notification"]["amount"] == 5000
    print("  PASS: send_notification event structure")


async def test_send_notification_payment_sent():
    """send_notification works for payment_sent type."""
    sp1 = NWCServiceProvider(
        "d7b5232fba0e02e32cfe26f20cdf2c803b27ecd81052c2dd5d17e5e1a333fe58",
        "ws://localhost:7777",
    )
    sp2 = NWCServiceProvider(
        "ce40821040275f72f3074a89770db3e2744b189f204807c867840eb58565de51",
        "ws://localhost:7777",
    )

    sent_events = []

    async def capture_send(data):
        sent_events.append(data)

    sp1._send = capture_send

    notification = {
        "type": "outgoing",
        "state": "settled",
        "invoice": "lnbc2000n1...",
        "payment_hash": "def789",
        "amount": 2000,
        "fees_paid": 10,
        "created_at": 1700000000,
        "settled_at": 1700000000,
    }

    await sp1.send_notification(sp2.public_key_hex, "payment_sent", notification)

    assert len(sent_events) == 1
    event = sent_events[0][1]
    assert event["kind"] == 23196

    content = sp2.private_key.decrypt_message(event["content"], sp1.public_key_hex)
    content = json.loads(content)
    assert content["notification_type"] == "payment_sent"
    assert content["notification"]["type"] == "outgoing"
    assert content["notification"]["fees_paid"] == 10
    print("  PASS: payment_sent notification")


async def test_encrypt_decrypt_roundtrip():
    """Notification content can be decrypted by the client."""
    sp = NWCServiceProvider(
        "d7b5232fba0e02e32cfe26f20cdf2c803b27ecd81052c2dd5d17e5e1a333fe58",
        "ws://localhost:7777",
    )
    client = NWCServiceProvider(
        "ce40821040275f72f3074a89770db3e2744b189f204807c867840eb58565de51",
        "ws://localhost:7777",
    )

    sent_events = []

    async def capture_send(data):
        sent_events.append(data)

    sp._send = capture_send

    # Send notification from sp to client
    await sp.send_notification(
        client.public_key_hex,
        "payment_received",
        {"type": "incoming", "amount": 42000},
    )

    event = sent_events[0][1]

    # Client decrypts using their private key and the sp's public key
    decrypted = client.private_key.decrypt_message(event["content"], sp.public_key_hex)
    parsed = json.loads(decrypted)
    assert parsed["notification"]["amount"] == 42000

    # SP can also decrypt (NIP-04 is symmetric)
    decrypted2 = sp.private_key.decrypt_message(event["content"], client.public_key_hex)
    parsed2 = json.loads(decrypted2)
    assert parsed2["notification"]["amount"] == 42000
    print("  PASS: encrypt/decrypt roundtrip")


def main():
    print("\n=== NIP-47 Notification Tests ===\n")
    passed = 0
    failed = 0

    # Sync tests
    for test_fn in [test_supported_notifications, test_info_event_tags]:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {test_fn.__name__}: {e}")
            failed += 1

    # Async tests
    for test_fn in [
        test_send_notification,
        test_send_notification_payment_sent,
        test_encrypt_decrypt_roundtrip,
    ]:
        try:
            asyncio.run(test_fn())
            passed += 1
        except Exception as e:
            print(f"  FAIL: {test_fn.__name__}: {e}")
            failed += 1

    print(f"\n{'=' * 40}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed > 0:
        sys.exit(1)
    print("All tests passed!")


if __name__ == "__main__":
    main()
