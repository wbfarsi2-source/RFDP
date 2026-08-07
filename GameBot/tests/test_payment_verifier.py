from decimal import Decimal

from core.payment_verifier import CryptoPaymentVerifier


def test_base_transaction_hash_validation():
    value = "0x" + "a" * 64
    assert CryptoPaymentVerifier.normalize_tx_hash("base_usdc", value) == value


def test_exact_amount_matching():
    verifier = CryptoPaymentVerifier()
    assert verifier._amount_matches(Decimal("4.990001"), Decimal("4.990001"))
    assert not verifier._amount_matches(Decimal("4.99"), Decimal("4.990100"))
