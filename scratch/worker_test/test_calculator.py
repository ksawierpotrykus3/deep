import pytest
from calculator import add, divide, is_even

def test_add():
    assert add(2, 3) == 5

def test_divide():
    assert divide(10, 2) == 5.0
    with pytest.raises(ValueError):
        divide(10, 0)

def test_is_even():
    assert is_even(4) is True
    assert is_even(5) is False
