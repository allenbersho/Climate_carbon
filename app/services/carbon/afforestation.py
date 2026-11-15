"""Afforestation carbon removal calculator implementation."""

from typing import Any

from app.services.carbon.base import BaseCalculator, CalculationResult


class AfforestationCalculator(BaseCalculator):
    """Pure functional calculator for afforestation and tree planting projects.

    Formula per PROJECT_SPEC.md Section 7:
        CO2e (tonnes) = trees * avg_biomass_per_tree_kg * carbon_fraction * (44/12) / 1000
        Net credits = CO2e * (1 - uncertainty_pct) * (1 - buffer_pct)
    """

    def calculate(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
    ) -> CalculationResult:
        """Calculate afforestation biomass carbon removal.

        Args:
            inputs: Dictionary containing:
                - 'trees' (or 'tree_count'): int (>= 0)
                - 'avg_biomass_per_tree_kg': float (optional, falls back to methodology default)
                - 'uncertainty_pct': float (optional override, 0 <= x < 1)
                - 'buffer_pct': float (optional override, 0 <= x < 1)
            parameters: Methodology parameters dictionary containing:
                - 'carbon_fraction': float (e.g. 0.47)
                - 'co2_to_c_ratio': float (e.g. 44/12 approx 3.6667)
                - 'default_biomass_per_tree_kg': float (e.g. 50.0)
                - 'default_uncertainty_pct': float (e.g. 0.10)
                - 'default_buffer_pct': float (e.g. 0.15)

        Returns:
            CalculationResult with gross CO2e, deductions, and net credits.

        Raises:
            ValueError: If input values or parameters are invalid or missing.
        """
        # 1. Extract tree count
        tree_count = inputs.get("trees")
        if tree_count is None:
            tree_count = inputs.get("tree_count")
        if tree_count is None:
            raise ValueError(
                "Afforestation calculation requires 'trees' or 'tree_count' in inputs."
            )
        if not isinstance(tree_count, (int, float)) or tree_count < 0:
            raise ValueError(
                f"Tree count must be a non-negative number, got {tree_count!r}."
            )
        tree_count = float(tree_count)

        # 2. Extract biomass per tree
        avg_biomass_kg = inputs.get("avg_biomass_per_tree_kg")
        if avg_biomass_kg is None:
            avg_biomass_kg = parameters.get("default_biomass_per_tree_kg", 50.0)
        if not isinstance(avg_biomass_kg, (int, float)) or avg_biomass_kg <= 0:
            raise ValueError(
                f"Average biomass per tree must be positive, got {avg_biomass_kg!r}."
            )
        avg_biomass_kg = float(avg_biomass_kg)

        # 3. Extract methodology coefficients
        carbon_fraction = parameters.get("carbon_fraction", 0.47)
        if not isinstance(carbon_fraction, (int, float)) or not (
            0 < carbon_fraction <= 1
        ):
            raise ValueError(
                f"Carbon fraction must be in range (0, 1], got {carbon_fraction!r}."
            )
        carbon_fraction = float(carbon_fraction)

        co2_to_c_ratio = parameters.get("co2_to_c_ratio", 44.0 / 12.0)
        if not isinstance(co2_to_c_ratio, (int, float)) or co2_to_c_ratio <= 0:
            raise ValueError(
                f"CO2 to C ratio must be positive, got {co2_to_c_ratio!r}."
            )
        co2_to_c_ratio = float(co2_to_c_ratio)

        # 4. Extract deduction percentages
        uncertainty_pct = inputs.get("uncertainty_pct")
        if uncertainty_pct is None:
            uncertainty_pct = parameters.get("default_uncertainty_pct", 0.10)
        if not isinstance(uncertainty_pct, (int, float)) or not (
            0 <= uncertainty_pct < 1
        ):
            raise ValueError(
                f"Uncertainty percentage must be in [0, 1), got {uncertainty_pct!r}."
            )
        uncertainty_pct = float(uncertainty_pct)

        buffer_pct = inputs.get("buffer_pct")
        if buffer_pct is None:
            buffer_pct = parameters.get("default_buffer_pct", 0.15)
        if not isinstance(buffer_pct, (int, float)) or not (0 <= buffer_pct < 1):
            raise ValueError(
                f"Buffer percentage must be in [0, 1), got {buffer_pct!r}."
            )
        buffer_pct = float(buffer_pct)

        # 5. Core Mathematical Computation
        # Step A: Total dry biomass in kg
        total_biomass_kg = tree_count * avg_biomass_kg
        # Step B: Total elemental carbon in tonnes (1 tonne = 1,000 kg)
        carbon_tonnes = (total_biomass_kg * carbon_fraction) / 1000.0
        # Step C: Gross CO2e in tonnes
        co2e_gross_tonnes = carbon_tonnes * co2_to_c_ratio
        # Step D: Net credits after uncertainty and buffer deductions
        net_credits = co2e_gross_tonnes * (1.0 - uncertainty_pct) * (1.0 - buffer_pct)

        inputs_snapshot = {
            "inputs": {
                "trees": tree_count,
                "avg_biomass_per_tree_kg": avg_biomass_kg,
                "uncertainty_pct": uncertainty_pct,
                "buffer_pct": buffer_pct,
            },
            "parameters": {
                "carbon_fraction": carbon_fraction,
                "co2_to_c_ratio": co2_to_c_ratio,
            },
        }

        details = {
            "total_biomass_kg": total_biomass_kg,
            "carbon_tonnes": carbon_tonnes,
        }

        return CalculationResult(
            co2e_gross_tonnes=round(co2e_gross_tonnes, 6),
            uncertainty_pct=uncertainty_pct,
            buffer_pct=buffer_pct,
            net_credits=round(net_credits, 6),
            inputs_snapshot=inputs_snapshot,
            details=details,
        )
