"""API client for the East Lake time tracking endpoints."""

import logging
from datetime import datetime, timedelta

import requests

log = logging.getLogger(__name__)


class APIError(Exception):
    """Raised when an API call fails with a meaningful message."""

    def __init__(self, message: str, status_code: int | None = None):
        self.status_code = status_code
        super().__init__(message)


class TimeTrackingClient:
    """Wraps the /api/time-tracking endpoints for a single portal."""

    def __init__(self, base_url: str, api_key: str, timeout: int = 10):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/time-tracking{path}"

    def _handle_error(self, e: requests.exceptions.HTTPError) -> None:
        """Convert HTTP errors into human-readable APIError."""
        resp = e.response
        if resp is None:
            raise APIError("No response from server") from e

        try:
            body = resp.json()
            detail = body.get("detail", body.get("message", ""))
        except Exception:
            detail = resp.text[:200] if resp.text else ""

        status = resp.status_code
        if status == 401:
            msg = "Authentication failed - check your API key."
        elif status == 403:
            msg = "Permission denied - your key may lack access to this endpoint."
        elif status == 404:
            msg = detail or "Resource not found."
        elif status == 409:
            msg = detail or "Conflict - a timer may already be running."
        elif status == 422:
            msg = f"Invalid request: {detail}" if detail else "Invalid request data."
        elif status >= 500:
            msg = "Server error - try again in a moment."
        else:
            msg = detail or f"Request failed (HTTP {status})."

        raise APIError(msg, status_code=status) from e

    def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            r = self.session.get(self._url(path), params=params, timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as e:
            self._handle_error(e)
        except requests.exceptions.ConnectionError:
            raise APIError("Cannot reach the server - check your connection and URL.")
        except requests.exceptions.Timeout:
            raise APIError("Request timed out - the server may be slow or unreachable.")

    def _post(self, path: str, json_body: dict | None = None) -> dict:
        try:
            r = self.session.post(self._url(path), json=json_body or {}, timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as e:
            self._handle_error(e)
        except requests.exceptions.ConnectionError:
            raise APIError("Cannot reach the server - check your connection and URL.")
        except requests.exceptions.Timeout:
            raise APIError("Request timed out - the server may be slow or unreachable.")

    def _patch(self, path: str, json_body: dict | None = None) -> dict:
        try:
            r = self.session.patch(self._url(path), json=json_body or {}, timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as e:
            self._handle_error(e)
        except requests.exceptions.ConnectionError:
            raise APIError("Cannot reach the server - check your connection and URL.")
        except requests.exceptions.Timeout:
            raise APIError("Request timed out - the server may be slow or unreachable.")

    def _delete(self, path: str) -> dict:
        try:
            r = self.session.delete(self._url(path), timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as e:
            self._handle_error(e)
        except requests.exceptions.ConnectionError:
            raise APIError("Cannot reach the server - check your connection and URL.")
        except requests.exceptions.Timeout:
            raise APIError("Request timed out - the server may be slow or unreachable.")

    # --- Timer controls ---

    def start_timer(self, notes: str = "", hourly_rate: float | None = None) -> dict:
        body = {}
        if notes:
            body["notes"] = notes
        if hourly_rate is not None:
            body["hourly_rate"] = hourly_rate
        return self._post("/start", body)

    def stop_timer(self) -> dict:
        return self._post("/stop")

    def get_active_timer(self) -> dict | None:
        try:
            return self._get("/active")
        except APIError as e:
            if e.status_code == 404:
                return None
            raise

    # --- Entries ---

    def list_entries(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        is_paid: bool | None = None,
    ) -> dict:
        params = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if is_paid is not None:
            params["is_paid"] = str(is_paid).lower()
        return self._get("/entries", params)

    def get_entry(self, entry_id: str) -> dict:
        return self._get(f"/entries/{entry_id}")

    def update_entry(self, entry_id: str, **fields) -> dict:
        return self._patch(f"/entries/{entry_id}", fields)

    def delete_entry(self, entry_id: str) -> dict:
        return self._delete(f"/entries/{entry_id}")

    def mark_paid(self, entry_id: str) -> dict:
        return self._patch(f"/entries/{entry_id}/mark-paid")

    def mark_unpaid(self, entry_id: str) -> dict:
        return self._patch(f"/entries/{entry_id}/mark-unpaid")

    # --- Stats ---

    def get_stats(self, start_date: str | None = None, end_date: str | None = None) -> dict:
        params = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return self._get("/stats", params)

    # --- Health ---

    def health_check(self) -> bool:
        try:
            r = self.session.get(f"{self.base_url}/api/health", timeout=self.timeout)
            return r.status_code == 200
        except Exception:
            return False


def format_duration(start_time_str: str) -> str:
    """Format elapsed time from an ISO start_time string to a human-readable duration."""
    try:
        start_str = start_time_str.replace("Z", "+00:00")
        start = datetime.fromisoformat(start_str)
        now = datetime.now(tz=start.tzinfo)
        delta = now - start
        total_seconds = int(delta.total_seconds())
        if total_seconds < 0:
            return "0m"
        hours, remainder = divmod(total_seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes:02d}m"
        return f"{minutes}m"
    except Exception:
        return "--:--"


def format_hours(duration_hours: float) -> str:
    """Format a decimal hours value into a human-readable string."""
    if duration_hours is None or duration_hours < 0:
        return "--:--"
    hours = int(duration_hours)
    minutes = int((duration_hours - hours) * 60)
    if hours > 0:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def format_entry_line(entry: dict) -> str:
    """Format a time entry into a short menu-friendly string."""
    notes = entry.get("notes", "") or "No notes"
    if len(notes) > 35:
        notes = notes[:32] + "..."

    duration = entry.get("duration_hours")
    if duration is not None:
        dur_str = format_hours(duration)
    elif entry.get("start_time"):
        dur_str = format_duration(entry["start_time"])
    else:
        dur_str = "--"

    amount = entry.get("total_amount")
    amt_str = f"  ${amount:.2f}" if amount is not None else ""

    paid = "  [paid]" if entry.get("is_paid") else ""

    return f"{dur_str}  {notes}{amt_str}{paid}"


def today_range() -> tuple[str, str]:
    """Return (today, today) ISO date strings."""
    today = datetime.now().date().isoformat()
    return today, today


def this_week_range() -> tuple[str, str]:
    """Return (monday, sunday) ISO date strings for the current week."""
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()
