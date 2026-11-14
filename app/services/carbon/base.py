"""Base interface and calculation result structures for pure carbon removal calculators."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CalculationResult:
    """Immutable output from a carbon removal calculation.

    Per PROJECT_SPEC.md Section 6 Rule 5: Every estimate stores inputs_snapshot
    so it can be reproduced exactly by third-party auditors.
    """

    co2e_gross_tonnes: float
    uncertainty_pct: float
    buffer_pct: float
    net_credits: float
    inputs_snapshot: dict[str, Any]
    details: dict[str, Any] = field(default_factory=dict)


class BaseCalculator(ABC):
    """Abstract base calculator interface.

    Calculators MUST be pure functions:
    1. Zero database access or network I/O inside calculators.
    2. All coefficients and thresholds come from the methodology parameters dictionary.
    3. Outputs are deterministic and reproducible.
    """

    @abstractmethod
    def calculate(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
    ) -> CalculationResult:
        """Execute carbon removal calculation.

        Args:
            inputs: Monitored field data (e.g. tree count, soil core values, parcel acreage).
            parameters: Methodology parameters snapshot loaded from the Methodology row.

        Returns:
            CalculationResult containing gross removals, deductions, net credits, and inputs snapshot.

        Raises:
            ValueError: If required inputs or parameters are missing or invalid.
        """
        raise NotImplementedError
