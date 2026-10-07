"""
AquaGuard AI — Backend Test Suite
Member 2 numerical tests: anomaly (§76), drift (§77-78), georeferencing (§79).

CONTRACT §76-80, §94
"""

from __future__ import annotations

import math
import sys
import os

# Ensure backend is importable when the test runner does not add the project root.
_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "backend"))
_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
for _candidate in (_BACKEND, _ROOT):
    if os.path.isdir(_candidate) and _candidate not in sys.path:
        sys.path.insert(0, _candidate)

# pyright: reportMissingImports=false
import pytest
from anomaly_detector import (
    detect_anomaly,
    _compute_sog_drop,
    _compute_cog_change,
    SOG_DROP_THRESHOLD_KNOTS,
    COG_CHANGE_THRESHOLD_DEG,
)
from drift_engine import (
    calculate_hindcast,
    calculate_forecast,
    DriftValidationError,
    EnvironmentConventionError,
    M_PER_DEG_LAT,
    DT_SECONDS,
    FORECAST_HOURS,
)


# ===========================================================================
# ANOMALY TESTS — contract §76
# ===========================================================================

class TestSOGDrop:
    """§13: sog_drop = previous_sog - current_sog (signed, not abs)."""

    def test_basic_drop(self):
        assert _compute_sog_drop(14.0, 2.0) == pytest.approx(12.0)

    def test_speed_increase_is_not_drop(self):
        """A speed increase must yield a negative drop — not an anomaly."""
        drop = _compute_sog_drop(2.0, 14.0)
        assert drop == pytest.approx(-12.0)
        assert drop < SOG_DROP_THRESHOLD_KNOTS

    def test_exact_threshold(self):
        assert _compute_sog_drop(10.0, 2.0) == pytest.approx(8.0)  # exactly threshold


class TestCOGChange:
    """§14: wraparound must be handled correctly."""

    def test_359_to_1(self):
        """Contract §76 TEST E: 359 -> 1 = 2°"""
        assert _compute_cog_change(359.0, 1.0) == pytest.approx(2.0)

    def test_1_to_359(self):
        """Contract §76 TEST F: 1 -> 359 = 2°"""
        assert _compute_cog_change(1.0, 359.0) == pytest.approx(2.0)

    def test_large_turn(self):
        assert _compute_cog_change(0.0, 180.0) == pytest.approx(180.0)

    def test_no_change(self):
        assert _compute_cog_change(90.0, 90.0) == pytest.approx(0.0)

    def test_45_deg(self):
        assert _compute_cog_change(90.0, 135.0) == pytest.approx(45.0)

    def test_44_deg_no_anomaly(self):
        change = _compute_cog_change(90.0, 134.0)
        assert change < COG_CHANGE_THRESHOLD_DEG


class TestDetectAnomaly:
    """Full anomaly record tests — contract §76."""

    def _make_kwargs(self, prev_sog, curr_sog, dist=10.0, prev_cog=180.0, curr_cog=182.0):
        return dict(
            previous_sog=prev_sog,
            current_sog=curr_sog,
            previous_cog=prev_cog,
            current_cog=curr_cog,
            lat=36.8,
            lon=-15.0,
            time_utc="2024-06-01T08:30:00+00:00",
            imo="9182734",
            mmsi="345678902",
            vessel_type="Tanker",
            distance_to_shore_km=dist,
        )

    def test_A_sog12_shore10(self):
        """TEST A: prev=14, curr=2, shore=10 → sog_drop=12, sog_anomaly=True, high=True"""
        r = detect_anomaly(**self._make_kwargs(14.0, 2.0, dist=10.0))
        assert r["sog_drop_knots"] == pytest.approx(12.0)
        assert r["sog_anomaly"] is True
        assert r["high_severity"] is True

    def test_B_sog12_shore3(self):
        """TEST B: prev=14, curr=2, shore=3 → sog_anomaly=True, high=False"""
        r = detect_anomaly(**self._make_kwargs(14.0, 2.0, dist=3.0))
        assert r["sog_anomaly"] is True
        assert r["high_severity"] is False

    def test_C_sog_drop_exactly8_curr6(self):
        """TEST C: prev=14, curr=6, shore=10 → sog_drop=8, sog_anomaly=True, high=False (curr>=3)"""
        r = detect_anomaly(**self._make_kwargs(14.0, 6.0, dist=10.0))
        assert r["sog_drop_knots"] == pytest.approx(8.0)
        assert r["sog_anomaly"] is True
        assert r["high_severity"] is False  # current_sog=6 >= 3

    def test_D_no_shore_distance(self):
        """TEST D: prev=10, curr=1, shore=None → sog_anomaly=True, high=False"""
        r = detect_anomaly(**self._make_kwargs(10.0, 1.0, dist=None))
        assert r["sog_anomaly"] is True
        assert r["high_severity"] is False

    def test_cog_anomaly_alone_no_high(self):
        """COG anomaly alone must NOT set high_severity."""
        r = detect_anomaly(
            previous_sog=5.0, current_sog=4.8,
            previous_cog=0.0, current_cog=90.0,
            lat=36.0, lon=-15.0,
            time_utc="2024-06-01T08:30:00+00:00",
            imo=None, mmsi="111",
            vessel_type=None,
            distance_to_shore_km=10.0,
        )
        assert r["cog_anomaly"] is True
        assert r["sog_anomaly"] is False
        assert r["high_severity"] is False

    def test_roi_is_vessel_position(self):
        """ROI must be the anomalous vessel position (§18)."""
        r = detect_anomaly(**self._make_kwargs(14.0, 2.0, dist=10.0))
        assert r["roi"]["lat"] == pytest.approx(36.8)
        assert r["roi"]["lon"] == pytest.approx(-15.0)

    def test_speed_increase_not_anomaly(self):
        """A speed increase must NOT trigger sog_anomaly."""
        r = detect_anomaly(**self._make_kwargs(2.0, 14.0, dist=10.0))
        assert r["sog_anomaly"] is False

    def test_reasons_populated(self):
        r = detect_anomaly(**self._make_kwargs(14.0, 2.0, dist=10.0))
        assert len(r["reasons"]) >= 2  # at least SOG + HIGH reason


# ===========================================================================
# DRIFT TESTS — contract §77
# ===========================================================================

_ZERO_ENV_UV = {"wind_U": 0.0, "wind_V": 0.0, "current_U": 0.0, "current_V": 0.0}
_NORTH_1MS = {"wind_U": 0.0, "wind_V": 0.0, "current_U": 0.0, "current_V": 1.0}
_EAST_1MS  = {"wind_U": 0.0, "wind_V": 0.0, "current_U": 1.0, "current_V": 0.0}

_OBS_TS = "2024-06-01T08:30:00+00:00"
_OBS_LAT = 36.8
_OBS_LON = -15.0


class TestHindcast:
    """§77, §41-43."""

    def test_A_zero_env_unchanged(self):
        """TEST A: wind=0, current=0 → origin same as observation."""
        r = calculate_hindcast(_OBS_LAT, _OBS_LON, _OBS_TS, _ZERO_ENV_UV, elapsed_hours=1.0)
        assert r["origin_lat"] == pytest.approx(_OBS_LAT)
        assert r["origin_lon"] == pytest.approx(_OBS_LON)

    def test_B_current_north_1ms_1h(self):
        """TEST B: current=1 m/s North, 1h → lat decreases by ~0.03243°"""
        r = calculate_hindcast(_OBS_LAT, _OBS_LON, _OBS_TS, _NORTH_1MS, elapsed_hours=1.0)
        expected_delta_lat = (1.0 * 3600.0) / M_PER_DEG_LAT  # ≈ 0.032432°
        assert (_OBS_LAT - r["origin_lat"]) == pytest.approx(expected_delta_lat, rel=1e-4)

    def test_C_current_east_1ms(self):
        """TEST C: current=1 m/s East → eastward displacement, lat unchanged."""
        r = calculate_hindcast(_OBS_LAT, _OBS_LON, _OBS_TS, _EAST_1MS, elapsed_hours=1.0)
        assert r["origin_lat"] == pytest.approx(_OBS_LAT, abs=1e-8)
        lat_rad = math.radians(_OBS_LAT)
        expected_delta_lon = (1.0 * 3600.0) / (M_PER_DEG_LAT * math.cos(lat_rad))
        assert (_OBS_LON - r["origin_lon"]) == pytest.approx(expected_delta_lon, rel=1e-4)

    def test_D_origin_timestamp(self):
        """TEST D: elapsed=3h → origin_timestamp = obs - 3h."""
        from datetime import datetime, timezone, timedelta
        r = calculate_hindcast(_OBS_LAT, _OBS_LON, _OBS_TS, _ZERO_ENV_UV, elapsed_hours=3.0)
        obs_dt = datetime.fromisoformat(_OBS_TS)
        expected = (obs_dt - timedelta(hours=3)).astimezone(timezone.utc).isoformat()
        assert r["origin_timestamp"] == expected

    def test_F_fractional_elapsed(self):
        """TEST F: elapsed=2.25h → exact 2.25h displacement."""
        from datetime import datetime, timezone, timedelta
        r = calculate_hindcast(_OBS_LAT, _OBS_LON, _OBS_TS, _NORTH_1MS, elapsed_hours=2.25)
        total_s = 2.25 * 3600.0
        expected_delta = total_s / M_PER_DEG_LAT
        assert (_OBS_LAT - r["origin_lat"]) == pytest.approx(expected_delta, rel=1e-4)

    def test_G_elapsed_zero(self):
        """TEST G: elapsed=0 → same coordinate, same timestamp."""
        from datetime import datetime, timezone
        r = calculate_hindcast(_OBS_LAT, _OBS_LON, _OBS_TS, _ZERO_ENV_UV, elapsed_hours=0)
        assert r["origin_lat"] == pytest.approx(_OBS_LAT)
        assert r["origin_lon"] == pytest.approx(_OBS_LON)
        obs_dt = datetime.fromisoformat(_OBS_TS).astimezone(timezone.utc).isoformat()
        assert r["origin_timestamp"] == obs_dt

    def test_H_negative_elapsed_fails(self):
        """TEST H: elapsed < 0 → validation failure."""
        with pytest.raises(DriftValidationError):
            calculate_hindcast(_OBS_LAT, _OBS_LON, _OBS_TS, _ZERO_ENV_UV, elapsed_hours=-1.0)


class TestForecast:
    """§77, §44-47."""

    def test_E_exactly_5_points(self):
        """TEST E: forecast_hours=5 → exactly 5 hourly points."""
        result = calculate_forecast(_OBS_LAT, _OBS_LON, _OBS_TS, _ZERO_ENV_UV, forecast_hours=5)
        assert len(result) == 5
        for h in range(1, 6):
            assert result[h - 1]["hour"] == h

    def test_E_zero_env_unchanged(self):
        """Zero environment → all forecast positions equal observation."""
        result = calculate_forecast(_OBS_LAT, _OBS_LON, _OBS_TS, _ZERO_ENV_UV, forecast_hours=5)
        for point in result:
            assert point["lat"] == pytest.approx(_OBS_LAT)
            assert point["lon"] == pytest.approx(_OBS_LON)

    def test_forecast_timestamps(self):
        """Each forecast timestamp = observation + h hours (§47)."""
        from datetime import datetime, timezone, timedelta
        result = calculate_forecast(_OBS_LAT, _OBS_LON, _OBS_TS, _ZERO_ENV_UV, forecast_hours=5)
        obs_dt = datetime.fromisoformat(_OBS_TS).astimezone(timezone.utc)
        for point in result:
            expected_ts = (obs_dt + timedelta(hours=point["hour"])).isoformat()
            assert point["timestamp"] == expected_ts


class TestForecastStartRule:
    """§78: Forecast starts from observed slick, NOT hindcast origin."""

    def test_hindcast_and_forecast_both_start_from_observation(self):
        """
        Given obs at (P, T), hindcast and forecast both begin at (P, T).
        Forecast first point must NOT equal hindcast origin.
        """
        env = _NORTH_1MS  # moves northward
        h_result = calculate_hindcast(_OBS_LAT, _OBS_LON, _OBS_TS, env, elapsed_hours=3.0)
        f_result = calculate_forecast(_OBS_LAT, _OBS_LON, _OBS_TS, env, forecast_hours=5)

        # After 3h backward, origin is south of observation
        assert h_result["origin_lat"] < _OBS_LAT

        # After 1h forward, forecast[0] is north of observation
        assert f_result[0]["lat"] > _OBS_LAT

        # Forecast +1h must NOT equal hindcast origin (different directions)
        assert f_result[0]["lat"] != pytest.approx(h_result["origin_lat"], abs=0.001)


class TestWindFactor:
    """§30: V_oil = V_current + 0.03 * V_wind"""

    def test_wind_factor(self):
        env = {"wind_U": 0.0, "wind_V": 10.0, "current_U": 0.0, "current_V": 0.0}
        # Expected: oil_V = 0 + 0.03*10 = 0.3 m/s north for 1h
        r = calculate_hindcast(_OBS_LAT, _OBS_LON, _OBS_TS, env, elapsed_hours=1.0)
        expected_delta = (0.3 * 3600.0) / M_PER_DEG_LAT
        assert (_OBS_LAT - r["origin_lat"]) == pytest.approx(expected_delta, rel=1e-4)


class TestEnvironmentConvention:
    """§32: Convention must be verified."""

    def test_mode_b_without_convention_fails(self):
        env = {
            "wind_speed": 5.0, "wind_deg": 90.0,
            "current_speed": 1.0, "current_deg": 0.0,
            "convention": "unknown",
        }
        with pytest.raises(EnvironmentConventionError):
            calculate_hindcast(_OBS_LAT, _OBS_LON, _OBS_TS, env, elapsed_hours=1.0)

    def test_mode_b_with_toward_convention(self):
        """TOWARD convention: 0° = North → oil_V positive, oil_U = 0."""
        env = {
            "wind_speed": 0.0, "wind_deg": 0.0,
            "current_speed": 1.0, "current_deg": 0.0,
            "convention": "toward",
        }
        r = calculate_hindcast(_OBS_LAT, _OBS_LON, _OBS_TS, env, elapsed_hours=1.0)
        expected_delta = (1.0 * 3600.0) / M_PER_DEG_LAT
        assert (_OBS_LAT - r["origin_lat"]) == pytest.approx(expected_delta, rel=1e-3)

    def test_mode_a_no_convention_needed(self):
        """MODE A (U/V direct) requires no convention."""
        r = calculate_hindcast(_OBS_LAT, _OBS_LON, _OBS_TS, _NORTH_1MS, elapsed_hours=1.0)
        assert r is not None


# ===========================================================================
# INTEGRATION SMOKE TEST — run_anomaly_detection with DataFrame
# ===========================================================================

class TestAnomalyDetectionIntegration:
    """Smoke test of full pipeline with the mock AIS data."""

    def _load_sample_df(self):
        import pandas as pd
        csv = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "data", "accessais_sample.csv")
        )
        return pd.read_csv(csv)

    def test_vanguard_detected(self):
        """Act-1 demo: Vanguard (IMO 9182734) drops 14→2 kn → SOG anomaly."""
        from anomaly_detector import run_anomaly_detection
        df = self._load_sample_df()
        anomalies = run_anomaly_detection(df)
        vanguard = [a for a in anomalies if a.get("imo") == "9182734"]
        assert len(vanguard) >= 1, "Vanguard should be detected as anomalous"
        v = vanguard[0]
        assert v["sog_anomaly"] is True
        assert v["sog_drop_knots"] == pytest.approx(12.0)

    def test_vanguard_high_severity_when_shore_present(self):
        """If DistanceToShoreKm > 5, high_severity must be True for Vanguard."""
        from anomaly_detector import run_anomaly_detection
        df = self._load_sample_df()
        anomalies = run_anomaly_detection(df)
        vanguard = [a for a in anomalies if a.get("imo") == "9182734"]
        assert len(vanguard) >= 1
        v = vanguard[0]
        if v["distance_to_shore_km"] is not None and v["distance_to_shore_km"] > 5.0:
            assert v["high_severity"] is True

    def test_roi_present_for_all_anomalies(self):
        """Every anomaly must have an ROI (§18, §55)."""
        from anomaly_detector import run_anomaly_detection
        df = self._load_sample_df()
        anomalies = run_anomaly_detection(df)
        for a in anomalies:
            assert "roi" in a
            assert "lat" in a["roi"]
            assert "lon" in a["roi"]

# ============================================================================
# FASTAPI ROUTE TESTS
# D15 — Member 2 REST API verification
# ============================================================================

class TestFastAPIRoutes:

    @staticmethod
    def _client():
        from fastapi.testclient import TestClient
        import main
        return TestClient(main.app)

    def test_health_route(self):
        client = self._client()

        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "ok"
        assert data["service"] == "AquaGuard AI Backend"
        assert data["version"] == "1.0.0"

    def test_vessels_route(self):
        client = self._client()

        response = client.get("/vessels")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "success"
        assert data["count"] == 10
        assert isinstance(data["vessels"], list)
        assert len(data["vessels"]) == 10

        first = data["vessels"][0]

        required = {
            "MMSI",
            "IMO",
            "BaseDateTime",
            "LAT",
            "LON",
            "SOG",
            "COG",
            "VesselType",
            "VesselName",
            "DistanceToShoreKm",
        }

        assert required.issubset(first.keys())

    def test_anomalies_route(self):
        client = self._client()

        response = client.get("/anomalies")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "success"
        assert data["count"] >= 1

        vanguard = [
            a for a in data["anomalies"]
            if a.get("imo") == "9182734"
        ]

        assert len(vanguard) >= 1

        anomaly = vanguard[0]

        assert anomaly["sog_anomaly"] is True
        assert anomaly["sog_drop_knots"] == pytest.approx(12.0)
        assert anomaly["high_severity"] is True
        assert anomaly["roi"]["lat"] == pytest.approx(36.7)
        assert anomaly["roi"]["lon"] == pytest.approx(-15.0)

    def test_drift_route(self):
        client = self._client()

        body = {
            "slick": {
                "polygon": [],
                "centroid": {
                    "lat": 36.8,
                    "lon": -15.0,
                },
                "area_sq_km": 12.4,
                "perimeter_km": 15.0,
                "observation_timestamp": "2024-06-01T08:30:00+00:00",
            },
            "environment": {
                "wind_U": 0.0,
                "wind_V": 0.0,
                "current_U": 0.0,
                "current_V": 1.0,
            },
            "elapsed_hours": 3.0,
            "forecast_hours": 5,
        }

        response = client.post("/drift", json=body)

        assert response.status_code == 200

        data = response.json()

        assert data["status"] == "success"

        assert data["origin"]["timestamp"] == "2024-06-01T05:30:00+00:00"

        assert len(data["forecast"]) == 5
        assert [p["hour"] for p in data["forecast"]] == [1, 2, 3, 4, 5]

        assert data["model"]["wind_factor"] == pytest.approx(0.03)
        assert data["model"]["timestep_minutes"] == 10
        assert data["model"]["forecast_hours"] == 5

    def test_drift_route_missing_slick(self):
        client = self._client()

        body = {
            "environment": {
                "wind_U": 0.0,
                "wind_V": 0.0,
                "current_U": 0.0,
                "current_V": 1.0,
            },
            "elapsed_hours": 3.0,
            "forecast_hours": 5,
        }

        response = client.post("/drift", json=body)

        assert response.status_code == 400
        assert "No slick data provided" in response.json()["detail"]

    def test_drift_route_invalid_forecast(self):
        client = self._client()

        body = {
            "slick": {
                "polygon": [],
                "centroid": {
                    "lat": 36.8,
                    "lon": -15.0,
                },
                "observation_timestamp": "2024-06-01T08:30:00+00:00",
            },
            "environment": {
                "wind_U": 0.0,
                "wind_V": 0.0,
                "current_U": 0.0,
                "current_V": 1.0,
            },
            "elapsed_hours": 3.0,
            "forecast_hours": 4,
        }

        response = client.post("/drift", json=body)

        assert response.status_code == 422
        assert "forecast_hours must be 5" in str(response.json())

    def test_segment_route_with_mocked_member1(self, monkeypatch):
        import main

        def fake_segment(roi_lat, roi_lon, timestamp):
            return {
                "polygon": [[-15.0, 36.8], [-15.01, 36.8]],
                "area_sq_km": 12.4,
                "perimeter_km": 15.0,
                "centroid": {
                    "lat": 36.8,
                    "lon": -15.0,
                },
                "observation_timestamp": "2024-06-01T08:30:00+00:00",
                "georeferenced": True,
            }

        monkeypatch.setattr(
            main,
            "_call_member1_segment",
            fake_segment,
        )

        client = self._client()

        response = client.post(
            "/segment",
            json={
                    "roi_lat": 36.8,
                    "roi_lon": -15.0,
                    "timestamp": "2024-06-01T08:30:00+00:00",
            },
            
        )

        assert response.status_code == 200

        data = response.json()

        assert data["status"] == "success"
        assert data["slick"]["area_sq_km"] == pytest.approx(12.4)
        assert data["slick"]["centroid"]["lat"] == pytest.approx(36.8)
        assert data["slick"]["centroid"]["lon"] == pytest.approx(-15.0)
        assert data["slick"]["observation_timestamp"] == (
            "2024-06-01T08:30:00+00:00"
        )

    def test_segment_route_rejects_non_georeferenced(self, monkeypatch):
        import main

        def fake_segment(roi_lat, roi_lon, timestamp):
            return {
                "polygon": [[100, 200], [120, 220]],
                "area_sq_km": 1.0,
                "perimeter_km": 2.0,
                "centroid": {
                    "lat": 36.8,
                    "lon": -15.0,
                },
                "observation_timestamp": "2024-06-01T08:30:00+00:00",
                "georeferenced": False,
            }

        monkeypatch.setattr(
            main,
            "_call_member1_segment",
            fake_segment,
        )

        client = self._client()

        response = client.post(
            "/segment",
            json={
                "roi_lat": 36.8,
                "roi_lon": -15.0,
                "timestamp": "2024-06-01T08:30:00+00:00",
        },
    )

        assert response.status_code == 400
        assert "not georeferenced" in response.json()["detail"]

    def test_suspects_route_with_mocked_member3(self, monkeypatch):
        import main

        main.latest_origin = {
            "lat": 36.7,
            "lon": -15.0,
            "timestamp": "2024-06-01T05:30:00+00:00",
        }

        def fake_scorer(origin_lat, origin_lon, origin_timestamp):
            assert origin_lat == pytest.approx(36.7)
            assert origin_lon == pytest.approx(-15.0)
            assert origin_timestamp == "2024-06-01T05:30:00+00:00"

            return [
                {
                    "imo": "9182734",
                    "score": 94.2,
                }
            ]

        monkeypatch.setattr(
            main,
            "_call_member3_suspects",
            fake_scorer,
        )

        client = self._client()

        response = client.get("/suspects")

        assert response.status_code == 200

        data = response.json()

        assert data["status"] == "success"
        assert data["count"] == 1
        assert data["suspects"][0]["imo"] == "9182734"

    def test_alert_route_with_mocked_member4(self, monkeypatch):
        import main

        main.latest_origin = {
            "lat": 36.7,
            "lon": -15.0,
            "timestamp": "2024-06-01T05:30:00+00:00",
        }

        main.latest_suspects = [
            {
                "imo": "9182734",
                "score": 94.2,
            }
        ]
        
        main.latest_segment = None

        def fake_alert(suspects, origin, area_sq_km):
            assert suspects == main.latest_suspects
            assert origin == main.latest_origin
            assert area_sq_km is None
            return {
                "dispatched": True,
                "channel": "mock",
            }

        monkeypatch.setattr(
            main,
            "_call_member4_alert",
            fake_alert,
        )

        client = self._client()

        response = client.post("/alert", json={})

        assert response.status_code == 200

        data = response.json()

        assert data["status"] == "success"
        assert data["alert"]["dispatched"] is True
        assert data["alert"]["channel"] == "mock"
        
        
def test_anomaly_groups_by_imo_when_mmsi_changes():
    import pandas as pd
    from anomaly_detector import run_anomaly_detection

    df = pd.DataFrame([
        {
            "MMSI": "111111111",
            "IMO": "9182734",
            "BaseDateTime": "2024-06-01T08:00:00+00:00",
            "LAT": 36.7,
            "LON": -15.0,
            "SOG": 14.0,
            "COG": 100.0,
            "VesselType": 80,
            "DistanceToShoreKm": 50.0,
        },
        {
            "MMSI": "222222222",
            "IMO": "9182734",
            "BaseDateTime": "2024-06-01T08:30:00+00:00",
            "LAT": 36.8,
            "LON": -15.1,
            "SOG": 2.0,
            "COG": 100.0,
            "VesselType": 80,
            "DistanceToShoreKm": 50.0,
        },
    ])

    anomalies = run_anomaly_detection(df)

    assert len(anomalies) == 1
    assert anomalies[0]["imo"] == "9182734"
    assert anomalies[0]["mmsi"] == "222222222"
    assert anomalies[0]["sog_drop_knots"] == pytest.approx(12.0)
    
    
def test_sog_drop_exactly_at_threshold():
    from anomaly_detector import detect_anomaly

    result = detect_anomaly(
        previous_sog=10.0,
        current_sog=2.0,
        previous_cog=100.0,
        current_cog=100.0,
        lat=36.0,
        lon=-15.0,
        time_utc="2024-06-01T08:30:00+00:00",
        imo="1234567",
        mmsi="111111111",
        vessel_type=80,
        distance_to_shore_km=50.0,
    )

    assert result["sog_drop_knots"] == 8.0
    assert result["sog_anomaly"] is True


def test_cog_wraparound_is_small_change():
    from anomaly_detector import detect_anomaly

    result = detect_anomaly(
        previous_sog=10.0,
        current_sog=10.0,
        previous_cog=359.0,
        current_cog=1.0,
        lat=36.0,
        lon=-15.0,
        time_utc="2024-06-01T08:30:00+00:00",
        imo="1234567",
        mmsi="111111111",
        vessel_type=80,
        distance_to_shore_km=50.0,
    )

    assert result["cog_change_deg"] == 2.0
    assert result["cog_anomaly"] is False


def test_cog_change_exactly_at_threshold():
    from anomaly_detector import detect_anomaly

    result = detect_anomaly(
        previous_sog=10.0,
        current_sog=10.0,
        previous_cog=0.0,
        current_cog=45.0,
        lat=36.0,
        lon=-15.0,
        time_utc="2024-06-01T08:30:00+00:00",
        imo="1234567",
        mmsi="111111111",
        vessel_type=80,
        distance_to_shore_km=50.0,
    )

    assert result["cog_change_deg"] == 45.0
    assert result["cog_anomaly"] is True
    
    
    
def test_anomaly_falls_back_to_mmsi_when_imo_missing():
    import pandas as pd
    from anomaly_detector import run_anomaly_detection

    df = pd.DataFrame([
        {
            "MMSI": "111111111",
            "IMO": None,
            "BaseDateTime": "2024-06-01T08:00:00+00:00",
            "LAT": 36.7,
            "LON": -15.0,
            "SOG": 14.0,
            "COG": 100.0,
            "VesselType": 80,
            "DistanceToShoreKm": 50.0,
        },
        {
            "MMSI": "111111111",
            "IMO": None,
            "BaseDateTime": "2024-06-01T08:30:00+00:00",
            "LAT": 36.8,
            "LON": -15.1,
            "SOG": 2.0,
            "COG": 100.0,
            "VesselType": 80,
            "DistanceToShoreKm": 50.0,
        },
    ])

    anomalies = run_anomaly_detection(df)

    assert len(anomalies) == 1
    assert anomalies[0]["imo"] is None
    assert anomalies[0]["mmsi"] == "111111111"
    assert anomalies[0]["sog_drop_knots"] == pytest.approx(12.0)
    
    
def test_member4_adapter_sends_payload(monkeypatch):
    import main
    from types import SimpleNamespace

    suspects = [
        {
            "imo": "9182734",
            "score": 94.2,
        }
    ]

    origin = {
        "lat": 36.7,
        "lon": -15.0,
        "timestamp": "2024-06-01T05:30:00+00:00",
    }

    captured = {}

    def fake_dispatch(payload):
        captured.update(payload)
        return {
            "status": "sent",
            "destination": "mock@test.local",
        }

    fake_module = SimpleNamespace(
        dispatch_alert=fake_dispatch
    )

    real_import = main.importlib.import_module

    def fake_import(module_name):
        if module_name == "alert_dispatcher":
            return fake_module
        return real_import(module_name)

    monkeypatch.setattr(
        main.importlib,
        "import_module",
        fake_import,
    )

    result = main._call_member4_alert(
        suspects,
        origin,
        12.4,
    )

    assert captured["suspects"] == suspects
    assert captured["origin"] == origin
    assert captured["area_sq_km"] == 12.4
    assert result["status"] == "sent"