"""CSV export for time tracking entries."""

import csv
import os
from datetime import datetime


def generate_csv(entries: list[dict], filepath: str) -> str:
    """Write time entries to a CSV file. Returns the filepath."""
    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Date", "Start", "End", "Hours", "Rate", "Amount", "Notes", "Paid",
        ])
        for e in entries:
            start = e.get("start_time", "")
            end = e.get("end_time", "")
            date = _parse_date(start)
            start_t = _parse_time(start)
            end_t = _parse_time(end)
            hours = e.get("duration_hours") or 0
            rate = e.get("hourly_rate") or 0
            amount = e.get("total_amount") or 0
            notes = e.get("notes", "") or ""
            paid = "Yes" if e.get("is_paid") else "No"
            writer.writerow([
                date, start_t, end_t,
                f"{hours:.2f}", f"{rate:.2f}", f"{amount:.2f}",
                notes, paid,
            ])
    return filepath


def default_export_path(portal_name: str, start_date: str, end_date: str) -> str:
    """Generate a default export filepath on the Desktop."""
    safe_name = portal_name.replace(" ", "-").replace("/", "-")
    filename = f"eastlake-{safe_name}-{start_date}-to-{end_date}.csv"
    return os.path.join(os.path.expanduser("~/Desktop"), filename)


def _parse_date(iso_str: str) -> str:
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except Exception:
        return ""


def _parse_time(iso_str: str) -> str:
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00")).strftime("%H:%M")
    except Exception:
        return ""
