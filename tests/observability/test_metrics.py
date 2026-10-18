from decimal import Decimal

from baremetal_harness.core.messages import Usage
from baremetal_harness.observability.costs import CostCalculator, ModelPrice


def test_cost_uses_decimal_without_early_rounding() -> None:
    cost = CostCalculator().calculate(
        Usage(1_000_000, 500_000),
        ModelPrice(Decimal("2"), Decimal("4")),
    )
    assert cost == Decimal("4")
