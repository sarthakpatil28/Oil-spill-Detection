"""
test_alert_dispatcher.py — Member 4 Alert Dispatcher Tests
==========================================================
AquaGuard AI — SIH PS 143: Member 4 Verification

Test Categories:
  1. Import & module structure
  2. Direct alert payload validation (Format B: incident, priority, vessel, score)
  3. M2/M3 pipeline alert payload validation (Format A: suspects, origin, area_sq_km)
  4. Validation failure handling (invalid scores, missing fields, invalid priority)
  5. Priority auto-derivation from suspect score
  6. Dispatch execution & alert history tracking
  7. External webhook transport (success & controlled failure)
  8. Integration with FastAPI /alert endpoint
"""

import math
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure backend directory is in sys.path
_BACKEND = str(Path(__file__).resolve().parent.parent / "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import alert_dispatcher


class TestImportsAndModuleStructure:
    """Category 1: Import and public callable verification."""

    def test_alert_dispatcher_importable(self):
        import alert_dispatcher
        assert callable(alert_dispatcher.dispatch_alert)
        assert callable(alert_dispatcher.validate_alert_payload)
        assert callable(alert_dispatcher.get_alert_history)

    def test_alert_dispatcher_location(self):
        import alert_dispatcher
        file_path = Path(alert_dispatcher.__file__).resolve()
        assert file_path.parent.name == "backend"
        assert file_path.name == "alert_dispatcher.py"


class TestDirectPayloadValidation:
    """Category 2: Direct alert payload schema (Format B)."""

    def test_valid_direct_payload(self):
        payload = {
            "incident": "Arabian Sea Oil Spill",
            "priority": "HIGH",
            "vessel": "VANGUARD",
            "score": 95.3,
        }
        res = alert_dispatcher.validate_alert_payload(payload)
        assert res["incident"] == "Arabian Sea Oil Spill"
        assert res["priority"] == "HIGH"
        assert res["top_suspect"] == "VANGUARD"
        assert res["suspect_score"] == 95.3

    def test_valid_direct_payload_with_top_suspect_alias(self):
        payload = {
            "top_suspect": "OCEAN STAR",
            "suspect_score": 71.8,
        }
        res = alert_dispatcher.validate_alert_payload(payload)
        assert res["top_suspect"] == "OCEAN STAR"
        assert res["suspect_score"] == 71.8
        assert res["priority"] == "HIGH"  # Derived from 71.8


class TestPipelinePayloadValidation:
    """Category 3: M2/M3 pipeline alert payload schema (Format A)."""

    def test_valid_pipeline_payload(self):
        payload = {
            "suspects": [
                {
                    "rank": 1,
                    "vessel_name": "VANGUARD",
                    "imo": "9182734",
                    "score": 88.5,
                    "risk_tier": "CRITICAL",
                },
                {
                    "rank": 2,
                    "vessel_name": "OCEAN STAR",
                    "score": 62.0,
                },
            ],
            "origin": {
                "lat": 15.62,
                "lon": 68.42,
                "timestamp": "2025-05-15T08:30:00Z",
            },
            "area_sq_km": 12.4,
        }
        res = alert_dispatcher.validate_alert_payload(payload)
        assert res["top_suspect"] == "VANGUARD"
        assert res["suspect_score"] == 88.5
        assert res["priority"] == "CRITICAL"
        assert res["area_sq_km"] == 12.4
        assert "15.62" in res["incident"]

    def test_pipeline_fallback_to_imo_when_name_missing(self):
        payload = {
            "suspects": [
                {
                    "rank": 1,
                    "imo": "9182734",
                    "score": 45.0,
                }
            ],
            "origin": {"lat": 10.0, "lon": 20.0},
        }
        res = alert_dispatcher.validate_alert_payload(payload)
        assert res["top_suspect"] == "IMO:9182734"
        assert res["priority"] == "MEDIUM"


class TestValidationFailures:
    """Category 4: Controlled error handling on invalid inputs."""

    def test_rejects_non_dict_payload(self):
        with pytest.raises(alert_dispatcher.AlertValidationError):
            alert_dispatcher.validate_alert_payload("not-a-dict")

    def test_rejects_empty_payload(self):
        with pytest.raises(alert_dispatcher.AlertValidationError):
            alert_dispatcher.validate_alert_payload({})

    def test_rejects_empty_suspects_list(self):
        with pytest.raises(alert_dispatcher.AlertValidationError):
            alert_dispatcher.validate_alert_payload({"suspects": []})

    def test_rejects_negative_score(self):
        with pytest.raises(alert_dispatcher.AlertValidationError):
            alert_dispatcher.validate_alert_payload({"vessel": "V1", "score": -5.0})

    def test_rejects_score_over_100(self):
        with pytest.raises(alert_dispatcher.AlertValidationError):
            alert_dispatcher.validate_alert_payload({"vessel": "V1", "score": 105.0})

    def test_rejects_non_numeric_score(self):
        with pytest.raises(alert_dispatcher.AlertValidationError):
            alert_dispatcher.validate_alert_payload({"vessel": "V1", "score": "abc"})

    def test_rejects_nan_score(self):
        with pytest.raises(alert_dispatcher.AlertValidationError):
            alert_dispatcher.validate_alert_payload({"vessel": "V1", "score": float("nan")})

    def test_rejects_invalid_priority(self):
        with pytest.raises(alert_dispatcher.AlertValidationError):
            alert_dispatcher.validate_alert_payload({
                "vessel": "V1",
                "score": 50.0,
                "priority": "URGENT",  # Invalid priority
            })


class TestPriorityDerivation:
    """Category 5: Priority auto-derivation thresholds."""

    @pytest.mark.parametrize("score,expected", [
        (85.0, "CRITICAL"),
        (80.0, "CRITICAL"),
        (79.9, "HIGH"),
        (50.0, "HIGH"),
        (49.9, "MEDIUM"),
        (25.0, "MEDIUM"),
        (24.9, "LOW"),
        (0.0, "LOW"),
    ])
    def test_priority_tiers(self, score, expected):
        assert alert_dispatcher._derive_priority(score) == expected


class TestDispatchExecution:
    """Category 6: Successful dispatch execution and audit tracking."""

    def setup_method(self):
        alert_dispatcher.clear_alert_history()

    def test_dispatch_direct_alert(self):
        payload = {
            "incident": "Gulf Spill",
            "priority": "CRITICAL",
            "vessel": "VANGUARD",
            "score": 92.0,
        }
        res = alert_dispatcher.dispatch_alert(payload)
        assert res["dispatch_status"] == "SENT"
        assert res["top_suspect"] == "VANGUARD"
        assert res["suspect_score"] == 92.0
        assert res["priority"] == "CRITICAL"
        assert "dashboard" in res["channels"]
        assert "dispatched_at" in res

        # Check history recorded
        history = alert_dispatcher.get_alert_history()
        assert len(history) == 1
        assert history[0]["top_suspect"] == "VANGUARD"

    def test_dispatch_pipeline_alert(self):
        payload = {
            "suspects": [{"vessel_name": "TITAN", "score": 75.0}],
            "origin": {"lat": 28.5, "lon": -89.2},
            "area_sq_km": 5.2,
        }
        res = alert_dispatcher.dispatch_alert(payload)
        assert res["dispatch_status"] == "SENT"
        assert res["top_suspect"] == "TITAN"
        assert res["suspect_score"] == 75.0
        assert res["priority"] == "HIGH"
        assert res["details"]["area_sq_km"] == 5.2


class TestExternalNotificationTransport:
    """Category 7: External notification transports (webhook / email)."""

    def test_webhook_dispatch_success(self, monkeypatch):
        monkeypatch.setenv("AQUAGUARD_ALERT_WEBHOOK_URL", "https://alerts.test.local/webhook")

        with patch("alert_dispatcher._send_webhook_notification", return_value=True) as mock_send:
            res = alert_dispatcher.dispatch_alert({"vessel": "V1", "score": 80.0})
            assert "webhook" in res["channels"]
            assert mock_send.called

    def test_webhook_dispatch_failure(self, monkeypatch):
        monkeypatch.setenv("AQUAGUARD_ALERT_WEBHOOK_URL", "https://invalid.webhook.unreachable")

        with patch("alert_dispatcher._send_webhook_notification", side_effect=alert_dispatcher.AlertDispatchError("Network down")):
            with pytest.raises(alert_dispatcher.AlertDispatchError):
                alert_dispatcher.dispatch_alert({"vessel": "V1", "score": 80.0})


class TestFastAPIAlertEndpointIntegration:
    """Category 8: Integration with FastAPI backend /alert route."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        import main
        yield TestClient(main.app)
        main.latest_origin = None
        main.latest_suspects = None
        main.latest_segment = None
        main.latest_drift = None

    def test_alert_endpoint_with_runtime_pipeline_state(self, client):
        import main
        main.latest_origin = {"lat": 36.7, "lon": -15.0, "timestamp": "2024-06-01T08:30:00Z"}
        main.latest_suspects = [
            {"vessel_name": "Vanguard", "imo": "9182734", "score": 76.11, "risk_tier": "HIGH"}
        ]
        main.latest_segment = {"area_sq_km": 2.5}

        response = client.post("/alert", json={})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["alert"]["top_suspect"] == "Vanguard"
        assert data["alert"]["suspect_score"] == 76.11
        assert data["alert"]["dispatch_status"] == "SENT"

    def test_alert_endpoint_with_explicit_body(self, client):
        import main
        body = {
            "suspects": [{"vessel_name": "Atlantic Runner", "score": 42.0}],
            "origin": {"lat": 37.1, "lon": -14.8, "timestamp": "2024-06-01T08:30:00Z"},
            "area_sq_km": 1.8,
        }
        response = client.post("/alert", json=body)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["alert"]["top_suspect"] == "Atlantic Runner"
        assert data["alert"]["suspect_score"] == 42.0

    def test_alert_endpoint_rejects_when_no_suspects_or_origin(self, client):
        import main
        main.latest_origin = None
        main.latest_suspects = None

        response = client.post("/alert", json={})
        assert response.status_code == 400
        assert "No suspects available" in response.json()["detail"]
