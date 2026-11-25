"""FAKE server fixtures only. These tests do not touch the real HRM service."""
import pandas as pd
import pytest

from dates import ms_to_halifax
from hrm_api import fetch_all


class FakeResp:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append((url, dict(params)))
        if url.endswith("/FeatureServer/0"):
            return FakeResp(
                {
                    "objectIdField": "ROW_KEY",
                    "maxRecordCount": 2,
                    "fields": [{"name": "ROW_KEY", "type": "esriFieldTypeOID"}],
                }
            )
        offset = params["resultOffset"]
        rows = self.pages.get(offset, [])
        more = (offset + len(rows)) in self.pages
        return FakeResp(
            {
                "features": [{"attributes": row} for row in rows],
                "exceededTransferLimit": more,
            }
        )


def test_pages_in_order_using_metadata_id_and_server_limit():
    session = FakeSession({0: [{"a": 1}, {"a": 2}], 2: [{"a": 3}]})

    rows = fetch_all("FakeTable", session=session, delay=0)

    assert [row["a"] for row in rows] == [1, 2, 3]
    query_calls = [params for url, params in session.calls if url.endswith("/query")]
    assert [params["resultOffset"] for params in query_calls] == [0, 2]
    assert all(params["resultRecordCount"] == 2 for params in query_calls)
    assert all(params["orderByFields"] == "ROW_KEY ASC" for params in query_calls)
    assert all(params["returnGeometry"] == "false" for params in query_calls)
    assert all(params["f"] == "json" for params in query_calls)


class MissingIdSession(FakeSession):
    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append((url, dict(params)))
        if url.endswith("/FeatureServer/0"):
            return FakeResp({"maxRecordCount": 10, "fields": [{"name": "NAME", "type": "esriFieldTypeString"}]})
        return super().get(url, params, timeout, headers)


def test_fails_when_layer_has_no_object_id():
    with pytest.raises(RuntimeError, match="no object ID field"):
        fetch_all("FakeTable", session=MissingIdSession({}), delay=0)


class EmptyTransferSession(FakeSession):
    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append((url, dict(params)))
        if url.endswith("/FeatureServer/0"):
            return FakeResp(
                {
                    "objectIdField": "ROW_KEY",
                    "maxRecordCount": 2,
                    "fields": [{"name": "ROW_KEY", "type": "esriFieldTypeOID"}],
                }
            )
        return FakeResp({"features": [], "exceededTransferLimit": True})


def test_fails_on_empty_page_when_server_reports_more_rows():
    with pytest.raises(RuntimeError, match="empty page"):
        fetch_all("FakeTable", session=EmptyTransferSession({}), delay=0)


def test_ms_to_halifax_standard_time():
    out = ms_to_halifax(pd.Series([1700000000000]))
    assert str(out.iloc[0]) == "2023-11-14 18:13:20-04:00"


def test_ms_to_halifax_changes_the_date():
    ms = int(pd.Timestamp("2023-07-01 02:30", tz="UTC").timestamp() * 1000)
    assert ms_to_halifax(pd.Series([ms])).iloc[0].date().isoformat() == "2023-06-30"


def test_missing_dates_become_nat():
    assert ms_to_halifax(pd.Series([None])).isna().all()
