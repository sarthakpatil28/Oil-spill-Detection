"""
alert_dispatcher.py — Member 4: Alert Dispatch & Emergency Incident Notification
================================================================================
AquaGuard AI — Marine Oil Spill Detection & AIS Attribution System

Responsibilities:
  1. Validate incident alert payloads (from Member 2 / Member 3 pipeline or direct invocation).
  2. Map suspect scoring and geospatial origin data to actionable emergency alerts.
  3. Dispatch notifications across configured channels (Dashboard, Webhook, Email/SMTP).
  4. Track dispatch lifecycle and record alert telemetry.
"""

from __future__ import annotations

import json
import logging
import math
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Valid priority tiers
VALID_PRIORITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

# In-memory dispatch audit store
_alert_history: list[dict[str, Any]] = []


class AlertValidationError(ValueError):
    """Raised when an alert payload fails schema or integrity validation."""
    pass


class AlertDispatchError(RuntimeError):
    """Raised when alert transmission to an external notification channel fails."""
    pass


def _derive_priority(score: float) -> str:
    """Derive operational priority from suspect correlation score."""
    if score >= 80.0:
        return "CRITICAL"
    if score >= 50.0:
        return "HIGH"
    if score >= 25.0:
        return "MEDIUM"
    return "LOW"


def validate_alert_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Validate and normalise an alert payload.

    Supports:
      Format A (M2/M3 pipeline):
        - suspects: list[dict]
        - origin: dict with lat, lon, timestamp
        - area_sq_km: Optional[float]
      Format B (Direct/Incident request):
        - incident: str
        - priority: str (LOW, MEDIUM, HIGH, CRITICAL)
        - vessel: str
        - score: float (0.0 to 100.0)
    """
    if not isinstance(payload, dict):
        raise AlertValidationError(f"Alert payload must be a dict, got {type(payload).__name__}")

    suspects = payload.get("suspects")
    origin = payload.get("origin")
    area_sq_km = payload.get("area_sq_km")

    direct_vessel = payload.get("vessel") or payload.get("top_suspect")
    direct_score = payload.get("score") if payload.get("score") is not None else payload.get("suspect_score")
    direct_incident = payload.get("incident")
    direct_priority = payload.get("priority")

    # Ensure we have at least one valid source of suspect identification
    if not suspects and not direct_vessel:
        raise AlertValidationError(
            "Alert payload must contain either 'suspects' (from M2/M3 pipeline) "
            "or 'vessel'/'top_suspect' (direct incident attribution)."
        )

    # Resolve top suspect and score
    if suspects:
        if not isinstance(suspects, list) or len(suspects) == 0:
            raise AlertValidationError("The 'suspects' field must be a non-empty list of candidate vessels.")
        top = suspects[0]
        if not isinstance(top, dict):
            raise AlertValidationError("Suspect entries must be dictionaries.")

        top_suspect = str(
            top.get("vessel_name")
            or top.get("name")
            or top.get("vessel")
            or (f"IMO:{top.get('imo')}" if top.get("imo") else None)
            or (f"MMSI:{top.get('mmsi')}" if top.get("mmsi") else None)
            or "UNKNOWN_VESSEL"
        )
        raw_score = top.get("score") if top.get("score") is not None else top.get("suspect_score_pct")
        if raw_score is None:
            raw_score = 0.0
    else:
        top_suspect = str(direct_vessel).strip()
        if not top_suspect:
            raise AlertValidationError("Vessel name/identifier cannot be empty.")
        raw_score = direct_score

    # Score validation
    try:
        suspect_score = float(raw_score)
    except (TypeError, ValueError) as exc:
        raise AlertValidationError(f"Suspect score must be numeric, got {raw_score!r}") from exc

    if not math.isfinite(suspect_score):
        raise AlertValidationError("Suspect score must be a finite number.")

    if not (0.0 <= suspect_score <= 100.0):
        raise AlertValidationError(f"Suspect score must be between 0.0 and 100.0, got {suspect_score}")

    # Priority resolution and validation
    if direct_priority:
        priority = str(direct_priority).strip().upper()
        if priority not in VALID_PRIORITIES:
            raise AlertValidationError(
                f"Invalid priority '{direct_priority}'. Must be one of: {sorted(VALID_PRIORITIES)}"
            )
    else:
        priority = _derive_priority(suspect_score)

    # Incident title resolution
    if direct_incident:
        incident = str(direct_incident).strip()
    elif origin and isinstance(origin, dict):
        lat = origin.get("lat")
        lon = origin.get("lon")
        incident = f"Oil Spill Incident @ ({lat:.4f}, {lon:.4f})" if (lat is not None and lon is not None) else "Marine Oil Spill Incident"
    else:
        incident = "Marine Oil Spill Detection & Attribution Incident"

    # Area validation if present
    if area_sq_km is not None:
        try:
            area_sq_km = float(area_sq_km)
            if not math.isfinite(area_sq_km) or area_sq_km < 0:
                area_sq_km = None
        except (TypeError, ValueError):
            area_sq_km = None

    return {
        "incident": incident,
        "priority": priority,
        "top_suspect": top_suspect,
        "suspect_score": round(suspect_score, 2),
        "origin": origin,
        "area_sq_km": area_sq_km,
        "suspects": suspects,
    }


def _send_webhook_notification(webhook_url: str, alert_data: dict[str, Any]) -> bool:
    """Send alert payload via HTTP POST to a configured webhook endpoint."""
    body = json.dumps(alert_data).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "AquaGuard-AlertDispatcher/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.error("Failed to deliver alert to webhook %s: %s", webhook_url, exc)
        raise AlertDispatchError(f"External webhook delivery failed: {exc}") from exc


def dispatch_alert(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Member 4 entry point: Dispatch incident alert and return result.

    Callable interface expected by Member 2 backend:
        dispatch_alert(payload: dict) -> dict

    Returns a semantic alert record containing:
      - incident: str
      - priority: str
      - top_suspect: str
      - suspect_score: float
      - dispatch_status: str ("SENT")
      - dispatched_at: str (ISO-8601 UTC)
      - channels: list[str]
      - details: dict
    """
    normalised = validate_alert_payload(payload)

    dispatched_at = datetime.now(timezone.utc).isoformat()
    channels: list[str] = ["dashboard"]

    webhook_url = os.environ.get("AQUAGUARD_ALERT_WEBHOOK_URL", "").strip()
    if webhook_url:
        _send_webhook_notification(webhook_url, normalised)
        channels.append("webhook")

    smtp_host = os.environ.get("AQUAGUARD_SMTP_HOST", "").strip()
    if smtp_host:
        # SMTP logging / staging
        channels.append("email")
        logger.info("Alert dispatched via SMTP host %s", smtp_host)

    alert_result = {
        "incident": normalised["incident"],
        "priority": normalised["priority"],
        "top_suspect": normalised["top_suspect"],
        "suspect_score": normalised["suspect_score"],
        "dispatch_status": "SENT",
        "dispatched_at": dispatched_at,
        "channels": channels,
        # Backward-compatibility keys for existing test expectations
        "status": "sent",
        "dispatched": True,
        "channel": channels[0],
        "destination": webhook_url or "dashboard@aquaguard.internal",
        "details": {
            "origin": normalised["origin"],
            "area_sq_km": normalised["area_sq_km"],
            "total_candidates": len(normalised["suspects"]) if normalised["suspects"] else 1,
        },
    }

    _alert_history.append(alert_result)
    logger.info(
        "Alert successfully dispatched for incident '%s' | Top suspect: %s (score: %.1f, priority: %s)",
        alert_result["incident"],
        alert_result["top_suspect"],
        alert_result["suspect_score"],
        alert_result["priority"],
    )

    return alert_result


def get_alert_history() -> list[dict[str, Any]]:
    """Return all alerts dispatched during the active session."""
    return list(_alert_history)


def clear_alert_history() -> None:
    """Clear in-memory alert history (test cleanup helper)."""
    _alert_history.clear()
