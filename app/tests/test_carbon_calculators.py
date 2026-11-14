"""Unit tests for pure functional carbon calculators (Afforestation & Soil Carbon)

verifying mathematical formulas against exact hand-computed values.
"""

import pytest
from app.services.carbon.afforestation import AfforestationCalculator
from app.services.carbon.soil_carbon import SoilCarbonCalculator


# =====================================================================
# Afforestation Calculator Unit Tests
# =====================================================================

def test_afforestation_calculator_hand_computed_values() -> None:
    """Verify Afforestation calculation against exact hand-computed baseline:

    Hand Calculation Steps:
      trees = 500
      avg_biomass_per_tree_kg = 50.0
      carbon_fraction = 0.47
      co2_to_c_ratio = 44 / 12 = 3.66666666667
      uncertainty_pct = 0.10
      buffer_pct = 0.15

      1. total_biomass_kg = 500 * 50.0 = 25,000.0 kg
      2. carbon_tonnes = 25,000.0 * 0.47 / 1,000 = 11.75 t C
      3. gross_co2e = 11.75 * (44 / 12) = 43.0833333333 t CO2e
      4. net_credits = 43.0833333333 * (1 - 0.10) * (1 - 0.15)
                     = 43.0833333333 * 0.90 * 0.85
                     = 32.95875 t CO2e
    """
    calc = AfforestationCalculator()
    inputs = {
        "trees": 500,
        "avg_biomass_per_tree_kg": 50.0,
    }
    parameters = {
        "carbon_fraction": 0.47,
        "co2_to_c_ratio": 44.0 / 12.0,
        "default_uncertainty_pct": 0.10,
        "default_buffer_pct": 0.15,
    }

    result = calc.calculate(inputs, parameters)

    assert result.co2e_gross_tonnes == pytest.approx(43.083333, abs=1e-5)
    assert result.net_credits == pytest.approx(32.95875, abs=1e-5)
    assert result.uncertainty_pct == 0.10
    assert result.buffer_pct == 0.15
    assert result.details["total_biomass_kg"] == 25000.0
    assert result.details["carbon_tonnes"] == 11.75

    # Check inputs snapshot structure for audit compliance
    snapshot = result.inputs_snapshot
    assert snapshot["inputs"]["trees"] == 500.0
    assert snapshot["parameters"]["carbon_fraction"] == 0.47


def test_afforestation_calculator_custom_overrides_and_defaults() -> None:
    """Verify custom input overrides for biomass, uncertainty, and buffer take precedence."""
    calc = AfforestationCalculator()
    inputs = {
        "tree_count": 1000,
        "avg_biomass_per_tree_kg": 60.0,
        "uncertainty_pct": 0.05,
        "buffer_pct": 0.10,
    }
    parameters = {
        "carbon_fraction": 0.47,
        "co2_to_c_ratio": 44.0 / 12.0,
        "default_uncertainty_pct": 0.10,
        "default_buffer_pct": 0.15,
    }

    # Hand calculation:
    # 1. total_biomass = 1000 * 60.0 = 60,000 kg
    # 2. carbon_tonnes = 60,000 * 0.47 / 1000 = 28.2 t C
    # 3. gross_co2e = 28.2 * (44 / 12) = 103.40 t CO2e
    # 4. net_credits = 103.40 * 0.95 * 0.90 = 88.407 t CO2e
    result = calc.calculate(inputs, parameters)

    assert result.co2e_gross_tonnes == pytest.approx(103.40, abs=1e-4)
    assert result.net_credits == pytest.approx(88.407, abs=1e-4)
    assert result.uncertainty_pct == 0.05
    assert result.buffer_pct == 0.10


def test_afforestation_calculator_zero_trees() -> None:
    """Verify zero trees yields zero gross and zero net credits without dividing by zero."""
    calc = AfforestationCalculator()
    result = calc.calculate({"trees": 0}, {"carbon_fraction": 0.47, "co2_to_c_ratio": 44.0 / 12.0})
    assert result.co2e_gross_tonnes == 0.0
    assert result.net_credits == 0.0


def test_afforestation_calculator_input_validation_errors() -> None:
    """Verify input validation catches missing fields and invalid ranges."""
    calc = AfforestationCalculator()
    params = {"carbon_fraction": 0.47, "co2_to_c_ratio": 44.0 / 12.0}

    # 1. Missing tree count
    with pytest.raises(ValueError, match="requires 'trees' or 'tree_count'"):
        calc.calculate({}, params)

    # 2. Negative tree count
    with pytest.raises(ValueError, match="must be a non-negative number"):
        calc.calculate({"trees": -10}, params)

    # 3. Negative biomass
    with pytest.raises(ValueError, match="Average biomass per tree must be positive"):
        calc.calculate({"trees": 100, "avg_biomass_per_tree_kg": -5.0}, params)

    # 4. Invalid uncertainty (> 1)
    with pytest.raises(ValueError, match="Uncertainty percentage must be in"):
        calc.calculate({"trees": 100, "uncertainty_pct": 1.5}, params)


# =====================================================================
# Soil Carbon Calculator Unit Tests
# =====================================================================

def test_soil_carbon_calculator_hand_computed_values() -> None:
    """Verify Soil Carbon calculation against exact hand-computed baseline:

    Hand Calculation Steps:
      area_acres = 10.0
      acres_to_hectares = 0.404686 -> area_ha = 4.04686 ha
      baseline: SOC% = 1.2, bulk_density = 1.30, depth = 30.0 cm
      current:  SOC% = 1.6, bulk_density = 1.25, depth = 30.0 cm
      co2_to_c_ratio = 44 / 12
      uncertainty_pct = 0.15
      buffer_pct = 0.20

      1. baseline_soc_stock = 1.2 * 1.30 * 30.0 = 46.80 t C/ha
      2. current_soc_stock  = 1.6 * 1.25 * 30.0 = 60.00 t C/ha
      3. delta_soc          = 60.00 - 46.80 = 13.20 t C/ha
      4. total_c_tonnes     = 13.20 * 4.04686 = 53.418552 t C
      5. gross_co2e         = 53.418552 * (44 / 12) = 195.868024 t CO2e
      6. net_credits        = 195.868024 * (1 - 0.15) * (1 - 0.20)
                            = 195.868024 * 0.85 * 0.80
                            = 133.19025632 t CO2e
    """
    calc = SoilCarbonCalculator()
    inputs = {
        "area_acres": 10.0,
        "baseline": {
            "soc_percent": 1.2,
            "bulk_density": 1.30,
            "depth_cm": 30.0,
        },
        "current": {
            "soc_percent": 1.6,
            "bulk_density": 1.25,
            "depth_cm": 30.0,
        },
    }
    parameters = {
        "acres_to_hectares": 0.404686,
        "co2_to_c_ratio": 44.0 / 12.0,
        "default_uncertainty_pct": 0.15,
        "default_buffer_pct": 0.20,
    }

    result = calc.calculate(inputs, parameters)

    assert result.co2e_gross_tonnes == pytest.approx(195.868024, abs=1e-5)
    assert result.net_credits == pytest.approx(133.190256, abs=1e-5)
    assert result.uncertainty_pct == 0.15
    assert result.buffer_pct == 0.20
    assert result.details["baseline_soc_stock_t_per_ha"] == pytest.approx(46.80, abs=1e-5)
    assert result.details["current_soc_stock_t_per_ha"] == pytest.approx(60.00, abs=1e-5)
    assert result.details["delta_soc_t_per_ha"] == pytest.approx(13.20, abs=1e-5)
    assert result.details["area_ha"] == pytest.approx(4.04686, abs=1e-5)
    assert result.details["total_carbon_tonnes"] == pytest.approx(53.418552, abs=1e-5)


def test_soil_carbon_calculator_reversal_handling() -> None:
    """Verify that when soil carbon drops (reversal), gross and net credits are 0.0 (no negative credits)."""
    calc = SoilCarbonCalculator()
    inputs = {
        "area_acres": 15.0,
        "baseline": {"soc_percent": 2.0, "bulk_density": 1.25, "depth_cm": 30.0},  # 75.0 t C/ha
        "current": {"soc_percent": 1.5, "bulk_density": 1.20, "depth_cm": 30.0},   # 54.0 t C/ha
    }
    parameters = {
        "acres_to_hectares": 0.404686,
        "co2_to_c_ratio": 44.0 / 12.0,
        "default_uncertainty_pct": 0.15,
        "default_buffer_pct": 0.20,
    }

    result = calc.calculate(inputs, parameters)

    assert result.co2e_gross_tonnes == 0.0
    assert result.net_credits == 0.0
    assert result.details["delta_soc_t_per_ha"] == pytest.approx(-21.0, abs=1e-5)
    assert result.details["total_carbon_tonnes"] == 0.0


def test_soil_carbon_calculator_flat_keys_support() -> None:
    """Verify calculator accepts flat observation keys as well as nested dictionaries."""
    calc = SoilCarbonCalculator()
    inputs = {
        "area_acres": 5.0,
        "baseline_soc_percent": 1.0,
        "baseline_bulk_density": 1.2,
        "baseline_depth_cm": 30.0,
        "current_soc_percent": 1.5,
        "current_bulk_density": 1.2,
        "current_depth_cm": 30.0,
    }
    params = {
        "acres_to_hectares": 0.404686,
        "co2_to_c_ratio": 44.0 / 12.0,
        "default_uncertainty_pct": 0.15,
        "default_buffer_pct": 0.20,
    }
    result = calc.calculate(inputs, params)
    # baseline stock: 1.0 * 1.2 * 30 = 36.0
    # current stock:  1.5 * 1.2 * 30 = 54.0
    # delta: 18.0 t C/ha
    assert result.details["delta_soc_t_per_ha"] == pytest.approx(18.0, abs=1e-5)
    assert result.net_credits > 0.0


def test_soil_carbon_calculator_input_validation_errors() -> None:
    """Verify input validation catches missing fields and non-positive numbers."""
    calc = SoilCarbonCalculator()
    params = {"acres_to_hectares": 0.404686, "co2_to_c_ratio": 44.0 / 12.0}

    # 1. Missing area_acres
    with pytest.raises(ValueError, match="requires 'area_acres'"):
        calc.calculate({}, params)

    # 2. Non-positive area
    with pytest.raises(ValueError, match="Parcel area must be positive"):
        calc.calculate({"area_acres": -2.0}, params)

    # 3. Missing baseline
    with pytest.raises(ValueError, match="Missing baseline soil parameters"):
        calc.calculate({"area_acres": 10.0, "current": {"soc_percent": 1.5, "bulk_density": 1.2, "depth_cm": 30.0}}, params)

    # 4. Non-positive baseline value
    with pytest.raises(ValueError, match="Baseline soil parameters must be strictly positive"):
        calc.calculate({
            "area_acres": 10.0,
            "baseline": {"soc_percent": -1.0, "bulk_density": 1.2, "depth_cm": 30.0},
            "current": {"soc_percent": 1.5, "bulk_density": 1.2, "depth_cm": 30.0},
        }, params)
