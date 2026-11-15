"""Soil Organic Carbon (SOC) removal calculator implementation."""

from typing import Any

from app.services.carbon.base import BaseCalculator, CalculationResult


class SoilCarbonCalculator(BaseCalculator):
    """Pure functional calculator for Soil Organic Carbon (SOC) stock changes.

    Formulas per PROJECT_SPEC.md Section 7:
        SOC_stock (t C/ha) = SOC% * bulk_density (g/cm³) * depth (cm)
        delta_SOC = SOC_stock_current - SOC_stock_baseline
        Gross CO2e (tonnes) = delta_SOC * area_ha * (44/12)
        Net credits = Gross CO2e * (1 - uncertainty_pct) * (1 - buffer_pct)
    """

    def calculate(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
    ) -> CalculationResult:
        """Calculate net soil carbon removal from baseline and current measurements.

        Args:
            inputs: Dictionary containing:
                - 'area_acres': float (> 0)
                - 'baseline': dict with 'soc_percent', 'bulk_density', 'depth_cm'
                  (or flat keys 'baseline_soc_percent', 'baseline_bulk_density', 'baseline_depth_cm')
                - 'current': dict with 'soc_percent', 'bulk_density', 'depth_cm'
                  (or flat keys 'current_soc_percent', 'current_bulk_density', 'current_depth_cm')
                - 'uncertainty_pct': float (optional override, 0 <= x < 1)
                - 'buffer_pct': float (optional override, 0 <= x < 1)
            parameters: Methodology parameters dictionary containing:
                - 'acres_to_hectares': float (default 0.404686)
                - 'co2_to_c_ratio': float (default 44/12 approx 3.6667)
                - 'depth_cm': float (default 30.0)
                - 'default_uncertainty_pct': float (default 0.15)
                - 'default_buffer_pct': float (default 0.20)

        Returns:
            CalculationResult with gross CO2e, deductions, and net credits.

        Raises:
            ValueError: If input values or parameters are invalid or missing.
        """
        # 1. Parcel Area
        area_acres = inputs.get("area_acres")
        if area_acres is None:
            raise ValueError("Soil carbon calculation requires 'area_acres' in inputs.")
        if not isinstance(area_acres, (int, float)) or area_acres <= 0:
            raise ValueError(f"Parcel area must be positive, got {area_acres!r}.")
        area_acres = float(area_acres)

        # 2. Extract baseline values (supports both nested dict and flat keys)
        baseline_data = inputs.get("baseline", {})
        b_soc = baseline_data.get("soc_percent", inputs.get("baseline_soc_percent"))
        b_bd = baseline_data.get("bulk_density", inputs.get("baseline_bulk_density"))
        b_depth = baseline_data.get(
            "depth_cm",
            inputs.get("baseline_depth_cm", parameters.get("depth_cm", 30.0)),
        )

        if b_soc is None or b_bd is None or b_depth is None:
            raise ValueError(
                "Missing baseline soil parameters: 'soc_percent', 'bulk_density', and 'depth_cm' are required."
            )
        if b_soc <= 0 or b_bd <= 0 or b_depth <= 0:
            raise ValueError(
                "Baseline soil parameters must be strictly positive numbers."
            )

        # 3. Extract current monitoring values
        current_data = inputs.get("current", {})
        c_soc = current_data.get("soc_percent", inputs.get("current_soc_percent"))
        c_bd = current_data.get("bulk_density", inputs.get("current_bulk_density"))
        c_depth = current_data.get(
            "depth_cm",
            inputs.get("current_depth_cm", b_depth),
        )

        if c_soc is None or c_bd is None or c_depth is None:
            raise ValueError(
                "Missing current soil parameters: 'soc_percent', 'bulk_density', and 'depth_cm' are required."
            )
        if c_soc <= 0 or c_bd <= 0 or c_depth <= 0:
            raise ValueError(
                "Current soil parameters must be strictly positive numbers."
            )

        # 4. Extract methodology parameters
        acres_to_ha = parameters.get("acres_to_hectares", 0.404686)
        if not isinstance(acres_to_ha, (int, float)) or acres_to_ha <= 0:
            raise ValueError(
                f"Acres to hectares conversion factor must be positive, got {acres_to_ha!r}."
            )
        acres_to_ha = float(acres_to_ha)

        co2_to_c_ratio = parameters.get("co2_to_c_ratio", 44.0 / 12.0)
        if not isinstance(co2_to_c_ratio, (int, float)) or co2_to_c_ratio <= 0:
            raise ValueError(
                f"CO2 to C ratio must be positive, got {co2_to_c_ratio!r}."
            )
        co2_to_c_ratio = float(co2_to_c_ratio)

        # 5. Deductions
        uncertainty_pct = inputs.get("uncertainty_pct")
        if uncertainty_pct is None:
            uncertainty_pct = parameters.get("default_uncertainty_pct", 0.15)
        if not isinstance(uncertainty_pct, (int, float)) or not (
            0 <= uncertainty_pct < 1
        ):
            raise ValueError(
                f"Uncertainty percentage must be in [0, 1), got {uncertainty_pct!r}."
            )
        uncertainty_pct = float(uncertainty_pct)

        buffer_pct = inputs.get("buffer_pct")
        if buffer_pct is None:
            buffer_pct = parameters.get("default_buffer_pct", 0.20)
        if not isinstance(buffer_pct, (int, float)) or not (0 <= buffer_pct < 1):
            raise ValueError(
                f"Buffer percentage must be in [0, 1), got {buffer_pct!r}."
            )
        buffer_pct = float(buffer_pct)

        # 6. Core Mathematical Computations
        # Formula: SOC_stock (t C/ha) = SOC% * BD (g/cm³) * Depth (cm)
        baseline_soc_stock = float(b_soc) * float(b_bd) * float(b_depth)
        current_soc_stock = float(c_soc) * float(c_bd) * float(c_depth)
        delta_soc_t_per_ha = current_soc_stock - baseline_soc_stock

        area_ha = area_acres * acres_to_ha

        # If soil carbon decreased or did not change, no positive credits are generated
        if delta_soc_t_per_ha <= 0:
            co2e_gross_tonnes = 0.0
            net_credits = 0.0
            total_carbon_tonnes = 0.0
        else:
            total_carbon_tonnes = delta_soc_t_per_ha * area_ha
            co2e_gross_tonnes = total_carbon_tonnes * co2_to_c_ratio
            net_credits = (
                co2e_gross_tonnes * (1.0 - uncertainty_pct) * (1.0 - buffer_pct)
            )

        inputs_snapshot = {
            "inputs": {
                "area_acres": area_acres,
                "baseline": {
                    "soc_percent": b_soc,
                    "bulk_density": b_bd,
                    "depth_cm": b_depth,
                },
                "current": {
                    "soc_percent": c_soc,
                    "bulk_density": c_bd,
                    "depth_cm": c_depth,
                },
                "uncertainty_pct": uncertainty_pct,
                "buffer_pct": buffer_pct,
            },
            "parameters": {
                "acres_to_hectares": acres_to_ha,
                "co2_to_c_ratio": co2_to_c_ratio,
            },
        }

        details = {
            "baseline_soc_stock_t_per_ha": baseline_soc_stock,
            "current_soc_stock_t_per_ha": current_soc_stock,
            "delta_soc_t_per_ha": delta_soc_t_per_ha,
            "area_ha": area_ha,
            "total_carbon_tonnes": total_carbon_tonnes,
        }

        return CalculationResult(
            co2e_gross_tonnes=round(co2e_gross_tonnes, 6),
            uncertainty_pct=uncertainty_pct,
            buffer_pct=buffer_pct,
            net_credits=round(net_credits, 6),
            inputs_snapshot=inputs_snapshot,
            details=details,
        )
