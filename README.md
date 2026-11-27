# Halifax Street Records

[Visit the live site](https://mitanshmistry.github.io/halifax-street-records/) · [View the source on GitHub](https://github.com/MitanshMistry/halifax-street-records)

Halifax Street Records summarizes past HRM “Street Surface Maintenance” reports, including how long it typically took for a close date to be recorded, how many records have no close date, and when reports came in.

## Features

- View an All of HRM summary and pages for each of the 16 numeric district codes.
- Explore estimates of recorded closure times, with the sample size and reporting period shown.
- See records without a close date, their age groups, and monthly and weekly report counts.
- Find sourced guidance about reporting a road problem, road maintenance responsibility, and vehicle damage.
- Read about the data, methods, and limitations behind the summaries.

## Current Snapshot

For All of HRM, the estimated typical time by which a close date had been recorded for about half of past reports was **1 calendar day**. For about 9 in 10 reports, it was **4 days**. The estimates cover **5,076 reports** started from November 1, 2025 to October 31, 2026.

The data was downloaded on **November 24, 2026**. A recorded close date does not confirm that a repair was completed. Records without a close date are counted only up to the download date; they cannot predict when an individual report will close.

The selected HRM category is broader than potholes. The project cannot determine whether HRM met its pothole repair standard: the available data does not reliably link a report to the work done on the road and does not identify pothole dimensions or road class.

## Data Source

The pipeline uses four public HRM Cityworks datasets:

- [Service Requests](https://services2.arcgis.com/11XBiaBYA9Ep0yNJ/arcgis/rest/services/Cityworks_Service_Requests/FeatureServer/0)
- [Work Orders](https://services2.arcgis.com/11XBiaBYA9Ep0yNJ/arcgis/rest/services/Cityworks_Work_Orders/FeatureServer/0)
- [Work Orders Custom Fields](https://services2.arcgis.com/11XBiaBYA9Ep0yNJ/arcgis/rest/services/Cityworks_Work_Orders_Custom_Fields/FeatureServer/0)
- [Service Requests Custom Fields](https://services2.arcgis.com/11XBiaBYA9Ep0yNJ/arcgis/rest/services/Cityworks_Service_Requests_Custom_Fields/FeatureServer/0)

Contains information licenced under the Open Government Licence—Halifax.

## Technology

- **Data pipeline:** Python
- **Website:** Static HTML, CSS, inline SVG, and vanilla JavaScript
- **Hosting:** GitHub Pages

The published site is a static snapshot, not an HRM service, live data feed, or individual request tracker. It is an independent project and is not run by HRM.

## Getting Started

### Requirements

- Python 3.10 or newer

### Install

From the project root, create a virtual environment and install the Python dependencies:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r python\requirements.txt
```

### Run the Tests and Build the Site

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe python\build_site.py
```

The site is generated from the committed aggregate data in `docs/data/`.

### Refresh the Data

To download current source data from HRM and recalculate the aggregates:

```powershell
.\.venv\Scripts\python.exe python\pipeline.py --refresh
.\.venv\Scripts\python.exe python\build_site.py
```

Raw downloaded records stay in the local, Git-ignored `data/raw/` folder. The pipeline writes aggregate-only JSON to `docs/data/`; it does not publish addresses, coordinates, written comments, names, contact details, or request IDs.

### Preview Locally

```powershell
.\.venv\Scripts\python.exe -m http.server 8000 --directory docs
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/).

## Project Structure

```text
python/           Data download, processing, and site-generation scripts
tests/            Python tests
project/          Definitions, requirements, reconciliation, and scan notes
data/raw/         Local downloaded records; Git-ignored
docs/             Website pages, styles, scripts, screenshots, and aggregate data
PLAN.md           Project build plan
```

## Method and Limitations

The pipeline selects the “Street Surface Maintenance” category, converts report and close timestamps to Halifax time, and counts calendar days between the two dates. It estimates typical and 9-in-10 recorded closure times while accounting for reports that have no close date yet. District estimates are shown only with at least 30 reports; smaller samples use the All of HRM estimate.

A missing close date does not prove that a road problem is still present. A recorded close date does not confirm a repair was completed. The results describe past records and should not be used to predict the outcome of an individual report.

For more detail, see [the requirements](project/requirements.md), [definitions](project/definitions.md), and [data reconciliation](project/reconciliation.md).
