# CarbonTrack Methodology & Scientific Assumptions

> **Disclaimer:** CarbonTrack is an educational prototype inspired by MRV concepts in the carbon-removal domain. It is NOT a validated carbon registry methodology (e.g., Verra VCS, Gold Standard).

## 1. Scope
CarbonTrack computes estimated carbon dioxide equivalent ($\text{CO}_2\text{e}$) removals for:
1. **Afforestation:** Tree planting biomass accumulation over time.
2. **Soil Organic Carbon (SOC):** Regenerative agriculture soil carbon stock changes.
3. **Biochar (Future):** Long-term stable pyrogenic carbon sequestration.

## 2. Core Formulas & Assumptions

### Afforestation
$$\text{CO}_2\text{e (tonnes)} = \text{trees} \times \text{avg\_biomass\_per\_tree\_kg} \times \text{carbon\_fraction} \times \frac{44}{12} \div 1000$$

* `carbon_fraction = 0.47` (**ASSUMPTION**): IPCC default average carbon fraction of dry wood biomass.
* Ratio $\frac{44}{12} \approx 3.667$: Stoichiometric ratio converting elemental Carbon (molecular weight 12) to Carbon Dioxide ($\text{CO}_2$, molecular weight 44).

### Soil Carbon Stock
$$\text{SOC\_stock (t C/ha)} = \text{SOC}\% \times \text{bulk\_density (g/cm}^3\text{)} \times \text{depth (cm)}$$
* Net removal is calculated as the increase above baseline measurements:
  $$\Delta \text{SOC} = \text{SOC\_stock}_{\text{current}} - \text{SOC\_stock}_{\text{baseline}}$$
* Scaled by parcel area (converted to hectares) and multiplied by $\frac{44}{12}$.

### Net Carbon Credits
$$\text{Net Credits} = \text{CO}_2\text{e} \times (1 - \text{uncertainty\_pct}) \times (1 - \text{buffer\_pct})$$
* **Uncertainty deduction:** Discounts credit issuance based on sampling variance.
* **Buffer deduction:** Withheld reserve pool against potential carbon reversal (e.g. wildfire or drought).

## 3. Data Quality & Validation Rules (Phase 5)

CarbonTrack runs automated validation strategies on all monitoring observations before estimating carbon credits. Observations flagged with `error`-severity issues are excluded from credit generation per Section 6 Rule 4.

| Rule Name | Severity | Plausible Bounds | Scientific Basis / Assumption |
|---|---|---|---|
| `soc_range_check` | `error` | $0.1\% \le \text{SOC}\% \le 10.0\%$ | **ASSUMPTION**: Mineral agricultural soils typically contain $0.5\% - 5.0\%$ organic carbon. Values $< 0.1\%$ resemble pure beach sand; values $> 10.0\%$ indicate waterlogged organic peat/bogs and represent lab anomalies in dryland farms. |
| `tree_count_drop_check` | `warning` | $\le 30\%$ drop | **ASSUMPTION**: A $> 30\%$ drop in living trees between consecutive monitoring events indicates substantial mortality, logging, disease, or reversal requiring auditor field inspection. |
| `missing_baseline_check` | `error` | Baseline required | **MRV Core Requirement**: Carbon additionality can only be verified against an established pre-project baseline measurement. |
| `future_date_check` | `error` | $\text{observed\_at} \le \text{now}$ | **Data Integrity**: Observations cannot be timestamped in the future. |
| `implausible_trees_per_acre_check` | `error` | $\le 2500\text{ trees/acre}$ | **ASSUMPTION**: Standard afforestation planting density is $400 - 1200\text{ stems/acre}$. Densities $> 2500\text{ stems/acre}$ exceed biological canopy capacity for standing trees and indicate data entry errors. |

