"""
Tests for watcher module.

Focuses on BTC to satoshis conversion precision.
"""

import pytest
from decimal import Decimal

from hashcredit_prover.watcher import btc_to_sats, SATS_PER_BTC


class TestBtcToSats:
    """Tests for btc_to_sats conversion function."""

    def test_one_btc(self):
        """1 BTC = 100,000,000 satoshis."""
        assert btc_to_sats(1) == 100_000_000
        assert btc_to_sats(1.0) == 100_000_000
        assert btc_to_sats("1") == 100_000_000
        assert btc_to_sats(Decimal("1")) == 100_000_000

    def test_zero(self):
        """0 BTC = 0 satoshis."""
        assert btc_to_sats(0) == 0
        assert btc_to_sats(0.0) == 0
        assert btc_to_sats("0") == 0

    def test_one_satoshi(self):
        """Smallest unit: 1 satoshi = 0.00000001 BTC."""
        assert btc_to_sats(0.00000001) == 1
        assert btc_to_sats("0.00000001") == 1
        assert btc_to_sats(Decimal("0.00000001")) == 1

    def test_point_one_btc_float_precision(self):
        """
        Critical test: 0.1 BTC should be exactly 10,000,000 satoshis.

        This tests the float precision issue:
        - float(0.1) * 1e8 = 9999999.999999998 (WRONG!)
        - Decimal("0.1") * 100000000 = 10000000 (CORRECT)
        """
        # Using float directly would fail
        # assert int(0.1 * 1e8) == 10_000_000  # This fails: 9999999

        # Our function should handle it correctly
        assert btc_to_sats(0.1) == 10_000_000
        assert btc_to_sats("0.1") == 10_000_000

    def test_point_two_btc_float_precision(self):
        """0.2 BTC also has float precision issues."""
        assert btc_to_sats(0.2) == 20_000_000
        assert btc_to_sats("0.2") == 20_000_000

    def test_point_three_btc_float_precision(self):
        """0.3 BTC also has float precision issues."""
        assert btc_to_sats(0.3) == 30_000_000
        assert btc_to_sats("0.3") == 30_000_000

    def test_common_amounts(self):
        """Test various common BTC amounts."""
        test_cases = [
            (0.001, 100_000),          # 1 mBTC
            (0.01, 1_000_000),         # 10 mBTC
            (0.5, 50_000_000),         # 0.5 BTC
            (0.12345678, 12_345_678),  # 8 decimal places
            (21.0, 2_100_000_000),     # 21 BTC
            (0.00001, 1_000),          # 10 microBTC
        ]
        for btc, expected_sats in test_cases:
            assert btc_to_sats(btc) == expected_sats, f"Failed for {btc} BTC"

    def test_max_btc_supply(self):
        """Test near maximum BTC supply (21 million)."""
        assert btc_to_sats(21_000_000) == 2_100_000_000_000_000

    def test_string_input(self):
        """Test string input handling."""
        assert btc_to_sats("0.00000001") == 1
        assert btc_to_sats("1.23456789") == 123_456_789

    def test_decimal_input(self):
        """Test Decimal input handling."""
        assert btc_to_sats(Decimal("0.00000001")) == 1
        assert btc_to_sats(Decimal("1.23456789")) == 123_456_789

    def test_integer_input(self):
        """Test integer input handling."""
        assert btc_to_sats(1) == 100_000_000
        assert btc_to_sats(10) == 1_000_000_000

    def test_fractional_satoshi_raises(self):
        """Values resulting in fractional satoshis should raise ValueError."""
        with pytest.raises(ValueError, match="fractional satoshis"):
            btc_to_sats("0.000000001")  # 0.1 satoshi

    def test_large_precision_string(self):
        """Test that we handle large precision strings correctly."""
        # 8 decimal places is valid
        assert btc_to_sats("0.12345678") == 12_345_678

        # 9+ decimal places should fail (unless they're zeros)
        assert btc_to_sats("0.123456780") == 12_345_678  # trailing zero ok
        with pytest.raises(ValueError):
            btc_to_sats("0.123456789")  # 9 significant digits

    def test_sats_per_btc_constant(self):
        """Verify the SATS_PER_BTC constant."""
        assert SATS_PER_BTC == Decimal("100000000")


class TestBtcToSatsFloatProblems:
    """
    Demonstrate the float precision problems this fix addresses.

    These tests document WHY we need Decimal conversion.
    Note: Some float behaviors vary by Python version and platform.
    """

    def test_float_representation_inexact(self):
        """Float 0.1 cannot be represented exactly in binary."""
        # This demonstrates the fundamental issue
        # float(0.1) is not exactly 0.1
        assert repr(0.1) == "0.1"  # Looks fine
        # But internally it's approximately 0.1000000000000000055511151231257827021181583404541015625
        assert 0.1 + 0.1 + 0.1 != 0.3  # Classic float precision issue

        # Our function handles this correctly
        assert btc_to_sats(0.1) == 10_000_000
        assert btc_to_sats(0.3) == 30_000_000

    def test_decimal_vs_float_precision(self):
        """Decimal provides exact decimal arithmetic."""
        from decimal import Decimal

        # Float arithmetic can have precision issues
        float_result = 0.1 + 0.2
        assert float_result != 0.3  # Classic float issue

        # Decimal is exact
        dec_result = Decimal("0.1") + Decimal("0.2")
        assert dec_result == Decimal("0.3")

        # Our function uses Decimal internally
        assert btc_to_sats(0.1) + btc_to_sats(0.2) == btc_to_sats(0.3)

    def test_cumulative_conversion_accuracy(self):
        """Test that multiple conversions give consistent results."""
        # Convert individually and sum
        # 0.1 BTC = 10,000,000 sats
        # 10 * 10,000,000 = 100,000,000 sats = 1 BTC
        total_sats = 0
        for _ in range(10):
            total_sats += btc_to_sats(0.1)
        assert total_sats == 100_000_000  # 10 * 0.1 BTC = 1 BTC

        # Convert sum at once
        assert btc_to_sats(1.0) == 100_000_000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
