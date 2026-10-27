"""Unit tests for BQL value serialization."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from beancount.core.amount import Amount
from beancount.core.inventory import Inventory
from beancount.core.position import Position

from beancount_mcp.queries import _serialize, _type_name


def testSerialize_shouldConvertDecimalToPlainString_whenValueIsDecimal() -> None:
    # Given
    value = Decimal("10.50")

    # When
    result = _serialize(value)

    # Then
    assert result == "10.50"


def testSerialize_shouldFormatAmount_whenValueIsAmount() -> None:
    # Given
    value = Amount(Decimal("10.00"), "EUR")

    # When
    result = _serialize(value)

    # Then
    assert result == "10.00 EUR"


def testSerialize_shouldFormatPositionAndInventory_whenValuesAreBeancountTypes() -> None:
    # Given
    position = Position(Amount(Decimal("10.00"), "EUR"))
    inventory = Inventory.from_string("10.00 EUR")

    # When
    position_result = _serialize(position)
    inventory_result = _serialize(inventory)

    # Then
    assert position_result == "10.00 EUR"
    assert inventory_result == "(10.00 EUR)"


def testSerialize_shouldConvertTemporalValuesToIso_whenValueIsDateOrDatetime() -> None:
    # Given
    day = date(2026, 1, 2)
    moment = datetime(2026, 1, 2, 3, 4, 5)

    # When
    day_result = _serialize(day)
    moment_result = _serialize(moment)

    # Then
    assert day_result == "2026-01-02"
    assert moment_result == "2026-01-02T03:04:05"


def testSerialize_shouldSortSets_whenValueIsSet() -> None:
    # Given
    value = {"b", "a"}

    # When
    result = _serialize(value)

    # Then
    assert result == ["a", "b"]


def testSerialize_shouldRecurseIntoContainers_whenValueIsListOrDict() -> None:
    # Given
    value = {
        "amount": Amount(Decimal("10.00"), "EUR"),
        "dates": [date(2026, 1, 2)],
    }

    # When
    result = _serialize(value)

    # Then
    assert result == {"amount": "10.00 EUR", "dates": ["2026-01-02"]}


def testSerialize_shouldConvertFloatToString_whenValueIsFloat() -> None:
    # Given
    value = 1.5

    # When
    result = _serialize(value)

    # Then
    assert result == "1.5"


@pytest.mark.parametrize("value", [None, True, 3, "text"])
def testSerialize_shouldLeavePrimitivesUnchanged_whenValueIsPrimitive(
    value: object,
) -> None:
    # Given
    # a JSON primitive

    # When
    result = _serialize(value)

    # Then
    assert result == value


@pytest.mark.parametrize(
    ("datatype", "expected"),
    [
        (str, "string"),
        (int, "integer"),
        (Decimal, "decimal"),
        (date, "date"),
        (datetime, "datetime"),
        (bool, "boolean"),
    ],
)
def testTypeName_shouldMapPrimitiveTypes_whenDatatypeIsKnown(
    datatype: type[object], expected: str
) -> None:
    # Given
    # a primitive datatype

    # When
    result = _type_name(datatype)

    # Then
    assert result == expected


@pytest.mark.parametrize(
    ("datatype", "expected"),
    [
        (Amount, "amount"),
        (Position, "position"),
        (Inventory, "inventory"),
    ],
)
def testTypeName_shouldMapBeancountTypes_whenDatatypeIsBeancountType(
    datatype: type[object], expected: str
) -> None:
    # Given
    # a Beancount datatype

    # When
    result = _type_name(datatype)

    # Then
    assert result == expected


def testTypeName_shouldUseClassName_whenDatatypeIsUnknown() -> None:
    # Given
    class Custom:
        pass

    # When
    result = _type_name(Custom)

    # Then
    assert result == "Custom"
