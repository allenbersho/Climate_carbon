"""Carbon removal calculation engine package providing pure functional calculators."""

from app.services.carbon.afforestation import AfforestationCalculator
from app.services.carbon.base import BaseCalculator, CalculationResult
from app.services.carbon.soil_carbon import SoilCarbonCalculator

__all__ = [
    "AfforestationCalculator",
    "BaseCalculator",
    "CalculationResult",
    "SoilCarbonCalculator",
]
