from dataclasses import dataclass
from decimal import Decimal

from baremetal_harness.core.messages import Usage


@dataclass(frozen=True, slots=True)
class ModelPrice:
    input_per_million: Decimal
    output_per_million: Decimal


class CostCalculator:
    def calculate(self, usage: Usage, price: ModelPrice) -> Decimal:
        million = Decimal(1_000_000)
        return (
            Decimal(usage.input_tokens) * price.input_per_million / million
            + Decimal(usage.output_tokens) * price.output_per_million / million
        )
