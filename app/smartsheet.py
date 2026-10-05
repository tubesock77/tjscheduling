"""Smartsheet API client for the TRADER JOES sheet."""
import requests

API = "https://api.smartsheet.com/2.0"


class SmartsheetError(Exception):
    pass


class SmartsheetClient:
    def __init__(self, token, sheet_id):
        self.token, self.sheet_id = token, sheet_id
        self._columns = None  # title -> id

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def fetch_rows(self):
        """Return list of dicts keyed by column title, plus '_row_id'."""
        r = requests.get(f"{API}/sheets/{self.sheet_id}", headers=self._headers(), timeout=60)
        if r.status_code != 200:
            raise SmartsheetError(f"Sheet read failed: {r.status_code} {r.text[:300]}")
        sheet = r.json()
        self._columns = {c["title"].strip(): c["id"] for c in sheet["columns"]}
        by_id = {v: k for k, v in self._columns.items()}
        rows = []
        for row in sheet.get("rows", []):
            d = {"_row_id": str(row["id"])}
            for cell in row.get("cells", []):
                title = by_id.get(cell["columnId"])
                if title:
                    d[title] = cell.get("value")
            rows.append(d)
        return rows

    def update_row(self, row_id, values):
        """values: {column title: value}."""
        if self._columns is None:
            self.fetch_rows()
        cells = []
        for title, value in values.items():
            if title not in self._columns:
                raise SmartsheetError(f"Column '{title}' not found in sheet")
            cells.append({"columnId": self._columns[title], "value": value})
        r = requests.put(f"{API}/sheets/{self.sheet_id}/rows", headers=self._headers(),
                         json=[{"id": int(row_id), "cells": cells}], timeout=60)
        if r.status_code != 200:
            raise SmartsheetError(f"Row update failed: {r.status_code} {r.text[:300]}")


class DemoSmartsheet:
    def __init__(self):
        self.writes = []

    def fetch_rows(self):
        return []

    def update_row(self, row_id, values):
        self.writes.append((row_id, values))
