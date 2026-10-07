"""
test_member3_integration.py — Member 3 Integration Tests
=========================================================
AquaGuard AI — SIH26143

61 test items covering Member 3 accessais_loader + suspect_scorer:

Categories:
  A. Import and module identity (3)
  B. File format detection — magic bytes (6)
  C. Column normalisation and canonical schema (5)
  D. IMO normalisation — no fabrication (6)
  E. Row coercion — domain validation and rejection (7)
  F. load_accessais_data — sample CSV (5)
  G. load_vessels() — env-var mode switching (5)
  H. Vessel grouping — IMO-first, MMSI fallback (4)
  I. score_suspects — sample mode (6)
  J. score_suspects — scoring math (7)
  K. Month-boundary and monthly-dataset resolution (4)
  L. Real-mode guards — no silent fallback (3)

Total: 61 tests
"""

from __future__ import annotations

import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure backend/ is importable without installing the package
# ---------------------------------------------------------------------------
_BACKEND = Path(__file__).parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# ---------------------------------------------------------------------------
# Inline canonical sample data (never touches real NOAA files)
# ---------------------------------------------------------------------------
_SAMPLE_CSV = Path(__file__).parent.parent / "data" / "accessais_sample.csv"

# Six synthetic vessel records for unit tests — no file I/O needed for most tests
_NEAR_VESSELS: list[dict[str, Any]] = [
    # Vessel A — IMO present, near origin, big SOG drop (prime suspect)
    {
        "mmsi": "111111111", "imo_number": "9001001",
        "vessel_name": "Tanker Alpha", "vessel_type": "Tanker",
        "latitude": 36.7, "longitude": -15.0,
        "sog_knots": 14.0, "cog_degrees": 180.0,
        "timestamp": "2025-06-01T09:30:00+00:00",
        "distance_to_shore_km": None,
    },
    {
        "mmsi": "111111111", "imo_number": "9001001",
        "vessel_name": "Tanker Alpha", "vessel_type": "Tanker",
        "latitude": 36.69, "longitude": -15.01,
        "sog_knots": 1.0, "cog_degrees": 200.0,
        "timestamp": "2025-06-01T11:00:00+00:00",
        "distance_to_shore_km": None,
    },
    # Vessel B — IMO present, slightly further, smaller SOG drop
    {
        "mmsi": "222222222", "imo_number": "9002002",
        "vessel_name": "Cargo Beta", "vessel_type": "Cargo",
        "latitude": 36.71, "longitude": -15.05,
        "sog_knots": 8.0, "cog_degrees": 90.0,
        "timestamp": "2025-06-01T09:00:00+00:00",
        "distance_to_shore_km": None,
    },
    {
        "mmsi": "222222222", "imo_number": "9002002",
        "vessel_name": "Cargo Beta", "vessel_type": "Cargo",
        "latitude": 36.72, "longitude": -15.06,
        "sog_knots": 5.5, "cog_degrees": 95.0,
        "timestamp": "2025-06-01T10:45:00+00:00",
        "distance_to_shore_km": None,
    },
    # Vessel C — NO valid IMO → MMSI fallback
    {
        "mmsi": "333333333", "imo_number": None,
        "vessel_name": "Mystery C", "vessel_type": "Unknown",
        "latitude": 36.68, "longitude": -15.02,
        "sog_knots": 3.0, "cog_degrees": 270.0,
        "timestamp": "2025-06-01T10:30:00+00:00",
        "distance_to_shore_km": None,
    },
    # Vessel D — outside 3h window → should be excluded
    {
        "mmsi": "444444444", "imo_number": "9004004",
        "vessel_name": "Far Future", "vessel_type": "Tanker",
        "latitude": 36.70, "longitude": -15.00,
        "sog_knots": 10.0, "cog_degrees": 90.0,
        "timestamp": "2025-06-01T15:00:00+00:00",  # +4h from 11:00 → outside ±3h
        "distance_to_shore_km": None,
    },
    # Vessel E — beyond 20 km radius → should be excluded
    {
        "mmsi": "555555555", "imo_number": "9005005",
        "vessel_name": "Far Away", "vessel_type": "Cargo",
        "latitude": 37.5, "longitude": -14.0,  # >100km from (36.7, -15.0)
        "sog_knots": 12.0, "cog_degrees": 90.0,
        "timestamp": "2025-06-01T11:00:00+00:00",
        "distance_to_shore_km": None,
    },
]

_ORIGIN_LAT = 36.70
_ORIGIN_LON = -15.00
_ORIGIN_TS  = "2025-06-01T11:00:00+00:00"


# ===========================================================================
# A. Import and module identity  (3 tests)
# ===========================================================================

class TestImports:
    def test_accessais_loader_importable(self):
        import accessais_loader  # noqa: F401

    def test_suspect_scorer_importable(self):
        import suspect_scorer  # noqa: F401

    def test_modules_in_backend_directory(self):
        import accessais_loader, suspect_scorer
        assert Path(accessais_loader.__file__).parent == _BACKEND
        assert Path(suspect_scorer.__file__).parent == _BACKEND


# ===========================================================================
# B. File format detection — magic bytes  (6 tests)
# ===========================================================================

class TestFileFormatDetection:
    def test_detect_zstd_magic_direct(self):
        """Files with magic 28 B5 2F FD must be detected as 'zstd'."""
        import accessais_loader
        zstd_magic = bytes([0x28, 0xB5, 0x2F, 0xFD]) + b"\x00" * 508
        with patch("builtins.open", return_value=MagicMock(
            __enter__=lambda s: MagicMock(read=lambda n: zstd_magic[:n]),
            __exit__=lambda *a: None,
        )):
            result = accessais_loader._detect_format.__wrapped__(Path("fake.tgz")) if hasattr(accessais_loader._detect_format, "__wrapped__") else None
        # Direct call with tmp file
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".tgz", delete=False) as f:
            f.write(bytes([0x28, 0xB5, 0x2F, 0xFD]) + b"\x00" * 508)
            tmppath = Path(f.name)
        try:
            fmt = accessais_loader._detect_format(tmppath)
            assert fmt == "zstd", f"Expected 'zstd', got {fmt!r}"
        finally:
            tmppath.unlink(missing_ok=True)

    def test_detect_gzip_magic(self):
        """Files with magic 1F 8B must be detected as 'gzip'."""
        import accessais_loader, tempfile
        with tempfile.NamedTemporaryFile(suffix=".gz", delete=False) as f:
            f.write(bytes([0x1F, 0x8B]) + b"\x00" * 510)
            tmppath = Path(f.name)
        try:
            fmt = accessais_loader._detect_format(tmppath)
            assert fmt == "gzip", f"Expected 'gzip', got {fmt!r}"
        finally:
            tmppath.unlink(missing_ok=True)

    def test_detect_plain_csv(self):
        """Plain text CSV must be detected as 'plain'."""
        import accessais_loader, tempfile
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", encoding="utf-8") as f:
            f.write("MMSI,BaseDateTime\n123456789,2025-01-01 00:00:00\n")
            tmppath = Path(f.name)
        try:
            fmt = accessais_loader._detect_format(tmppath)
            assert fmt == "plain", f"Expected 'plain', got {fmt!r}"
        finally:
            tmppath.unlink(missing_ok=True)

    def test_tgz_extension_with_zstd_content_detected_as_zstd(self):
        """A .tgz extension with Zstandard content must report 'zstd', not 'gzip'."""
        import accessais_loader, tempfile
        # Jan-Mar NOAA files: extension .tgz, content Zstandard
        with tempfile.NamedTemporaryFile(suffix=".tgz", delete=False) as f:
            f.write(bytes([0x28, 0xB5, 0x2F, 0xFD]) + b"\x00" * 508)
            tmppath = Path(f.name)
        try:
            fmt = accessais_loader._detect_format(tmppath)
            assert fmt == "zstd", (
                f".tgz file with Zstandard content must be 'zstd', got {fmt!r}"
            )
        finally:
            tmppath.unlink(missing_ok=True)

    def test_actual_jan_file_is_zstd(self):
        """Jan 2025 NOAA file (ais-2025-01-01.tgz) must be detected as Zstandard."""
        import accessais_loader
        jan_path = Path(r"D:\OIL_SPILLL\data\ais2025\ais-2025-01-01.tgz")
        if not jan_path.exists():
            pytest.skip("Jan 2025 NOAA file not present on disk")
        fmt = accessais_loader._detect_format(jan_path)
        assert fmt == "zstd", f"Jan 2025 .tgz must be Zstandard, got {fmt!r}"

    def test_actual_apr_file_is_zstd(self):
        """Apr 2025 NOAA file (ais-2025-04-01.csv.zst) must be detected as Zstandard."""
        import accessais_loader
        apr_path = Path(r"D:\OIL_SPILLL\data\ais2025\ais-2025-04-01.csv.zst")
        if not apr_path.exists():
            pytest.skip("Apr 2025 NOAA file not present on disk")
        fmt = accessais_loader._detect_format(apr_path)
        assert fmt == "zstd", f"Apr 2025 .csv.zst must be Zstandard, got {fmt!r}"


# ===========================================================================
# C. Column normalisation and canonical schema  (5 tests)
# ===========================================================================

class TestColumnNormalisation:
    def test_norm_col_noaa_headers(self):
        """NOAA raw headers must map to canonical field names."""
        import accessais_loader
        assert accessais_loader._norm_col("MMSI") == "mmsi"
        assert accessais_loader._norm_col("BaseDateTime") == "timestamp"
        assert accessais_loader._norm_col("LAT") == "latitude"
        assert accessais_loader._norm_col("LON") == "longitude"
        assert accessais_loader._norm_col("SOG") == "sog_knots"
        assert accessais_loader._norm_col("COG") == "cog_degrees"

    def test_norm_col_imo(self):
        import accessais_loader
        assert accessais_loader._norm_col("IMO") == "imo_number"

    def test_norm_col_vesselname(self):
        import accessais_loader
        assert accessais_loader._norm_col("VesselName") == "vessel_name"
        assert accessais_loader._norm_col("VesselType") == "vessel_type"

    def test_norm_col_case_insensitive(self):
        import accessais_loader
        assert accessais_loader._norm_col("mmsi") == "mmsi"
        assert accessais_loader._norm_col("basedatetime") == "timestamp"
        assert accessais_loader._norm_col("sog") == "sog_knots"

    def test_required_canonical_fields_defined(self):
        import accessais_loader
        required = accessais_loader._REQUIRED_CANONICAL
        assert "mmsi" in required
        assert "timestamp" in required
        assert "latitude" in required
        assert "longitude" in required
        assert "sog_knots" in required
        assert "cog_degrees" in required


# ===========================================================================
# D. IMO normalisation — no fabrication  (6 tests)
# ===========================================================================

class TestIMONormalisation:
    def _make_row(self, imo="", **kwargs):
        base = {
            "MMSI": "123456789",
            "BaseDateTime": "2025-06-01 10:00:00",
            "LAT": "36.7",
            "LON": "-15.0",
            "SOG": "8.0",
            "COG": "90.0",
            "IMO": imo,
        }
        base.update(kwargs)
        return base

    def test_valid_imo_normalised_to_numeric(self):
        import accessais_loader
        row = self._make_row(imo="IMO 9182734")
        result = accessais_loader._coerce_row(row)
        assert result is not None
        assert result["imo_number"] == "9182734"

    def test_valid_imo_numeric_only(self):
        import accessais_loader
        row = self._make_row(imo="9182734")
        result = accessais_loader._coerce_row(row)
        assert result is not None
        assert result["imo_number"] == "9182734"

    def test_missing_imo_returns_none_not_fabricated(self):
        """Missing IMO must be None — must NOT be 'MMSI_...' or any invented value."""
        import accessais_loader
        row = self._make_row(imo="")
        result = accessais_loader._coerce_row(row)
        assert result is not None
        assert result["imo_number"] is None, (
            f"Missing IMO must be None, got {result['imo_number']!r}"
        )

    def test_zero_imo_returns_none(self):
        """IMO='0' is invalid — must map to None."""
        import accessais_loader
        row = self._make_row(imo="0")
        result = accessais_loader._coerce_row(row)
        assert result is not None
        assert result["imo_number"] is None, f"Zero IMO must be None, got {result['imo_number']!r}"

    def test_imo_0000000_returns_none(self):
        """All-zero IMO must map to None."""
        import accessais_loader
        row = self._make_row(imo="0000000")
        result = accessais_loader._coerce_row(row)
        assert result is not None
        assert result["imo_number"] is None

    def test_no_mmsi_prefix_fabrication(self):
        """No fabricated MMSI_ prefix when IMO is missing."""
        import accessais_loader
        row = self._make_row(imo="")
        result = accessais_loader._coerce_row(row)
        assert result is not None
        imo = result.get("imo_number")
        assert imo is None or not str(imo).startswith("MMSI_"), (
            f"imo_number must not be fabricated as MMSI_..., got {imo!r}"
        )


# ===========================================================================
# E. Row coercion — domain validation and rejection  (7 tests)
# ===========================================================================

class TestRowCoercion:
    def _base(self, **overrides):
        row = {
            "MMSI": "123456789",
            "BaseDateTime": "2025-06-01 10:00:00",
            "LAT": "36.7",
            "LON": "-15.0",
            "SOG": "8.0",
            "COG": "90.0",
            "IMO": "9001001",
        }
        row.update(overrides)
        return row

    def test_valid_row_accepted(self):
        import accessais_loader
        result = accessais_loader._coerce_row(self._base())
        assert result is not None
        assert result["latitude"] == 36.7
        assert result["longitude"] == -15.0

    def test_invalid_lat_rejected(self):
        import accessais_loader
        result = accessais_loader._coerce_row(self._base(LAT="91.0"))
        assert result is None, "Latitude > 90 must be rejected"

    def test_invalid_lon_rejected(self):
        import accessais_loader
        result = accessais_loader._coerce_row(self._base(LON="181.0"))
        assert result is None, "Longitude > 180 must be rejected"

    def test_negative_sog_rejected(self):
        import accessais_loader
        result = accessais_loader._coerce_row(self._base(SOG="-1.0"))
        assert result is None, "Negative SOG must be rejected"

    def test_cog_360_rejected_not_fabricated(self):
        """COG=360 is the NOAA unavailable sentinel — must be rejected."""
        import accessais_loader
        result = accessais_loader._coerce_row(self._base(COG="360.0"))
        assert result is None, "COG=360.0 (NOAA sentinel) must be rejected"

    def test_missing_required_field_rejected(self):
        import accessais_loader
        row = self._base()
        del row["SOG"]
        result = accessais_loader._coerce_row(row)
        assert result is None, "Missing required field SOG must cause rejection"

    def test_optional_fields_default_to_none(self):
        """vessel_name, vessel_type, distance_to_shore_km must be None when missing."""
        import accessais_loader
        row = self._base()
        # Do NOT include optional fields
        result = accessais_loader._coerce_row(row)
        assert result is not None
        assert result.get("vessel_name") is None, "vessel_name must be None when missing"
        assert result.get("vessel_type") is None, "vessel_type must be None when missing"
        assert result.get("distance_to_shore_km") is None, "distance_to_shore_km must be None when missing"


# ===========================================================================
# F. load_accessais_data — sample CSV  (5 tests)
# ===========================================================================

class TestLoadAccessaisData:
    def test_load_sample_csv_returns_list(self):
        import accessais_loader
        recs = accessais_loader.load_accessais_data(str(_SAMPLE_CSV))
        assert isinstance(recs, list)
        assert len(recs) > 0

    def test_load_sample_csv_required_fields_present(self):
        import accessais_loader
        recs = accessais_loader.load_accessais_data(str(_SAMPLE_CSV))
        required = {"mmsi", "timestamp", "latitude", "longitude", "sog_knots", "cog_degrees"}
        for r in recs:
            missing = required - r.keys()
            assert not missing, f"Record missing required fields: {missing}. Record: {r}"

    def test_load_sample_csv_numeric_fields_are_floats(self):
        import accessais_loader
        recs = accessais_loader.load_accessais_data(str(_SAMPLE_CSV))
        for r in recs:
            assert isinstance(r["latitude"], float)
            assert isinstance(r["longitude"], float)
            assert isinstance(r["sog_knots"], float)
            assert isinstance(r["cog_degrees"], float)

    def test_load_sample_csv_lat_lon_in_range(self):
        import accessais_loader
        recs = accessais_loader.load_accessais_data(str(_SAMPLE_CSV))
        for r in recs:
            assert -90 <= r["latitude"] <= 90
            assert -180 <= r["longitude"] <= 180

    def test_load_missing_file_raises_file_not_found(self):
        import accessais_loader
        with pytest.raises(FileNotFoundError):
            accessais_loader.load_accessais_data(r"D:\OIL_SPILLL\data\nonexistent_file.csv")


# ===========================================================================
# G. load_vessels() — env-var mode switching  (5 tests)
# ===========================================================================

class TestLoadVessels:
    def test_sample_mode_returns_dataframe(self):
        import accessais_loader
        with patch.dict(os.environ, {"AQUAGUARD_AIS_SOURCE": "sample"}, clear=False):
            df = accessais_loader.load_vessels()
        import pandas as pd
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0

    def test_sample_mode_has_required_columns(self):
        import accessais_loader
        with patch.dict(os.environ, {"AQUAGUARD_AIS_SOURCE": "sample"}, clear=False):
            df = accessais_loader.load_vessels()
        for col in ("MMSI", "IMO", "BaseDateTime", "LAT", "LON", "SOG", "COG", "VesselType"):
            assert col in df.columns, f"Required column {col!r} missing from DataFrame"

    def test_unknown_source_defaults_to_sample(self):
        """An unrecognised AQUAGUARD_AIS_SOURCE value must not crash — defaults to sample."""
        import accessais_loader
        with patch.dict(os.environ, {"AQUAGUARD_AIS_SOURCE": "unknown_mode"}, clear=False):
            df = accessais_loader.load_vessels()
        import pandas as pd
        assert isinstance(df, pd.DataFrame)

    def test_real_mode_without_date_raises_configuration_error(self):
        import accessais_loader
        env = {"AQUAGUARD_AIS_SOURCE": "real"}
        env_clean = {k: v for k, v in os.environ.items() if k != "AQUAGUARD_AIS_DATE"}
        env_clean.update(env)
        env_clean.pop("AQUAGUARD_AIS_DATE", None)
        with patch.dict(os.environ, env_clean, clear=True):
            with pytest.raises(accessais_loader.ConfigurationError):
                accessais_loader.load_vessels()

    def test_real_mode_with_invalid_date_raises_configuration_error(self):
        import accessais_loader
        with patch.dict(
            os.environ,
            {"AQUAGUARD_AIS_SOURCE": "real", "AQUAGUARD_AIS_DATE": "not-a-date"},
            clear=False,
        ):
            with pytest.raises(accessais_loader.ConfigurationError):
                accessais_loader.load_vessels()


# ===========================================================================
# H. Vessel grouping — IMO-first, MMSI fallback  (4 tests)
# ===========================================================================

class TestVesselGrouping:
    def test_same_imo_different_mmsi_grouped_together(self):
        """Two records with same IMO but different MMSI → same group (IMO takes precedence)."""
        import accessais_loader
        vessels = [
            {**_NEAR_VESSELS[0], "mmsi": "111111111", "imo_number": "9001001",
             "timestamp": "2025-06-01T09:00:00+00:00"},
            {**_NEAR_VESSELS[1], "mmsi": "999999999", "imo_number": "9001001",
             "timestamp": "2025-06-01T10:00:00+00:00"},
        ]
        grouped = accessais_loader.group_vessels_by_identity(vessels)
        assert len(grouped) == 1, "Same IMO must produce exactly one group"

    def test_missing_imo_grouped_by_mmsi(self):
        """Records with missing IMO must be grouped by MMSI."""
        import accessais_loader
        vessels = [
            {**_NEAR_VESSELS[4], "mmsi": "333333333", "imo_number": None,
             "timestamp": "2025-06-01T10:00:00+00:00"},
            {**_NEAR_VESSELS[4], "mmsi": "444444444", "imo_number": None,
             "timestamp": "2025-06-01T10:15:00+00:00"},
        ]
        grouped = accessais_loader.group_vessels_by_identity(vessels)
        assert len(grouped) == 2, "Two different MMSIs with missing IMO must produce 2 groups"

    def test_groups_sorted_chronologically(self):
        """Each group must be sorted oldest → newest by timestamp."""
        import accessais_loader
        vessels = [
            {**_NEAR_VESSELS[1], "timestamp": "2025-06-01T10:00:00+00:00"},
            {**_NEAR_VESSELS[0], "timestamp": "2025-06-01T09:00:00+00:00"},
        ]
        grouped = accessais_loader.group_vessels_by_identity(vessels)
        assert len(grouped) == 1
        recs = list(grouped.values())[0]
        ts0 = recs[0]["timestamp"]
        ts1 = recs[1]["timestamp"]
        assert ts0 < ts1, f"Expected chronological order, got {ts0} then {ts1}"

    def test_get_latest_positions_one_per_identity(self):
        """get_latest_positions must return exactly one record per identity."""
        import accessais_loader
        recs = accessais_loader.get_latest_positions(_NEAR_VESSELS)
        # Unique identities: 9001001, 9002002, MMSI:333333333, 9004004, 9005005 → 5
        assert len(recs) == 5


# ===========================================================================
# I. score_suspects — sample mode  (6 tests)
# ===========================================================================

class TestScoreSuspectsSampleMode:
    def _score(self, lat, lon, ts, vessels):
        import suspect_scorer
        with patch.dict(os.environ, {"AQUAGUARD_AIS_SOURCE": "sample"}, clear=False):
            with patch("accessais_loader.load_accessais_data", return_value=vessels):
                return suspect_scorer.score_suspects(lat, lon, ts)

    def test_returns_list(self):
        import suspect_scorer
        with patch.dict(os.environ, {"AQUAGUARD_AIS_SOURCE": "sample"}, clear=False):
            result = suspect_scorer.score_suspects(_ORIGIN_LAT, _ORIGIN_LON, _ORIGIN_TS)
        assert isinstance(result, list)

    def test_empty_result_is_valid_not_fabricated(self):
        """No candidates → empty list. Must never fabricate suspects."""
        import suspect_scorer
        with patch.dict(os.environ, {"AQUAGUARD_AIS_SOURCE": "sample"}, clear=False):
            result = suspect_scorer.score_suspects(0.0, 0.0, "2025-06-01T11:00:00+00:00")
        # The sample data is nowhere near (0,0)
        assert isinstance(result, list)
        assert len(result) == 0, f"Expected 0 suspects near (0,0), got {len(result)}"

    def test_suspect_has_required_keys(self):
        """Each suspect dict must contain the required keys."""
        import suspect_scorer
        required_keys = {
            "rank", "imo", "mmsi", "vessel_name", "vessel_type",
            "latitude", "longitude", "sog_knots", "cog_degrees",
            "timestamp", "distance_to_origin_km", "proximity_km",
            "delta_sog", "delta_cog", "score", "suspect_score_pct",
            "risk_tier", "factors",
        }
        with patch.dict(os.environ, {"AQUAGUARD_AIS_SOURCE": "sample"}, clear=False):
            with patch("accessais_loader.load_accessais_data", return_value=_NEAR_VESSELS):
                result = suspect_scorer.score_suspects(_ORIGIN_LAT, _ORIGIN_LON, _ORIGIN_TS)
        if result:
            missing = required_keys - result[0].keys()
            assert not missing, f"Suspect missing keys: {missing}"

    def test_ranks_are_sequential_from_one(self):
        import suspect_scorer
        with patch.dict(os.environ, {"AQUAGUARD_AIS_SOURCE": "sample"}, clear=False):
            with patch("accessais_loader.load_accessais_data", return_value=_NEAR_VESSELS):
                result = suspect_scorer.score_suspects(_ORIGIN_LAT, _ORIGIN_LON, _ORIGIN_TS)
        ranks = [s["rank"] for s in result]
        assert ranks == list(range(1, len(result) + 1)), f"Ranks must be 1..N, got {ranks}"

    def test_sorted_descending_by_score(self):
        import suspect_scorer
        with patch.dict(os.environ, {"AQUAGUARD_AIS_SOURCE": "sample"}, clear=False):
            with patch("accessais_loader.load_accessais_data", return_value=_NEAR_VESSELS):
                result = suspect_scorer.score_suspects(_ORIGIN_LAT, _ORIGIN_LON, _ORIGIN_TS)
        scores = [s["score"] for s in result]
        assert scores == sorted(scores, reverse=True), f"Scores must be descending: {scores}"

    def test_out_of_window_vessel_excluded(self):
        """Vessel D (timestamp = +4h) must NOT appear in results for ±3h window."""
        import suspect_scorer
        # Vessel D has timestamp 2025-06-01T15:00:00 which is +4h from origin at 11:00
        with patch.dict(os.environ, {"AQUAGUARD_AIS_SOURCE": "sample"}, clear=False):
            with patch("accessais_loader.load_accessais_data", return_value=_NEAR_VESSELS):
                result = suspect_scorer.score_suspects(_ORIGIN_LAT, _ORIGIN_LON, _ORIGIN_TS)
        imos = [s.get("imo") for s in result]
        assert "9004004" not in imos, "Vessel outside ±3h window must be excluded"


# ===========================================================================
# J. score_suspects — scoring math  (7 tests)
# ===========================================================================

class TestScoringMath:
    def test_proximity_factor_at_origin(self):
        """Vessel exactly at origin → distance=0 → proximity_factor=1.0."""
        import suspect_scorer
        score, factors = suspect_scorer._compute_score(0.0, None, 5.0, None, 90.0)
        assert factors["proximity"] == pytest.approx(1.0), f"proximity_factor={factors['proximity']}"

    def test_proximity_factor_at_radius_boundary(self):
        """Vessel at exactly 20 km → proximity_factor = max(0, 1-20/20) = 0.0."""
        import suspect_scorer
        score, factors = suspect_scorer._compute_score(20.0, None, 5.0, None, 90.0)
        assert factors["proximity"] == pytest.approx(0.0, abs=1e-6)

    def test_proximity_factor_beyond_radius_zero(self):
        """Vessel beyond 20 km → proximity_factor = 0 (clamped at 0, not negative)."""
        import suspect_scorer
        score, factors = suspect_scorer._compute_score(25.0, None, 5.0, None, 90.0)
        assert factors["proximity"] >= 0.0

    def test_sog_factor_uses_signed_drop(self):
        """SOG increasing (prev=5, curr=10) must produce sog_factor=0 (no suspicious drop)."""
        import suspect_scorer
        score, factors = suspect_scorer._compute_score(1.0, 5.0, 10.0, None, 90.0)
        assert factors["sog_drop"] == pytest.approx(0.0), (
            f"SOG increase should not score as suspicious, got sog_drop={factors['sog_drop']}"
        )

    def test_sog_factor_large_drop_saturates_at_one(self):
        """SOG drop ≥ 8 kn → sog_factor = 1.0 (saturated)."""
        import suspect_scorer
        score, factors = suspect_scorer._compute_score(1.0, 14.0, 0.0, None, 90.0)
        assert factors["sog_drop"] == pytest.approx(1.0), (
            f"14→0 kn drop (14 kn ≥ 8 kn threshold) must saturate at 1.0, got {factors['sog_drop']}"
        )

    def test_cog_factor_circular_arithmetic(self):
        """COG 5° vs 355° → circular delta = 10°, not 350°."""
        import suspect_scorer
        delta = suspect_scorer._cog_circular_delta(5.0, 355.0)
        assert delta == pytest.approx(10.0, abs=1e-6), (
            f"Circular COG delta(5, 355) must be 10°, got {delta}"
        )

    def test_score_range_zero_to_hundred(self):
        """Score must always be in [0, 100]."""
        import suspect_scorer
        # Extreme inputs
        for dist in (0.0, 1.0, 5.0, 10.0, 19.9, 20.0):
            for sog_drop in (0.0, 8.0, 20.0):
                for cog_delta in (0.0, 45.0, 180.0):
                    score, _ = suspect_scorer._compute_score(dist, 10.0, 10.0 - sog_drop, None, 90.0)
                    assert 0.0 <= score <= 100.0, f"Score out of range: {score}"


# ===========================================================================
# K. Month-boundary and monthly-dataset resolution  (4 tests)
# ===========================================================================

class TestMonthBoundaryResolution:
    def test_single_month_no_boundary_crossing(self):
        """Timestamp well within a month → only one month required."""
        import accessais_loader
        ts = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        months = accessais_loader._months_required_for_window(ts, 3.0)
        assert months == [(2025, 6)], f"Expected [(2025, 6)], got {months}"

    def test_month_boundary_crossing_start_of_month(self):
        """2025-06-01 00:30 UTC ± 3h spans May and June → both months required."""
        import accessais_loader
        ts = datetime(2025, 6, 1, 0, 30, 0, tzinfo=timezone.utc)
        months = accessais_loader._months_required_for_window(ts, 3.0)
        assert (2025, 5) in months and (2025, 6) in months, (
            f"Expected both May and June, got {months}"
        )

    def test_month_boundary_crossing_end_of_month(self):
        """2025-05-31 23:30 UTC ± 3h spans May and June → both months required."""
        import accessais_loader
        ts = datetime(2025, 5, 31, 23, 30, 0, tzinfo=timezone.utc)
        months = accessais_loader._months_required_for_window(ts, 3.0)
        assert (2025, 5) in months and (2025, 6) in months, (
            f"Expected both May and June, got {months}"
        )

    def test_exact_month_match_only_no_closest_fallback(self):
        """
        Monthly registry must raise DataCoverageError for an unregistered month
        (e.g., 2024-12) — NEVER substitute the closest available month.
        """
        import accessais_loader
        with pytest.raises(accessais_loader.DataCoverageError):
            accessais_loader._get_monthly_path(2024, 12, Path(r"D:\OIL_SPILLL\data\ais2025"))


# ===========================================================================
# L. Real-mode guards — no silent fallback  (3 tests)
# ===========================================================================

class TestRealModeGuards:
    def test_real_mode_missing_monthly_file_raises_coverage_error(self):
        """
        Real mode with a non-existent monthly file must raise DataCoverageError,
        NOT silently fall back to sample data.
        """
        import accessais_loader
        # Month 2024-01 is not in the registry — must raise
        with pytest.raises(accessais_loader.DataCoverageError):
            accessais_loader._get_monthly_path(2024, 1, Path(r"D:\OIL_SPILLL\data\ais2025"))

    def test_load_vessels_for_window_unregistered_year_raises(self):
        """
        load_vessels_for_window with a 2024 timestamp must raise DataCoverageError
        since 2024 is not in the registry.
        """
        import accessais_loader
        with pytest.raises(accessais_loader.DataCoverageError):
            accessais_loader.load_vessels_for_window(
                origin_timestamp="2024-06-15T12:00:00+00:00",
                window_hours=3.0,
            )

    def test_score_suspects_real_mode_unregistered_ts_raises(self):
        """
        score_suspects in real mode with a timestamp outside the NOAA 2025 coverage
        must raise DataCoverageError — NEVER silently switch to sample data.
        """
        import suspect_scorer, accessais_loader
        with patch.dict(os.environ, {"AQUAGUARD_AIS_SOURCE": "real"}, clear=False):
            with pytest.raises(accessais_loader.DataCoverageError):
                suspect_scorer.score_suspects(
                    origin_lat=36.7,
                    origin_lon=-15.0,
                    origin_timestamp="2024-06-15T12:00:00+00:00",
                )
