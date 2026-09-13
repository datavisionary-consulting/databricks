# Databricks

Real, end-to-end Databricks (PySpark, Delta Lake, MLlib) case studies. Each subfolder is one project: real data at lakehouse scale, the actual notebooks that produced the results, and a README explaining what was found and why it matters in plain, non-technical language.

These projects are also written up, with figures and a business-first summary, on [datavisionary-consulting.github.io](https://datavisionary-consulting.github.io/#solutions).

## Projects

- [`global-shipping-chokepoints/`](global-shipping-chokepoints/) — a global view of the world's 9 major shipping chokepoints, cross-checking real AIS traffic density (World Bank) against real cargo-carrying capacity (IMF PortWatch).
- [`steam-review-helpfulness-classification/`](steam-review-helpfulness-classification/) — predicting whether a Steam review gets marked "helpful," at 6.4M-row lakehouse scale, with a triage framework for routing human review attention.
- [`pnda-catalog-inventory/`](pnda-catalog-inventory/) — inventory and exploration layer for Peru's National Open Data Platform (~4,714 datasets): metadata catalog, resource sampling, and a report to decide what to build next. Not a finished case study on its own.
