# Layer 1 definitions

Version 1.1; core measures locked on 2026-11-24 after the Stage 1 scan, with report-volume seasonality clarified on 2026-11-25.

## Scope and HRM standard

The measured population is Service Requests whose `DESCRIPTION`, after trimming surrounding source whitespace, is `Street Surface Maintenance`. Call these **street surface repair requests**, not potholes: the category can include other defects. The scan found 17,210 requests across 10 calendar years and no matching Service Request Custom Fields rows for this type. The available request-to-work-order flag is not an ID link. The data therefore cannot identify pothole size, priority, road class, or the work order that repaired a request.

HRM's [Potholes and Sinkholes page][potholes] (checked 2026-11-24) publishes the following table. It says repair service standards are in effect April 1 through November 30, except where noted.

| Published priority | Published definition | Published timeline |
| --- | --- | --- |
| Priority 1 | At least 25 cm in diameter **and** 8 cm in depth | Arterial and major collector: 7 business days; minor collector: 14; local: 30 |
| Priority 2 | Smaller than Priority 1 | 12 months or as soon as resources permit |

There is an unresolved conflict with HRM's [Pavement Maintenance and Rehabilitation Strategies page][pavement-strategies] (checked 2026-11-24): it classifies Priority 1 by depth of at least 8 cm without the 25 cm diameter condition, describes Priority 2 as depth of 7.9 cm or less, and calls the Priority 2 timeline a 12-month standard on all street classifications. The Potholes and Sinkholes page's FAQ also describes a general 7-to-30-business-day range without reconciling that wording with the Priority 2 table. Record both pages; do not resolve these differences by inference.

These are verified statements published by HRM, not findings about HRM performance. The selected request type is not pothole-specific and cannot be classified against the published dimensions, road classes, or repair-completion event. **Do not calculate or claim compliance with the pothole standard for this dataset.** `DATE_CLOSED` means the request was closed in the system; it does not prove a pothole was repaired.

## Wait and reporting rules

- **Public wait:** whole calendar-date difference, `local DATE_CLOSED - local DATE_INITIATED`, after converting timestamps to `America/Halifax`. A same-local-date closure is zero days. Label this “until the request was closed,” never “until fixed.”
- **Open requests:** include them as right-censored observations through the latest pull date; never treat an open request as a zero-day wait. Implement the Kaplan–Meier-style median and 90th-percentile (“9 in 10”) wait in Stage 3 and validate against a hand-worked test. If the estimator cannot be validated, use the planned reporting-month shares closed within 7, 14, 30, and 90 days, with only sufficiently old cohorts in each denominator.
- **Open-record age:** calendar-date difference from the Halifax-local initiation date to the data-pull date for records whose close date is missing. The oldest age is the maximum of these values and is always paired with the number of records that have no close date. It describes an HRM record, not whether a road issue remains physically present.
- **Elapsed-days helper:** a browser-only calculator for a number supplied by the visitor. It may restate elapsed days and compare them with published aggregate context, but it cannot retrieve an individual request or predict remaining time. Do not persist or transmit the entered value.
- **Headline period:** the last 12 complete calendar months at the pull date. Charts may include all complete months.
- **Request-volume trends:** count initiations by Halifax-local `DATE_INITIATED` and closures by Halifax-local `DATE_CLOSED` as separate event series. Monthly counts cover all complete months. Weekly counts cover the latest 52 complete Monday-start weeks, ending on the last completed Sunday before the pull date; the partial current week is excluded. A closure in the displayed period counts even if its request was initiated earlier. These counts describe recorded volume, not road-condition severity.
- **Report-volume seasonality:** compare average recorded initiations per month for December–March and April–November over the same complete calendar years. Exclude incomplete first/last years and the partial current month; show the included years and number of monthly observations in each base. These request counts do not measure road conditions, repair completion, or crew output.
- **Small samples:** show a statistic only when its base `n >= 30`; otherwise show “too few reports to show” and the count. Every percentage must display its numerator and denominator.
- **Seasons:** April 1–November 30 is the published standard season; December 1–March 31 is winter. Show winter separately and make no standard-based judgement in winter.
- **Data quality:** for duplicate request IDs, keep the earliest valid Halifax-local initiated date; sort missing/invalid dates after valid dates and break ties with the lowest source object ID. Log discarded rows. Exclude closed-before-opened rows from timing but retain them in counts. A missing close date is open/censored; invalid nonblank dates and missing initiated dates are reported as timing exclusions, not silently treated as open. Flag valid closed waits above `Q3 + 1.5 × IQR` as statistical outliers for inspection only; do not remove them from any metric.
- **Districts:** retain `DISTRICT` as supplied. The public site pairs codes 1–16 with the current place labels on HRM's official Districts and Councillors page (checked 2026-11-25); this is a display label only. Historical records are not remapped to current boundaries. Show blank codes as “District not recorded — place unknown”; never infer a place for them.
- **District pages:** numeric routes follow district codes in ascending order. These are not ranks. Keep the source code alongside its current place label. “District not recorded — place unknown” appears in the directory but does not receive an inferred numeric route.

## Business-day and holiday reference

The pothole standard uses “business days” but does not define the term on the service page. HRM's [Holidays Policy][hrm-holidays] (last updated February 8, 2023; checked 2026-11-24) applies to non-union HRM employees, says municipal offices are generally closed, and says many operations remain open and individual business units determine operational needs. It does not establish a Roads Operations calendar or a service-standard counting rule. The [Nova Scotia Holiday Pay page][ns-holidays] lists six paid holidays under the Labour Standards Code; it says Remembrance Day is covered separately. Neither source defines the pothole standard's business-day calculation.

The following is a source-recorded **candidate holiday list**, not a confirmed Roads Operations calendar. Nominal date rules identify calendar dates only. Do not shift weekend holidays to Monday without an applicable official schedule. Before Layer 2 uses any candidate date in a business-day calculation, verify the year-specific date and Roads Operations observance; keep the HRM-policy and Nova Scotia statutory sets distinguishable for sensitivity checks.

| Holiday | Nominal date / rule | Nova Scotia status | Source |
| --- | --- | --- | --- |
| New Year's Day | January 1 | General paid holiday | [HRM policy][hrm-holidays]; [NS holiday pay][ns-holidays] |
| Nova Scotia Heritage Day | Annual date; verify against the official calendar before materializing | General paid holiday | [HRM policy][hrm-holidays]; [NS holiday pay][ns-holidays] |
| Good Friday | Date varies annually | General paid holiday | [HRM policy][hrm-holidays]; [NS holiday pay][ns-holidays] |
| Easter Monday | Monday after Easter Sunday | Not one of the six general paid holidays | [HRM policy][hrm-holidays]; [NS holiday pay][ns-holidays] |
| Victoria Day | Date varies annually | Not one of the six general paid holidays | [HRM policy][hrm-holidays] |
| Canada Day | July 1 | General paid holiday | [HRM policy][hrm-holidays]; [NS holiday pay][ns-holidays] |
| Civic Holiday (Natal Day) | Annual HRM calendar date | Not one of the six general paid holidays | [HRM policy][hrm-holidays] |
| Labour Day | First Monday in September | General paid holiday | [HRM policy][hrm-holidays]; [NS holiday pay][ns-holidays] |
| National Day for Truth and Reconciliation | September 30 | Not one of the six general paid holidays | [HRM policy][hrm-holidays] |
| Thanksgiving Day | Second Monday in October | Not one of the six general paid holidays | [HRM policy][hrm-holidays] |
| Remembrance Day | November 11 | Separate Act; not a general paid holiday under the Labour Standards Code | [HRM policy][hrm-holidays]; [NS Remembrance Day][ns-remembrance] |
| Christmas Day | December 25 | General paid holiday | [HRM policy][hrm-holidays]; [NS holiday pay][ns-holidays] |
| Boxing Day | December 26 | Not one of the six general paid holidays | [HRM policy][hrm-holidays] |
| Other proclaimed general holiday | Date set by proclamation; check each year | Not in the recurring six-holiday list | [HRM policy][hrm-holidays] |

## Sources checked

- HRM, [Potholes and Sinkholes][potholes], checked 2026-11-24.
- HRM, [Pavement Maintenance and Rehabilitation Strategies][pavement-strategies], checked 2026-11-24.
- HRM, [Human Resources: Policies and collective agreements][hrm-policies] and linked [Holidays Policy][hrm-holidays], checked 2026-11-24.
- Nova Scotia, [Holiday Pay][ns-holidays] and [Remembrance Day][ns-remembrance], checked 2026-11-24.

[potholes]: https://www.halifax.ca/transportation/streets-sidewalks/paving-repair/report-a-pothole
[pavement-strategies]: https://www.halifax.ca/transportation/streets-sidewalks/paving-repair/pavement-maintenance-rehabilitation-strategies
[hrm-policies]: https://www.halifax.ca/about-halifax/employment/human-resources-policies-collective-agreements
[hrm-holidays]: https://www.halifax.ca/sites/default/files/documents/about-the-city/employment/29-holidays-policy.pdf
[ns-holidays]: https://novascotia.ca/lae/employmentrights/holidaypay.asp
[ns-remembrance]: https://novascotia.ca/lae/employmentrights/remembrance.asp
