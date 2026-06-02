import pytest

from ...paranoia import assert_valid_lud16


@pytest.mark.parametrize(
    "address",
    [
        "satoshi@example.com",
        "user.name@example.com",
        "user-name@sub.example.com",
        "user_name@example.co.uk",
        "abc123@example.com",
    ],
)
def test_assert_valid_lud16_accepts_valid_addresses(address):
    # Should not raise
    assert_valid_lud16(address)


@pytest.mark.parametrize(
    "address",
    [
        "",  # empty
        "noatsign.com",  # missing @
        "user@@example.com",  # double @
        "@example.com",  # empty name
        "user@",  # empty domain
        "user@localhost",  # domain without a dot
        "user name@example.com",  # space in name
        "user@exa mple.com",  # space in domain
        "user!@example.com",  # illegal char in name
        "user@exam_ple.com",  # underscore not allowed in domain
        "a" * 256 + "@example.com",  # too long
    ],
)
def test_assert_valid_lud16_rejects_invalid_addresses(address):
    with pytest.raises(ValueError):
        assert_valid_lud16(address)
