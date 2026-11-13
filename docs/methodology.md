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
