"""
accessais_loader.py — Member 3: NOAA 2025 AIS Dataset Loader
=============================================================
AquaGuard AI — Member 3 implementation integrated with the ACTIVE Member 2 backend.

Source: NOAA 2025 AccessAIS monthly datasets
Local:  D:\\OIL_SPILLL\\data\\ais2025\\

MONTHLY DATASET STRUCTURE:
    ais-2025-01-01.tgz      → January 2025   (Zstandard CSV despite .tgz extension)
    ais-2025-02-01.tgz      → February 2025  (Zstandard CSV despite .tgz extension)
    ais-2025-03-01.tgz      → March 2025     (Zstandard CSV despite .tgz extension)
    ais-2025-04-01.csv.zst  → April 2025
    ...
    ais-2025-12-01.csv.zst  → December 2025

File extension MUST NOT be trusted for format detection.
All files have been verified as Zstandard-compressed CSV streams (magic 28 B5 2F FD).

OPERATIONAL MODES (AQUAGUARD_AIS_SOURCE env var):
    sample  → data/accessais_sample.csv  (deterministic dev/test)
    real    → data/ais2025/ exact monthly NOAA dataset
    (default, unset, or other) → sample for safety

REAL MODE requires AQUAGUARD_AIS_DATE (YYYY-MM-DD) for load_vessels().
The suspect scoring path uses origin_timestamp directly (see suspect_scorer.py).

NOAA Column → Canonical Field Mapping:
    MMSI          → mmsi
    BaseDateTime  → timestamp
    LAT           → latitude
    LON           → longitude
    SOG           → sog_knots
    COG           → cog_degrees
    IMO           → imo_number
    VesselName    → vessel_name
    VesselType    → vessel_type
    Heading       → heading_degrees  (optional)
    CallSign      → call_sign        (optional)
    Status        → nav_status       (optional)

Member 2 public interface (DO NOT CHANGE):
    load_vessels() -> pandas.DataFrame

    Columns returned:
        MMSI, IMO, BaseDateTime, LAT, LON, SOG, COG, VesselType
        Optional: VesselName, DistanceToShoreKm

NO DATA FABRICATION RULES:
    - Missing IMO → IMO column = None (NOT "MMSI_..." or "Unknown IMO")
    - Missing VesselName → VesselName = None
    - Missing VesselType → VesselType = None
    - Missing DistanceToShoreKm → DistanceToShoreKm = None
    - DO NOT substitute 0.0 for any missing numeric optional field
    - REAL mode must NEVER silently fall back to sample data
"""

from __future__ import annotations

import csv
import io
import logging
import math
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

# ---------------------------------------------------------------------------
# Paths & Directory Resolution (Portable: env var -> project root -> fallback)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).parent.parent


def resolve_ais_data_dir() -> Path:
    """
    Resolve the canonical NOAA AIS dataset directory in order:
      1. Explicit environment variable: AQUAGUARD_AIS_DATA_DIR
      2. Project root data dir: <project_root>/data/ais2025
      3. Fallback to _PROJECT_ROOT / "data" / "ais2025"
    """
    env_dir = os.environ.get("AQUAGUARD_AIS_DATA_DIR", "").strip()
    if env_dir:
        return Path(env_dir)
    return _PROJECT_ROOT / "data" / "ais2025"


_ZST_DATA_DIR  = resolve_ais_data_dir()
_FALLBACK_CSV  = _PROJECT_ROOT / "data" / "accessais_sample.csv"

# ---------------------------------------------------------------------------
# NOAA column → canonical field mapping
# ---------------------------------------------------------------------------
_COL_MAP: dict[str, str] = {
    # NOAA AccessAIS raw headers (case-insensitive, stripped)
    "mmsi":              "mmsi",
    "basedatetime":      "timestamp",
    "lat":               "latitude",
    "lon":               "longitude",
    "sog":               "sog_knots",
    "cog":               "cog_degrees",
    "heading":           "heading_degrees",
    "vesselname":        "vessel_name",
    "imo":               "imo_number",
    "callsign":          "call_sign",
    "vesseltype":        "vessel_type",
    "status":            "nav_status",
    "length":            "length_meters",
    "width":             "width_meters",
    "draft":             "draft_meters",
    "cargo":             "cargo_type",
    "transceiverclass":  "transceiver_class",
    # Snake-case aliases (sample CSV and internal canonical)
    "imo_number":          "imo_number",
    "vessel_name":         "vessel_name",
    "vessel_type":         "vessel_type",
    "latitude":            "latitude",
    "longitude":           "longitude",
    "sog_knots":           "sog_knots",
    "cog_degrees":         "cog_degrees",
    "timestamp":           "timestamp",
    "distance_to_shore_km": "distance_to_shore_km",
    # Member 2 sample CSV column aliases
    "distancetoshorekm":   "distance_to_shore_km",
}

_REQUIRED_CANONICAL = {
    "mmsi", "timestamp", "latitude", "longitude", "sog_knots", "cog_degrees",
}

_NUMERIC_FIELDS = {
    "latitude", "longitude", "sog_knots", "cog_degrees",
    "heading_degrees", "length_meters", "width_meters",
    "draft_meters", "distance_to_shore_km",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm_col(raw: str) -> str:
    """Normalise a CSV header to its canonical field name."""
    k = raw.strip().lower().replace(" ", "").replace("_", "")
    if k in _COL_MAP:
        return _COL_MAP[k]
    # Try snake_case variant
    k2 = raw.strip().lower()
    return _COL_MAP.get(k2, k2)


def _parse_ts(ts: str) -> datetime:
    """
    Parse an ISO-8601 or NOAA BaseDateTime string into a UTC-aware datetime.
    NOAA format: '2025-05-01 14:23:11' (no T, no tz — assumed UTC).
    """
    ts = ts.strip().replace("Z", "+00:00")
    if "T" not in ts and "+" not in ts and "-" in ts[4:]:
        # NOAA raw: '2025-05-01 14:23:11'
        ts = ts + "+00:00"
    ts = ts.replace(" ", "T", 1)
    dt = datetime.fromisoformat(ts)
    # Ensure tz-aware UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _is_valid_imo(raw_imo: str) -> bool:
    """Return True only if raw_imo is a non-empty, non-zero, non-placeholder IMO."""
    if not raw_imo:
        return False
    # Strip 'IMO' prefix if present
    numeric = re.sub(r"[^0-9]", "", raw_imo)
    if not numeric:
        return False
    # Reject all-zero values: "0", "00", "0000000", etc.
    if int(numeric) == 0:
        return False
    return True


def _coerce_row(raw: dict[str, str]) -> dict[str, Any] | None:
    """
    Map, coerce, and validate one CSV row into the canonical schema.

    NO DATA FABRICATION:
        - Missing IMO → imo_number = None
        - Missing vessel_name → vessel_name = None
        - Missing vessel_type → vessel_type = None
        - Missing distance_to_shore_km → distance_to_shore_km = None
        - COG = 360 (NOAA unavailable sentinel) → cog_degrees excluded → row rejected
          (per contract: do not invent replacement COG)
    """
    out: dict[str, Any] = {}

    for raw_k, raw_v in raw.items():
        if raw_k is None:
            continue
        canon = _norm_col(raw_k)
        val = (raw_v or "").strip()
        if val == "":
            continue
        if canon in _NUMERIC_FIELDS:
            try:
                out[canon] = float(val)
            except ValueError:
                pass
        else:
            out[canon] = val

    # ----- Required field check -----
    missing = _REQUIRED_CANONICAL - out.keys()
    if missing:
        return None

    # ----- Domain sanity -----
    lat = out["latitude"]
    lon = out["longitude"]
    sog = out["sog_knots"]
    cog = out["cog_degrees"]

    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return None
    if sog < 0:
        return None
    if not math.isfinite(cog):
        return None
    # COG = 360 is the NOAA sentinel for "unavailable" — reject (do not fabricate)
    if cog == 360.0:
        return None
    if not (0 <= cog < 360):
        return None

    # ----- IMO normalisation — NO FABRICATION -----
    imo_raw = out.get("imo_number", "")
    if isinstance(imo_raw, str):
        imo_raw = imo_raw.strip()
    else:
        imo_raw = ""

    if _is_valid_imo(imo_raw):
        # Normalise to bare numeric form
        numeric = re.sub(r"[^0-9]", "", imo_raw)
        out["imo_number"] = numeric
    else:
        # Missing/invalid IMO — do NOT fabricate
        out["imo_number"] = None

    # ----- Optional fields — do NOT fabricate values -----
    # vessel_name, vessel_type, distance_to_shore_km remain None if not in source
    out.setdefault("vessel_name", None)
    out.setdefault("vessel_type", None)
    if "distance_to_shore_km" not in out:
        out["distance_to_shore_km"] = None

    return out


# ---------------------------------------------------------------------------
# Actual content / signature detection
# ---------------------------------------------------------------------------

_ZSTD_MAGIC = bytes([0x28, 0xB5, 0x2F, 0xFD])
_GZIP_MAGIC  = bytes([0x1F, 0x8B])
_TAR_OFFSET  = 257
_TAR_MAGIC   = b"ustar"


def _detect_format(path: Path) -> str:
    """
    Return the actual compression format regardless of file extension.

    Returns: 'zstd', 'gzip', 'tar', or 'plain'
    """
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    with path.open("rb") as fh:
        header = fh.read(512)

    if header[:4] == _ZSTD_MAGIC:
        return "zstd"
    if header[:2] == _GZIP_MAGIC:
        return "gzip"
    if len(header) >= _TAR_OFFSET + 5 and header[_TAR_OFFSET:_TAR_OFFSET + 5] == _TAR_MAGIC:
        return "tar"

    try:
        sample_text = header[:128].decode("utf-8", errors="strict")
        if "," in sample_text or "\n" in sample_text:
            return "plain"
    except UnicodeDecodeError:
        pass

    return "plain"


# ---------------------------------------------------------------------------
# Readers — by actual detected format
# ---------------------------------------------------------------------------

def _read_zstd(
    path: Path,
    time_window: tuple[datetime, datetime] | None = None,
    row_limit: int | None = None,
) -> list[dict[str, Any]]:
    """Read a Zstandard-compressed CSV (actual content, not extension-based)."""
    try:
        import zstandard as zstd
    except ImportError:
        raise ImportError(
            "The 'zstandard' package is required.\n"
            "Install with: pip install zstandard"
        )

    logger.info("Reading Zstandard stream: %s (%.1f MB)", path.name, path.stat().st_size / 1_048_576)
    vessels: list[dict[str, Any]] = []
    skipped = 0

    start_str = time_window[0].strftime("%Y-%m-%d %H:%M:%S") if time_window else None
    end_str = time_window[1].strftime("%Y-%m-%d %H:%M:%S") if time_window else None

    dctx = zstd.ZstdDecompressor()
    with path.open("rb") as fh:
        with dctx.stream_reader(fh) as reader:
            text_stream = io.TextIOWrapper(reader, encoding="utf-8", errors="replace")
            csv_reader = csv.DictReader(text_stream)
            for row in csv_reader:
                if time_window:
                    raw_ts = (row.get("base_date_time") or row.get("BaseDateTime") or row.get("timestamp") or "")[:19].replace("T", " ")
                    if raw_ts and (raw_ts < start_str or raw_ts > end_str):
                        skipped += 1
                        continue

                vessel = _coerce_row(row)
                if vessel is None:
                    skipped += 1
                    continue
                vessels.append(vessel)
                if row_limit and len(vessels) >= row_limit:
                    break

    logger.info("  → %d valid records (%d skipped) from %s", len(vessels), skipped, path.name)
    return vessels


def _read_tar(
    path: Path,
    time_window: tuple[datetime, datetime] | None = None,
    row_limit: int | None = None,
) -> list[dict[str, Any]]:
    """Safely inspect and extract CSV member from an actual tar archive."""
    import tarfile

    logger.info("Reading tar archive member: %s", path.name)
    vessels: list[dict[str, Any]] = []
    skipped = 0

    with tarfile.open(path, "r:*") as tar:
        csv_member = None
        for member in tar.getmembers():
            if member.name.lower().endswith(".csv") and not Path(member.name).name.startswith("._"):
                csv_member = member
                break
        if not csv_member:
            raise ValueError(f"No CSV member found inside tar archive {path.name}")

        fh = tar.extractfile(csv_member)
        if fh is None:
            raise ValueError(f"Could not extract {csv_member.name} from {path.name}")

        text_stream = io.TextIOWrapper(fh, encoding="utf-8", errors="replace")
        csv_reader = csv.DictReader(text_stream)

        start_str = time_window[0].strftime("%Y-%m-%d %H:%M:%S") if time_window else None
        end_str = time_window[1].strftime("%Y-%m-%d %H:%M:%S") if time_window else None

        for row in csv_reader:
            if time_window:
                raw_ts = (row.get("base_date_time") or row.get("BaseDateTime") or row.get("timestamp") or "")[:19].replace("T", " ")
                if raw_ts and (raw_ts < start_str or raw_ts > end_str):
                    skipped += 1
                    continue

            vessel = _coerce_row(row)
            if vessel is None:
                skipped += 1
                continue
            vessels.append(vessel)
            if row_limit and len(vessels) >= row_limit:
                break

    logger.info("  → %d valid records (%d skipped) from tar %s", len(vessels), skipped, path.name)
    return vessels


def _read_gzip(
    path: Path,
    time_window: tuple[datetime, datetime] | None = None,
    row_limit: int | None = None,
) -> list[dict[str, Any]]:
    """Read a gzip-compressed CSV."""
    import gzip
    logger.info("Reading gzip stream: %s", path.name)
    vessels: list[dict[str, Any]] = []
    skipped = 0

    start_str = time_window[0].strftime("%Y-%m-%d %H:%M:%S") if time_window else None
    end_str = time_window[1].strftime("%Y-%m-%d %H:%M:%S") if time_window else None

    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        csv_reader = csv.DictReader(fh)
        for row in csv_reader:
            if time_window:
                raw_ts = (row.get("base_date_time") or row.get("BaseDateTime") or row.get("timestamp") or "")[:19].replace("T", " ")
                if raw_ts and (raw_ts < start_str or raw_ts > end_str):
                    skipped += 1
                    continue

            vessel = _coerce_row(row)
            if vessel is None:
                skipped += 1
                continue
            vessels.append(vessel)
            if row_limit and len(vessels) >= row_limit:
                break

    logger.info("  → %d valid records (%d skipped) from %s", len(vessels), skipped, path.name)
    return vessels


def _read_plain_csv(
    path: Path,
    time_window: tuple[datetime, datetime] | None = None,
    row_limit: int | None = None,
) -> list[dict[str, Any]]:
    """Read an uncompressed CSV."""
    logger.info("Reading plain CSV: %s", path.name)
    vessels: list[dict[str, Any]] = []
    skipped = 0

    start_str = time_window[0].strftime("%Y-%m-%d %H:%M:%S") if time_window else None
    end_str = time_window[1].strftime("%Y-%m-%d %H:%M:%S") if time_window else None

    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        csv_reader = csv.DictReader(fh)
        for row in csv_reader:
            if time_window:
                raw_ts = (row.get("base_date_time") or row.get("BaseDateTime") or row.get("timestamp") or "")[:19].replace("T", " ")
                if raw_ts and (raw_ts < start_str or raw_ts > end_str):
                    skipped += 1
                    continue

            vessel = _coerce_row(row)
            if vessel is None:
                skipped += 1
                continue
            vessels.append(vessel)
            if row_limit and len(vessels) >= row_limit:
                break

    logger.info("  → %d valid records (%d skipped) from %s", len(vessels), skipped, path.name)
    return vessels


def _read_file(
    path: Path,
    time_window: tuple[datetime, datetime] | None = None,
    row_limit: int | None = None,
) -> list[dict[str, Any]]:
    """
    Dispatch to the correct reader based on ACTUAL file content and extension.
    Implements content-aware handling for .tgz, .csv.zst, and plain .csv.
    """
    ext = path.name.lower()
    fmt = _detect_format(path)
    logger.info("Reading %s — detected content format: %s", path.name, fmt)

    if ext.endswith(".tgz"):
        # Section 3: Content-aware handling for .tgz
        if fmt == "zstd":
            return _read_zstd(path, time_window=time_window, row_limit=row_limit)
        elif fmt == "tar":
            return _read_tar(path, time_window=time_window, row_limit=row_limit)
        elif fmt == "gzip":
            return _read_gzip(path, time_window=time_window, row_limit=row_limit)
        else:
            raise ValueError(
                f"File '{path.name}' has .tgz extension but is neither a Zstandard stream nor a valid tar archive."
            )

    if ext.endswith(".csv.zst") or fmt == "zstd":
        return _read_zstd(path, time_window=time_window, row_limit=row_limit)

    if ext.endswith(".gz") or fmt == "gzip":
        return _read_gzip(path, time_window=time_window, row_limit=row_limit)

    if fmt == "tar":
        return _read_tar(path, time_window=time_window, row_limit=row_limit)

    if fmt == "plain" or ext.endswith(".csv"):
        return _read_plain_csv(path, time_window=time_window, row_limit=row_limit)

    raise ValueError(f"Unsupported or unrecognized file format for '{path.name}' (detected: {fmt})")


# ---------------------------------------------------------------------------
# Monthly dataset discovery and selection — NO CLOSEST-MONTH FALLBACK
# ---------------------------------------------------------------------------

# Exact monthly registry: (year, month) → list of candidate filenames
_MONTHLY_REGISTRY: dict[tuple[int, int], list[str]] = {
    (2025, 1):  ["ais-2025-01-01.csv.zst", "ais-2025-01-01.tgz", "ais-2025-01-01.csv"],
    (2025, 2):  ["ais-2025-02-01.csv.zst", "ais-2025-02-01.tgz", "ais-2025-02-01.csv"],
    (2025, 3):  ["ais-2025-03-01.csv.zst", "ais-2025-03-01.tgz", "ais-2025-03-01.csv"],
    (2025, 4):  ["ais-2025-04-01.csv.zst", "ais-2025-04-01.csv"],
    (2025, 5):  ["ais-2025-05-01.csv.zst", "ais-2025-05-01.csv"],
    (2025, 6):  ["ais-2025-06-01.csv.zst", "ais-2025-06-01.csv"],
    (2025, 7):  ["ais-2025-07-01.csv.zst", "ais-2025-07-01.csv"],
    (2025, 8):  ["ais-2025-08-01.csv.zst", "ais-2025-08-01.csv"],
    (2025, 9):  ["ais-2025-09-01.csv.zst", "ais-2025-09-01.csv"],
    (2025, 10): ["ais-2025-10-01.csv.zst", "ais-2025-10-01.csv"],
    (2025, 11): ["ais-2025-11-01.csv.zst", "ais-2025-11-01.csv"],
    (2025, 12): ["ais-2025-12-01.csv.zst", "ais-2025-12-01.csv"],
}


class DataCoverageError(FileNotFoundError):
    """Raised when the required monthly NOAA dataset is missing. Never falls back."""
    pass


class ConfigurationError(ValueError):
    """Raised when required configuration (e.g. AQUAGUARD_AIS_DATE) is missing or invalid."""
    pass


def _get_monthly_path(year: int, month: int, data_dir: Path) -> Path:
    """
    Return the exact Path for the requested year/month.
    Checks candidate filenames in preference order (.csv.zst, .tgz, .csv).
    Raises DataCoverageError if not in the registry or not on disk.
    NO closest-month fallback.
    """
    key = (year, month)
    if key not in _MONTHLY_REGISTRY:
        raise DataCoverageError(
            f"No NOAA AIS dataset registered for year={year}, month={month}. "
            f"Available months: {sorted(_MONTHLY_REGISTRY.keys())}"
        )
    candidates = _MONTHLY_REGISTRY[key]
    for filename in candidates:
        path = data_dir / filename
        if path.is_file():
            return path

    raise DataCoverageError(
        f"NOAA AIS dataset for {year}-{month:02d} looked for candidates {candidates} "
        f"but none found on disk at: {data_dir}. "
        "REAL mode will NEVER fall back to sample data."
    )


def _months_required_for_window(ts: datetime, window_hours: float) -> list[tuple[int, int]]:
    """
    Return the (year, month) tuples required to cover ts ± window_hours.
    Typically 1 month, occasionally 2 when the window crosses a month boundary.
    """
    start_dt = ts - timedelta(hours=window_hours)
    end_dt   = ts + timedelta(hours=window_hours)

    months_needed: list[tuple[int, int]] = []
    # Walk month by month from start to end
    cur = start_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while cur <= end_dt:
        key = (cur.year, cur.month)
        if key not in months_needed:
            months_needed.append(key)
        # Advance to next month
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)

    return months_needed


# ---------------------------------------------------------------------------
# In-memory cache (key = canonical path string)
# ---------------------------------------------------------------------------
_vessels_cache: dict[str, list[dict[str, Any]]] = {}


def _load_monthly(
    year: int,
    month: int,
    data_dir: Path,
    time_window: tuple[datetime, datetime] | None = None,
    row_limit: int | None = None,
) -> list[dict[str, Any]]:
    """Load and cache a single monthly dataset."""
    path = _get_monthly_path(year, month, data_dir)
    if time_window or row_limit:
        tw_str = f"{time_window[0].isoformat()}_{time_window[1].isoformat()}" if time_window else "all"
        cache_key = f"{path.resolve()}::{tw_str}::{row_limit}"
    else:
        cache_key = str(path.resolve())

    if cache_key in _vessels_cache:
        logger.debug("Cache hit for %s", path.name)
        return _vessels_cache[cache_key]
    vessels = _read_file(path, time_window=time_window, row_limit=row_limit)
    _vessels_cache[cache_key] = vessels
    return vessels


# ---------------------------------------------------------------------------
# Public API — load_accessais_data (backward-compatible entry point)
# ---------------------------------------------------------------------------

def load_accessais_data(
    csv_path: str | Path,
    time_window: tuple[datetime, datetime] | None = None,
    row_limit: int | None = None,
) -> list[dict[str, Any]]:
    """
    Load an AccessAIS file (plain CSV or any supported compressed format).
    Backward-compatible entry point used by suspect_scorer.py.
    Uses actual content detection, not extension-based.
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"AccessAIS file not found: {path.resolve()}")

    if time_window or row_limit:
        tw_str = f"{time_window[0].isoformat()}_{time_window[1].isoformat()}" if time_window else "all"
        cache_key = f"{path.resolve()}::{tw_str}::{row_limit}"
    else:
        cache_key = str(path.resolve())

    if cache_key in _vessels_cache:
        return _vessels_cache[cache_key]

    vessels = _read_file(path, time_window=time_window, row_limit=row_limit)
    _vessels_cache[cache_key] = vessels
    return vessels


# ---------------------------------------------------------------------------
# Vessel grouping — IMO-first, MMSI fallback, NO FABRICATION
# ---------------------------------------------------------------------------

def _identity_key(vessel: dict[str, Any]) -> str:
    """
    Return the grouping key for a vessel.
    Valid IMO → use IMO.
    Missing/invalid IMO → use MMSI.
    NEVER fabricate an identity key.
    """
    imo = vessel.get("imo_number")
    if imo is not None and str(imo).strip() not in ("", "0", "None"):
        return f"IMO:{imo}"
    mmsi = vessel.get("mmsi", "")
    return f"MMSI:{mmsi}"


def group_vessels_by_identity(
    vessels: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """
    Group vessels by identity key (IMO when valid, MMSI fallback).
    Each group is sorted chronologically by timestamp.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for v in vessels:
        key = _identity_key(v)
        grouped.setdefault(key, []).append(v)

    for key in grouped:
        try:
            grouped[key].sort(key=lambda r: _parse_ts(str(r["timestamp"])))
        except Exception:
            pass  # leave unsortable groups as-is

    return grouped


def group_vessels_by_imo(vessels: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """
    Backward-compatible grouping function.
    Groups by IMO when valid, MMSI when IMO is missing.
    Name retained for backward compatibility with suspect_scorer.py.
    """
    return group_vessels_by_identity(vessels)


def get_latest_positions(vessels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one record per identity — the most recent ping."""
    grouped = group_vessels_by_identity(vessels)
    return [records[-1] for records in grouped.values()]


# ---------------------------------------------------------------------------
# Spatio-temporal filtering — used by suspect_scorer for scoring
# ---------------------------------------------------------------------------

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in km between two WGS-84 points."""
    R = 6_371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def filter_traffic_near_origin(
    origin_lat: float,
    origin_lon: float,
    origin_timestamp: str,
    vessels: list[dict[str, Any]],
    radius_km: float = 20.0,
    window_hours: float = 3.0,
) -> list[dict[str, Any]]:
    """
    Filter AIS records for vessels near a spill origin within a spatio-temporal window.

    Contract parameters (DO NOT change defaults):
        radius_km = 20.0 km
        window_hours = 3.0 hours (±3h)

    Uses incident-time observation: for each vessel identity, finds the observation
    CLOSEST to origin_timestamp within the time window, not blindly records[-1].

    Returns records sorted descending by proximity (closest first).
    """
    try:
        origin_dt = _parse_ts(origin_timestamp)
    except Exception as exc:
        raise ValueError(f"Cannot parse origin_timestamp '{origin_timestamp}': {exc}") from exc

    window_start = origin_dt - timedelta(hours=window_hours)
    window_end   = origin_dt + timedelta(hours=window_hours)

    grouped = group_vessels_by_identity(vessels)
    candidates: list[dict[str, Any]] = []

    for identity_key, records in grouped.items():
        # --- Find all records within the temporal window ---
        in_window = []
        for r in records:
            try:
                r_dt = _parse_ts(str(r["timestamp"]))
                if window_start <= r_dt <= window_end:
                    in_window.append((r_dt, r))
            except Exception:
                continue

        if not in_window:
            continue

        # --- Select the observation CLOSEST to origin_timestamp (NOT records[-1]) ---
        in_window.sort(key=lambda x: abs((x[0] - origin_dt).total_seconds()))
        incident_dt, incident_record = in_window[0]

        # --- Spatial filter ---
        dist_km = _haversine(
            origin_lat, origin_lon,
            incident_record["latitude"], incident_record["longitude"],
        )
        if dist_km > radius_km:
            continue

        # --- Previous observation for behavioral delta ---
        # Find the immediately preceding record (chronologically) before incident_record
        pre_records = [r for r_dt, r in in_window
                       if r_dt < incident_dt] + [r for r in records
                       if _try_parse_ts_before(str(r["timestamp"]), incident_dt)]
        pre_records_sorted = []
        for r in records:
            try:
                r_dt = _parse_ts(str(r["timestamp"]))
                if r_dt < incident_dt:
                    pre_records_sorted.append((r_dt, r))
            except Exception:
                continue
        pre_records_sorted.sort(key=lambda x: x[0], reverse=True)
        previous_record = pre_records_sorted[0][1] if pre_records_sorted else None

        candidates.append({
            "identity_key": identity_key,
            "incident_record": incident_record,
            "previous_record": previous_record,
            "distance_km": dist_km,
            "incident_dt": incident_dt,
        })

    # Sort by distance (closest first)
    candidates.sort(key=lambda c: c["distance_km"])
    return candidates


def _try_parse_ts_before(ts_str: str, ref_dt: datetime) -> bool:
    """Helper: return True if ts_str parses to a datetime before ref_dt."""
    try:
        return _parse_ts(ts_str) < ref_dt
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Month-aware loading for suspect scoring
# ---------------------------------------------------------------------------

def load_vessels_for_window(
    origin_timestamp: str,
    window_hours: float = 3.0,
    data_dir: Path | None = None,
    row_limit: int | None = None,
) -> list[dict[str, Any]]:
    """
    Load all NOAA monthly dataset(s) needed to cover origin_timestamp ± window_hours.

    This is the scoring path's data loader — authoritative date comes from origin_timestamp.
    Raises DataCoverageError if required monthly data is missing.
    Never falls back to sample data.
    """
    data_dir = data_dir or resolve_ais_data_dir()
    if not data_dir.is_dir():
        raise DataCoverageError(
            f"AIS data directory not found: {data_dir}. "
            "REAL mode will NEVER fall back to sample data."
        )

    origin_dt = _parse_ts(origin_timestamp)
    window_start = origin_dt - timedelta(hours=window_hours)
    window_end = origin_dt + timedelta(hours=window_hours)
    time_window = (window_start, window_end)

    required_months = _months_required_for_window(origin_dt, window_hours)

    all_vessels: list[dict[str, Any]] = []
    loaded_months: list[str] = []
    missing_months: list[str] = []

    for year, month in required_months:
        try:
            vessels = _load_monthly(
                year,
                month,
                data_dir,
                time_window=time_window,
                row_limit=row_limit,
            )
            all_vessels.extend(vessels)
            loaded_months.append(f"{year}-{month:02d}")
        except DataCoverageError as exc:
            missing_months.append(f"{year}-{month:02d}")
            logger.warning("Missing monthly dataset: %s", exc)

    if missing_months and not all_vessels:
        raise DataCoverageError(
            f"No NOAA AIS data available for the required months: {missing_months}. "
            f"origin_timestamp={origin_timestamp}. "
            "REAL mode will NEVER fall back to sample data."
        )
    if missing_months:
        logger.warning(
            "Partial coverage warning: months %s are missing. "
            "Scoring may be incomplete near month boundaries.",
            missing_months,
        )

    logger.info(
        "Loaded %d records from months %s for origin_timestamp=%s",
        len(all_vessels), loaded_months, origin_timestamp,
    )
    return all_vessels


# ---------------------------------------------------------------------------
# Public API — load_vessels() for Member 2 /vessels and /anomalies
# ---------------------------------------------------------------------------

def load_vessels(limit: int | None = None):
    """
    Load AIS vessel data and return as a pandas DataFrame.

    Public interface for Member 2 backend (DO NOT CHANGE SIGNATURE).

    Mode selection via environment variable AQUAGUARD_AIS_SOURCE:
        sample  → data/accessais_sample.csv
        real    → exact NOAA monthly dataset determined by AQUAGUARD_AIS_DATE

    REAL mode:
        Requires AQUAGUARD_AIS_DATE=YYYY-MM-DD.
        Maps any date in a month to that month's NOAA dataset file.
        Example: 2025-05-15 → ais-2025-05-01.csv.zst
        NEVER falls back to sample data if real dataset is missing.

    Returns
    -------
    pandas.DataFrame
        Columns: MMSI, IMO, BaseDateTime, LAT, LON, SOG, COG, VesselType
        Optional: VesselName, DistanceToShoreKm
        (All required columns are always present; individual values may be None.)
    """
    source = (os.environ.get("AQUAGUARD_AIS_SOURCE") or "sample").strip().lower()
    logger.info("load_vessels() called — AQUAGUARD_AIS_SOURCE=%r", source)

    if source == "sample":
        return _load_sample_as_dataframe(limit=limit)
    elif source == "real":
        return _load_real_as_dataframe(limit=limit)
    else:
        logger.warning(
            "Unknown AQUAGUARD_AIS_SOURCE=%r — defaulting to sample mode.", source
        )
        return _load_sample_as_dataframe(limit=limit)


def _load_sample_as_dataframe(limit: int | None = None):
    """Load the demo sample CSV as a Member 2-compatible DataFrame."""
    import pandas as pd

    if not _FALLBACK_CSV.exists():
        raise FileNotFoundError(
            f"Sample AIS CSV not found: {_FALLBACK_CSV}. "
            "Ensure data/accessais_sample.csv exists."
        )

    logger.info("Loading sample AIS data from %s", _FALLBACK_CSV.name)
    df = pd.read_csv(str(_FALLBACK_CSV))
    if limit is not None:
        df = df.head(limit)
    return _to_member2_schema(df)


def _load_real_as_dataframe(limit: int | None = None):
    """
    Load the REAL NOAA monthly dataset as a Member 2-compatible DataFrame.
    Requires AQUAGUARD_AIS_DATE env var.
    Never falls back to sample data.
    """
    import pandas as pd

    data_dir = resolve_ais_data_dir()
    if not data_dir.is_dir():
        raise DataCoverageError(
            f"AIS data directory not found: {data_dir}. "
            "REAL mode will NEVER fall back to sample data."
        )

    date_str = (os.environ.get("AQUAGUARD_AIS_DATE") or "").strip()
    if not date_str:
        raise ConfigurationError(
            "AQUAGUARD_AIS_SOURCE=real requires AQUAGUARD_AIS_DATE=YYYY-MM-DD. "
            "Example: AQUAGUARD_AIS_DATE=2025-05-15"
        )

    try:
        target_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ConfigurationError(
            f"Invalid AQUAGUARD_AIS_DATE format: {date_str!r}. "
            "Expected YYYY-MM-DD (e.g. 2025-05-15)."
        ) from exc

    year, month = target_dt.year, target_dt.month
    logger.info(
        "Loading REAL NOAA AIS — date=%s → year=%d month=%d", date_str, year, month
    )

    env_limit = os.environ.get("AQUAGUARD_AIS_ROW_LIMIT", "").strip()
    row_limit = limit
    if row_limit is None:
        if env_limit and env_limit.lower() != "none":
            try:
                row_limit = int(env_limit)
            except ValueError:
                row_limit = 50000
        else:
            row_limit = 50000

    day_start = target_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = target_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    time_window = (day_start, day_end)

    vessels = _load_monthly(year, month, data_dir, time_window=time_window, row_limit=row_limit)
    return _canonical_list_to_member2_df(vessels)


def _canonical_list_to_member2_df(vessels: list[dict[str, Any]]):
    """Convert a list of canonical vessel dicts to the Member 2 DataFrame schema."""
    import pandas as pd

    rows = []
    for v in vessels:
        rows.append({
            "MMSI":              v.get("mmsi"),
            "IMO":               v.get("imo_number"),   # None if missing — DO NOT FABRICATE
            "BaseDateTime":      v.get("timestamp"),
            "LAT":               v.get("latitude"),
            "LON":               v.get("longitude"),
            "SOG":               v.get("sog_knots"),
            "COG":               v.get("cog_degrees"),
            "VesselType":        v.get("vessel_type"),   # None if missing
            "VesselName":        v.get("vessel_name"),   # None if missing
            "DistanceToShoreKm": v.get("distance_to_shore_km"),  # None if missing
        })

    df = pd.DataFrame(rows)

    # Guarantee required columns exist even if all values are None
    for col in ("MMSI", "IMO", "BaseDateTime", "LAT", "LON", "SOG", "COG", "VesselType"):
        if col not in df.columns:
            df[col] = None

    return df


def _to_member2_schema(df):
    """
    Normalise a raw DataFrame (potentially from the sample CSV) to the
    Member 2 canonical column names.
    Handles both NOAA-header and internal-canonical-header CSVs.
    """
    import pandas as pd

    # Build a rename map from any recognized column name to the Member 2 schema
    rename_map = {
        "mmsi":                "MMSI",
        "MMSI":                "MMSI",
        "imo_number":          "IMO",
        "IMO":                 "IMO",
        "timestamp":           "BaseDateTime",
        "BaseDateTime":        "BaseDateTime",
        "latitude":            "LAT",
        "LAT":                 "LAT",
        "longitude":           "LON",
        "LON":                 "LON",
        "sog_knots":           "SOG",
        "SOG":                 "SOG",
        "cog_degrees":         "COG",
        "COG":                 "COG",
        "vessel_type":         "VesselType",
        "VesselType":          "VesselType",
        "vessel_name":         "VesselName",
        "VesselName":          "VesselName",
        "distance_to_shore_km": "DistanceToShoreKm",
        "DistanceToShoreKm":   "DistanceToShoreKm",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    # Guarantee required columns
    for col in ("MMSI", "IMO", "BaseDateTime", "LAT", "LON", "SOG", "COG", "VesselType"):
        if col not in df.columns:
            df[col] = None

    return df


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------

def clear_cache() -> None:
    """Clear in-memory vessel cache (useful between test runs)."""
    _vessels_cache.clear()
    logger.info("AIS loader cache cleared.")
