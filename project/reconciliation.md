# Stage 3 data reconciliation

Generated from the complete local HRM cache on 2026-11-25.
The source rows and request identifiers remain in ignored `data/raw/`; this report contains aggregates only.

## Raw source rows

| Source table | Raw rows |
| --- | ---: |
| service requests | 489,632 |
| work orders | 121,849 |
| wo custom fields | 468,849 |
| sr custom fields | 1,192,089 |

## Service Request scope and timing

The locked scope is the `Street Surface Maintenance` request type after trimming surrounding source whitespace,
labelled street surface repair requests.
The raw Service Request row count reconciles as 472,422 outside scope plus
17,210 in scope.

| Reconciliation outcome | Rows |
| --- | ---: |
| Raw Service Request rows | 489,632 |
| Outside selected scope | 472,422 |
| Selected scope rows | 17,210 |
| Duplicate rows discarded | 0 |
| Unique selected rows | 17,210 |
| Timing exclusions | 0 |
| Kept for timing metrics | 17,210 |
| Closed rows kept | 17,131 |
| Open/censored rows kept | 79 |

| Timing exclusion reason | Rows |
| --- | ---: |
| missing initiated date | 0 |
| invalid initiated date | 0 |
| initiated after pull date | 0 |
| invalid close date | 0 |
| closed after pull date | 0 |
| closed before initiated | 0 |

The unique selected row total equals timing exclusions plus rows kept. Open requests are kept as right-censored
observations through the cache pull date; they are not treated as zero-day closures. Closed-before-initiated
records are excluded from timing only. Closed waits above Q3 + 1.5 × IQR are retained; 1,881
were flagged for inspection only.

## Custom Fields

| Source | Raw rows | Pivot rows | Pivot fields |
| --- | ---: | ---: | ---: |
| Service Request Custom Fields matching selected request IDs | 0 | 0 | 0 |
| Work Order Custom Fields (unlinked, pivoted separately) | 468,849 | 117,212 | 7 |

The Service Request Custom Fields table was cleaned and pivoted for the selected request IDs. It did not provide
matching rows in the Stage 1 scan, so it does not narrow the population. Work Order Custom Fields were pivoted
separately for reconciliation, but no reliable request-to-work-order ID link exists; they are not used to classify
or time these requests. No field values are published.

## Public output checks

The public JSON totals 31,982 bytes (target: under 50,000 bytes). It contains aggregate counts and statistics,
not addresses, coordinates, free text, or request IDs. The wait estimator is Kaplan–Meier with closed requests
as events and open requests as right-censored observations. Statistics are suppressed below n = 30.
