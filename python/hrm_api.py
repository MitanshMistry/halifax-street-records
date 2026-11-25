"""Download helpers for HRM's ArcGIS feature services."""
import json
import time
from pathlib import Path

import requests

BASE = "https://services2.arcgis.com/11XBiaBYA9Ep0yNJ/arcgis/rest/services"
TABLES = {
    "service_requests": "Cityworks_Service_Requests",
    "work_orders": "Cityworks_Work_Orders",
    "wo_custom_fields": "Cityworks_Work_Orders_Custom_Fields",
    "sr_custom_fields": "Cityworks_Service_Requests_Custom_Fields",
}
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
RETRYABLE_CODES = {429, 500, 502, 503, 504}
USER_AGENT = "HRM-Pothole-Portfolio/1.0 (read-only open-data scan)"


def query_url(service):
    return f"{BASE}/{service}/FeatureServer/0/query"


def layer_url(service):
    return f"{BASE}/{service}/FeatureServer/0"


def _get(session, url, params, retries=5):
    for attempt in range(retries):
        try:
            response = session.get(
                url,
                params=params,
                timeout=60,
                headers={"User-Agent": USER_AGENT},
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            if attempt == retries - 1:
                raise
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is not None and status not in RETRYABLE_CODES and status < 500:
                raise
            time.sleep(2 ** attempt)
            continue

        if not isinstance(data, dict):
            raise RuntimeError("ArcGIS returned a response that was not a JSON object.")
        if "error" in data:
            error = data["error"]
            code = error.get("code") if isinstance(error, dict) else None
            try:
                code = int(code)
            except (TypeError, ValueError):
                code = None
            if code in RETRYABLE_CODES and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            message = error.get("message", "Unknown ArcGIS error") if isinstance(error, dict) else str(error)
            raise RuntimeError(f"ArcGIS error {code}: {message}")
        return data


def layer_paging_info(service, session):
    """Read the layer's actual object ID field and server page limit."""
    data = _get(session, layer_url(service), {"f": "json"})
    fields = data.get("fields") or []
    field_names = {field.get("name") for field in fields}
    object_id = data.get("objectIdField") or data.get("objectIdFieldName")
    if object_id not in field_names:
        object_id = next(
            (field.get("name") for field in fields if field.get("type") == "esriFieldTypeOID"),
            None,
        )
    try:
        page_size = int(data.get("maxRecordCount"))
    except (TypeError, ValueError):
        page_size = 0
    if not object_id:
        raise RuntimeError(f"ArcGIS layer metadata has no object ID field for {service}.")
    if page_size <= 0:
        raise RuntimeError(f"ArcGIS layer metadata has no valid maxRecordCount for {service}.")
    return object_id, page_size


def fetch_all(service, session=None, delay=0.5, progress=None):
    """Fetch every row using the layer's object ID and maximum record count."""
    session = session or requests.Session()
    url = query_url(service)
    object_id, page_size = layer_paging_info(service, session)
    base = {"where": "1=1", "outFields": "*", "returnGeometry": "false", "f": "json"}
    rows, offset = [], 0
    page_number = 0

    while True:
        params = dict(
            base,
            resultOffset=offset,
            resultRecordCount=page_size,
            orderByFields=f"{object_id} ASC",
        )
        data = _get(session, url, params)
        features = data.get("features", [])
        if not features:
            if data.get("exceededTransferLimit"):
                raise RuntimeError(f"ArcGIS returned an empty page while more rows were reported for {service}.")
            break

        for feature in features:
            attributes = feature.get("attributes")
            if attributes is None:
                attributes = feature.get("properties")
            if not isinstance(attributes, dict):
                raise RuntimeError(f"ArcGIS returned a feature without attributes for {service}.")
            rows.append(attributes)

        offset += len(features)
        page_number += 1
        if progress:
            progress(len(rows), page_number)
        if not data.get("exceededTransferLimit"):
            break
        time.sleep(max(delay, 0))

    return rows


def load_table(name, refresh=False, progress=None):
    """Return raw row attributes from cache or fetch and atomically cache the full table."""
    if name not in TABLES:
        raise KeyError(f"Unknown HRM table: {name}")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache = RAW_DIR / f"{name}.json"
    if cache.exists() and not refresh:
        rows = json.loads(cache.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError(f"Cached HRM data is not a list of row objects: {cache.name}")
        return rows

    rows = fetch_all(TABLES[name], progress=progress)
    temporary = cache.with_suffix(".json.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(rows, handle, ensure_ascii=False, separators=(",", ":"))
        temporary.replace(cache)
    finally:
        if temporary.exists():
            temporary.unlink()
    return rows
