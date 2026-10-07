"""
AquaGuard AI — NOAA 2025 AIS Dataset Registry
Dataset discovery and path registry helper for Member 3.

Location: backend/ais_dataset_registry.py

PURPOSE:
    Provides deterministic discovery and path resolution for the 12 monthly
    NOAA 2025 AIS dataset archives stored in data/ais2025/.

SUPPORTED FORMATS:
    - January - March 2025   : .tgz archives
    - April - December 2025   : .csv.zst compressed streams

MEMBER 3 SCHEMA EXPECTATIONS:
    When Member 3 (accessais_loader.py / ais_loader.py) decompresses and
    reads these files, records must be mapped to AquaGuard AI's core fields:
        Required:
            - MMSI
            - IMO
            - BaseDateTime
            - LAT
            - LON
            - SOG
            - COG
            - VesselType
        Optional:
            - VesselName
            - DistanceToShoreKm

    Note: NOAA source datasets may use slightly different raw column conventions
    or headers. The consumer (Member 3 loader) is responsible for decompression
    and source column mapping. This registry does NOT modify or decompress the archives.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple


# Default dataset root relative to this file's location (backend/ -> data/ais2025/)
_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "ais2025"

# Known registry map for year 2025: month -> (filename, format)
NOAA_2025_CATALOG: Dict[int, Tuple[str, str]] = {
    1: ("ais-2025-01-01.tgz", "tgz"),
    2: ("ais-2025-02-01.tgz", "tgz"),
    3: ("ais-2025-03-01.tgz", "tgz"),
    4: ("ais-2025-04-01.csv.zst", "csv.zst"),
    5: ("ais-2025-05-01.csv.zst", "csv.zst"),
    6: ("ais-2025-06-01.csv.zst", "csv.zst"),
    7: ("ais-2025-07-01.csv.zst", "csv.zst"),
    8: ("ais-2025-08-01.csv.zst", "csv.zst"),
    9: ("ais-2025-09-01.csv.zst", "csv.zst"),
    10: ("ais-2025-10-01.csv.zst", "csv.zst"),
    11: ("ais-2025-11-01.csv.zst", "csv.zst"),
    12: ("ais-2025-12-01.csv.zst", "csv.zst"),
}


class DatasetNotFoundError(FileNotFoundError):
    """Raised when a requested monthly AIS dataset is not registered or missing on disk."""
    pass


def get_dataset_root(custom_dir: Optional[Path | str] = None) -> Path:
    """Return the resolved Path to the ais2025 dataset directory."""
    if custom_dir is not None:
        return Path(custom_dir).resolve()
    return _DEFAULT_DATA_DIR.resolve()


def dataset_exists(year: int, month: int, data_dir: Optional[Path | str] = None) -> bool:
    """
    Check if the NOAA AIS dataset file for the specified year and month exists on disk.

    Parameters
    ----------
    year : int
        The calendar year (currently 2025 supported).
    month : int
        The month (1 to 12).
    data_dir : Path or str, optional
        Custom directory override for the dataset root.

    Returns
    -------
    bool
        True if registered and present on disk, False otherwise.
    """
    if year != 2025 or month not in NOAA_2025_CATALOG:
        return False

    filename, _ = NOAA_2025_CATALOG[month]
    root = get_dataset_root(data_dir)
    target_path = root / filename
    return target_path.is_file()


def get_dataset_path(year: int, month: int, data_dir: Optional[Path | str] = None) -> Path:
    """
    Resolve and validate the filesystem path to a NOAA 2025 monthly AIS dataset.

    Parameters
    ----------
    year : int
        The calendar year (currently 2025 supported).
    month : int
        The month (1 to 12).
    data_dir : Path or str, optional
        Custom directory override for the dataset root.

    Returns
    -------
    pathlib.Path
        The absolute Path to the verified dataset file.

    Raises
    ------
    ValueError
        If year/month is unsupported or invalid.
    DatasetNotFoundError
        If the file is registered but does not exist at the expected filesystem location.
    """
    if year != 2025:
        raise ValueError(
            f"Unsupported dataset year {year}. NOAA AIS registry currently supports 2025."
        )

    if month not in NOAA_2025_CATALOG:
        raise ValueError(
            f"Invalid month {month}. Month must be an integer between 1 and 12."
        )

    filename, _ = NOAA_2025_CATALOG[month]
    root = get_dataset_root(data_dir)
    target_path = root / filename

    if not target_path.is_file():
        raise DatasetNotFoundError(
            f"NOAA AIS dataset for {year}-{month:02d} was not found on disk at: {target_path}. "
            "Never substituting demo data for production datasets."
        )

    return target_path


def list_available_datasets(data_dir: Optional[Path | str] = None) -> List[dict]:
    """
    List all catalogued datasets along with their on-disk availability and metadata.

    Returns
    -------
    list of dict
        List of entries with year, month, filename, format, path, and exists status.
    """
    root = get_dataset_root(data_dir)
    entries = []

    for month in range(1, 13):
        filename, fmt = NOAA_2025_CATALOG[month]
        file_path = root / filename
        is_present = file_path.is_file()
        file_size = file_path.stat().st_size if is_present else None

        entries.append({
            "year": 2025,
            "month": month,
            "filename": filename,
            "compression_format": fmt,
            "path": str(file_path),
            "exists": is_present,
            "size_bytes": file_size,
        })

    return entries
