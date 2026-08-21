"""Proste funkcje matematyczne do benchmarków i testów."""

from math import isqrt
from typing import List


def is_prime(n: int) -> bool:
    """Zwraca True, gdy n jest liczbą pierwszą (n >= 2)."""
    if n < 2:
        return False
    if n == 2:
        return True
    if n % 2 == 0:
        return False

    limit = isqrt(n)
    for divisor in range(3, limit + 1, 2):
        if n % divisor == 0:
            return False
    return True


def factorize(n: int) -> List[int]:
    """Zwraca listę dzielników pierwszych liczby n (z powtórzeniami), posortowaną rosnąco."""
    if n < 1:
        raise ValueError("factorize() expects a positive integer")

    factors: List[int] = []
    remainder = n

    # Dzielnik 2
    while remainder % 2 == 0:
        factors.append(2)
        remainder //= 2

    # Dzielniki nieparzyste
    divisor = 3
    while divisor * divisor <= remainder:
        while remainder % divisor == 0:
            factors.append(divisor)
            remainder //= divisor
        divisor += 2

    if remainder > 1:
        factors.append(remainder)

    return factors