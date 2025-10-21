import logging
import sys
from typing import Literal, Optional, Union
import pytest

# Constraint constants for assertion functions
POSITIVE: Literal['positive'] = 'positive'
NON_NEGATIVE: Literal['non-negative'] = 'non-negative'

# To investigate how to configure pytest logging:
# https://docs.pytest.org/en/stable/how-to/logging.html
# From the first time it did not work


def configure_test_logging():
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s [%(name)s]')

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)


def get_option_value(pytestconfig, option_name):
    cli_value = pytestconfig.getoption('--' + option_name)
    if cli_value:
        return cli_value
    return pytestconfig.getini(option_name)


def register_option(parser, option_name, description, default):
    parser.addini(option_name, description, default=default)
    parser.addoption(
        '--' + option_name,
        action='store',
        help=description
    )


def assert_is_numeric_string(
    value, field_name: str, constraint: Optional[Literal['positive', 'non-negative']] = None
) -> float:
    """
    Assert that 'value' is a numeric string and optionally satisfies a constraint.

    Args:
        value: The value to check (expected to be a string).
        field_name: The field name for clearer assertion messages.
        constraint: Optional constraint: 'positive' (> 0), 'non-negative' (>= 0), or None.

    Returns:
        The parsed float value for further checks by the caller.

    Raises:
        AssertionError or triggers pytest.fail with clear, descriptive messages.
    """
    assert isinstance(value, str), f"'{field_name}' must be string, got {type(value)}"
    num = 0
    try:
        num = float(value)
    except (TypeError, ValueError):
        pytest.fail(f"'{field_name}' should be numeric string, got {value}")

    if constraint is not None:
        if constraint == POSITIVE:
            assert num > 0, f"'{field_name}' must be positive, got {value}"
        elif constraint == NON_NEGATIVE:
            assert num >= 0, f"'{field_name}' must be non-negative, got {value}"
        else:
            pytest.fail(f"Invalid constraint '{constraint}' for field '{field_name}'")

    return num


def assert_is_int(
    value, field_name: str, constraint: Optional[Literal['positive', 'non-negative']] = None
) -> int:
    """
    Assert that 'value' is an integer and optionally satisfies a constraint.

    Args:
        value: The value to check (expected to be int).
        field_name: The field name for clearer assertion messages.
        constraint: Optional constraint: 'positive' (> 0), 'non-negative' (>= 0), or None.

    Returns:
        The integer value for further checks by the caller.

    Raises:
        AssertionError with clear, descriptive messages.
    """
    assert isinstance(value, int), f"'{field_name}' must be int, got {type(value)}"

    if constraint is not None:
        if constraint == POSITIVE:
            assert value > 0, f"'{field_name}' must be positive, got {value}"
        elif constraint == NON_NEGATIVE:
            assert value >= 0, f"'{field_name}' must be non-negative, got {value}"
        else:
            pytest.fail(f"Invalid constraint '{constraint}' for field '{field_name}'")

    return value


def assert_is_number(
    value, field_name: str, constraint: Optional[Literal['positive', 'non-negative']] = None
) -> Union[int, float]:
    """
    Assert that 'value' is numeric (int or float) and optionally satisfies a constraint.

    Args:
        value: The value to check (expected to be int or float).
        field_name: The field name for clearer assertion messages.
        constraint: Optional constraint: 'positive' (> 0), 'non-negative' (>= 0), or None.

    Returns:
        The numeric value (preserving original type) for further checks by the caller.

    Raises:
        AssertionError with clear, descriptive messages.
    """
    assert isinstance(value, (int, float)), f"'{field_name}' must be numeric, got {type(value)}"

    if constraint is not None:
        if constraint == POSITIVE:
            assert value > 0, f"'{field_name}' must be positive, got {value}"
        elif constraint == NON_NEGATIVE:
            assert value >= 0, f"'{field_name}' must be non-negative, got {value}"
        else:
            pytest.fail(f"Invalid constraint '{constraint}' for field '{field_name}'")

    return value


def assert_is_valid_solana_address(address: str, field_name: str):
    """
    Simple validation of a Solana address format.
    Args:
        address: The Solana address to validate.
        field_name: The field name for clearer assertion messages.
    Raises:
        AssertionError with clear, descriptive messages if validation fails.
    """
    assert isinstance(address, str), f"'{field_name}' must be string, got {type(address)}"
    assert 32 <= len(address) <= 44, f"'{field_name}' should be valid Solana address length, got {len(address)}"
    assert address.isalnum(), f"'{field_name}' should contain only alphanumeric chars, got {address}"


