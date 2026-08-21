"""Testy jednostkowe dla scratch.math_benchmark."""

import pytest

from math_benchmark import factorize, is_prime


def test_is_prime_basic():
    """Sprawdza poprawne rozpoznawanie liczb pierwszych i złożonych."""
    primes = [2, 3, 5, 7, 11, 13, 17, 19, 23, 97]
    composites = [1, 0, -3, 4, 6, 8, 9, 15, 100]

    for n in primes:
        assert is_prime(n) is True, f"{n} powinno być pierwsze"
    for n in composites:
        assert is_prime(n) is False, f"{n} powinno być złożone"


def test_factorize_small_numbers():
    """Sprawdza faktoryzację małych liczb."""
    assert factorize(1) == []
    assert factorize(2) == [2]
    assert factorize(12) == [2, 2, 3]
    assert factorize(84) == [2, 2, 3, 7]
    assert factorize(97) == [97]


def test_factorize_rejects_non_positive():
    """Sprawdza, że factorize rzuca ValueError dla n < 1."""
    with pytest.raises(ValueError):
        factorize(0)
    with pytest.raises(ValueError):
        factorize(-5)