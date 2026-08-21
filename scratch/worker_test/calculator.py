def add(a, b):
    return a + b

def divide(a, b):
    # BUG: nie rzuca ValueError przy b == 0 i zwraca int zamiast float
    return a // b

def is_even(n):
    # BUG: odwrotna logika
    return n % 2 != 0
