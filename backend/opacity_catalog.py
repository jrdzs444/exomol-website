from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import RLock
from urllib.parse import unquote, urljoin, urlparse

import h5py
import requests
from bs4 import BeautifulSoup


EXOMOL_OPACITY_BASE = os.environ.get(
    "EXOMOL_OPACITY_BASE",
    "https://exomol.com/data/data-types/opacity",
).rstrip("/")
EXOMOL_OPACITY_LINK_BASE = os.environ.get(
    "EXOMOL_OPACITY_LINK_BASE",
    "https://exomol.com",
).rstrip("/")
DOWNLOAD_TIMEOUT_SECONDS = int(
    os.environ.get("EXOMOL_DOWNLOAD_TIMEOUT_SECONDS", "180")
)
HTTP_HEADERS = {
    "User-Agent": "ExoMol-Opacity-App/0.5 (+local development)"
}
SAFE_SLUG = re.compile(r"^[A-Za-z0-9_+\-]+$")
TAUREX_SUFFIX = ".xsec.TauREx.h5"
REQUIRED_TAUREX_DATASETS = {"mol_name", "key_iso_ll", "t", "p", "bin_edges", "xsecarr"}
DEFAULT_OPACITY_LINKS_FILE = Path(__file__).resolve().parent / "opacity-links.txt"
EXOMOL_OPACITY_LINKS_FILE = (
    Path(os.environ["EXOMOL_OPACITY_LINKS_FILE"]).expanduser()
    if os.environ.get("EXOMOL_OPACITY_LINKS_FILE")
    else DEFAULT_OPACITY_LINKS_FILE if DEFAULT_OPACITY_LINKS_FILE.is_file() else None
)
EXOMOL_OPACITY_DATA_DIR = (
    Path(os.environ["EXOMOL_OPACITY_DATA_DIR"]).expanduser()
    if os.environ.get("EXOMOL_OPACITY_DATA_DIR")
    else None
)
DEFAULT_CACHE_DIR = Path(
    os.environ.get(
        "TAUREX_H5_CACHE_DIR",
        str(Path(__file__).resolve().parent / "opacity_data"),
    )
)
EXOMOL_OPACITY_CATALOG_CACHE_FILE = Path(
    os.environ.get(
        "EXOMOL_OPACITY_CATALOG_CACHE_FILE",
        str(DEFAULT_CACHE_DIR / "opacity_catalog.json"),
    )
).expanduser()
EXOMOL_OPACITY_CATALOG_CACHE_TTL_SECONDS = int(
    os.environ.get("EXOMOL_OPACITY_CATALOG_CACHE_TTL_SECONDS", str(24 * 60 * 60))
)
EXOMOL_OPACITY_CATALOG_CACHE_ENABLED = (
    os.environ.get("EXOMOL_OPACITY_CATALOG_CACHE_ENABLED", "true").strip().lower()
    not in {"0", "false", "no", "off"}
)
CATALOG_CACHE_VERSION = 1
CATALOG_CACHE_LOCK = RLock()


def configured_local_data_dir() -> Path | None:
    if EXOMOL_OPACITY_DATA_DIR is None:
        return None
    if not EXOMOL_OPACITY_DATA_DIR.is_dir():
        raise ValueError(
            "EXOMOL_OPACITY_DATA_DIR does not exist or is not a directory: "
            f"{EXOMOL_OPACITY_DATA_DIR}"
        )
    return EXOMOL_OPACITY_DATA_DIR


def configured_opacity_links_file() -> Path | None:
    if EXOMOL_OPACITY_LINKS_FILE is None:
        return None
    if not EXOMOL_OPACITY_LINKS_FILE.is_file():
        raise ValueError(
            "EXOMOL_OPACITY_LINKS_FILE does not exist or is not a file: "
            f"{EXOMOL_OPACITY_LINKS_FILE}"
        )
    return EXOMOL_OPACITY_LINKS_FILE


def catalog_source() -> str:
    links_file = configured_opacity_links_file()
    local_dir = configured_local_data_dir()
    if links_file is not None:
        if local_dir is not None:
            return f"{links_file} mapped to {local_dir}"
        return str(links_file)
    if local_dir is not None:
        return str(local_dir)
    return f"{EXOMOL_OPACITY_BASE}/"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def clear_catalog_memory_caches() -> None:
    discover_local_taurex_catalog.cache_clear()
    discover_link_file_taurex_catalog.cache_clear()


def configured_cache_file() -> Path:
    return EXOMOL_OPACITY_CATALOG_CACHE_FILE


def read_catalog_cache(cache_file: Path | None = None) -> dict | None:
    cache_path = cache_file or configured_cache_file()
    if not cache_path.is_file():
        return None

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if payload.get("version") != CATALOG_CACHE_VERSION:
        return None
    if not isinstance(payload.get("datasets"), list):
        return None
    return payload


def catalog_cache_is_fresh(payload: dict) -> bool:
    generated_epoch = payload.get("generatedAtEpoch")
    if not isinstance(generated_epoch, (int, float)):
        return False
    return (time.time() - generated_epoch) <= EXOMOL_OPACITY_CATALOG_CACHE_TTL_SECONDS


def write_catalog_cache(payload: dict, cache_file: Path | None = None) -> None:
    cache_path = cache_file or configured_cache_file()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_name(cache_path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(cache_path)


def build_catalog_cache_payload(datasets: list[dict], source_mode: str) -> dict:
    return {
        "version": CATALOG_CACHE_VERSION,
        "generatedAt": now_utc_iso(),
        "generatedAtEpoch": time.time(),
        "source": catalog_source(),
        "sourceMode": source_mode,
        "cacheTtlSeconds": EXOMOL_OPACITY_CATALOG_CACHE_TTL_SECONDS,
        "supportedDatasetCount": len(datasets),
        "datasets": datasets,
    }


def scan_configured_catalog() -> dict:
    local_dir = configured_local_data_dir()
    links_file = configured_opacity_links_file()

    clear_catalog_memory_caches()

    if local_dir is not None:
        datasets = [dict(dataset) for dataset in discover_local_taurex_catalog(str(local_dir))]
        return build_catalog_cache_payload(datasets, "local-data-dir")

    if links_file is not None:
        datasets = [
            dict(dataset)
            for dataset in discover_link_file_taurex_catalog(str(links_file), "")
        ]
        return build_catalog_cache_payload(datasets, "link-file")

    raise ValueError("No cacheable opacity catalogue source is configured.")


def catalog_cache_source_available() -> bool:
    return configured_local_data_dir() is not None or configured_opacity_links_file() is not None


def get_catalog_cache_payload(force_refresh: bool = False) -> dict:
    if not catalog_cache_source_available():
        raise ValueError("No cacheable opacity catalogue source is configured.")

    with CATALOG_CACHE_LOCK:
        if EXOMOL_OPACITY_CATALOG_CACHE_ENABLED and not force_refresh:
            cached = read_catalog_cache()
            if cached is not None and catalog_cache_is_fresh(cached):
                return cached

        payload = scan_configured_catalog()
        if EXOMOL_OPACITY_CATALOG_CACHE_ENABLED:
            write_catalog_cache(payload)
        return payload


def refresh_opacity_catalog() -> dict:
    return get_catalog_cache_payload(force_refresh=True)


def catalog_cache_status() -> dict:
    cache_file = configured_cache_file()
    cached = read_catalog_cache(cache_file)
    return {
        "enabled": EXOMOL_OPACITY_CATALOG_CACHE_ENABLED,
        "cacheFile": str(cache_file),
        "exists": cache_file.is_file(),
        "fresh": catalog_cache_is_fresh(cached) if cached else False,
        "ttlSeconds": EXOMOL_OPACITY_CATALOG_CACHE_TTL_SECONDS,
        "generatedAt": cached.get("generatedAt") if cached else None,
        "source": cached.get("source") if cached else catalog_source(),
        "sourceMode": cached.get("sourceMode") if cached else None,
        "supportedDatasetCount": cached.get("supportedDatasetCount") if cached else None,
    }


def molecules_from_datasets(datasets: list[dict]) -> list[dict]:
    molecules: dict[str, str] = {}
    for dataset in datasets:
        key = dataset["molecule"]
        molecules[key] = key.replace("_p", "+")
    return [
        {"key": key, "label": label}
        for key, label in sorted(molecules.items(), key=lambda item: item[1].lower())
    ]


def label_to_key(label: str) -> str:
    return label.replace("+", "_p")


def decode_hdf5_scalar(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def read_hdf5_text(handle: h5py.File, name: str) -> str | None:
    if name not in handle:
        return None

    value = handle[name][()]
    if hasattr(value, "size") and value.size == 0:
        return None
    if hasattr(value, "flat"):
        value = value.flat[0]
    return decode_hdf5_scalar(value)


def validate_local_taurex_file(handle: h5py.File) -> None:
    missing = sorted(REQUIRED_TAUREX_DATASETS.difference(handle.keys()))
    if missing:
        raise ValueError("Missing required TauREx datasets: " + ", ".join(missing))


def parse_configuration(filename: str) -> str:
    match = re.search(r"(?:\.|__)(R\d.+)\.xsec\.TauREx\.h5$", filename)
    return match.group(1) if match else filename


def normalize_link_path(raw_link: str) -> str | None:
    link = raw_link.strip().split()[0] if raw_link.strip() else ""
    if not link or link.startswith("#"):
        return None

    path = unquote(urlparse(link).path or link)
    return path if path.endswith(TAUREX_SUFFIX) else None


def opacity_link_segments(link_path: str) -> list[str]:
    parts = [part for part in link_path.strip("/").split("/") if part]
    if parts and parts[0] == "db":
        parts = parts[1:]
    return parts


def build_link_file_dataset_record(
    raw_link: str,
    local_root: Path | None = None,
) -> dict | None:
    link_path = normalize_link_path(raw_link)
    if link_path is None:
        return None

    parts = opacity_link_segments(link_path)
    if len(parts) < 4:
        return None

    molecule, isotopologue, line_list, filename = parts[-4:]
    if not (
        SAFE_SLUG.fullmatch(molecule)
        and SAFE_SLUG.fullmatch(isotopologue)
        and SAFE_SLUG.fullmatch(line_list)
        and filename.endswith(TAUREX_SUFFIX)
    ):
        return None

    parsed = urlparse(raw_link.strip())
    url = (
        raw_link.strip()
        if parsed.scheme in {"http", "https"} and parsed.netloc
        else urljoin(EXOMOL_OPACITY_LINK_BASE + "/", link_path.lstrip("/"))
    )

    local_path = local_root.joinpath(*parts) if local_root is not None else None
    source_type = "local" if local_path is not None and local_path.is_file() else "remote"

    record = {
        "key": f"{molecule}/{isotopologue}/{line_list}/{filename}",
        "molecule": molecule,
        "isotopologue": isotopologue,
        "lineList": line_list,
        "dataset": f"{isotopologue}__{line_list}",
        "configuration": parse_configuration(filename),
        "fileName": filename,
        "url": url,
        "sourceType": source_type,
        "catalogPath": "/" + "/".join(["db", *parts]),
        "label": f"{isotopologue} / {line_list} / {filename}",
    }

    if source_type == "local":
        record["localPath"] = str(local_path)
    elif local_path is not None:
        record["expectedLocalPath"] = str(local_path)

    return record


def fetch_html(url: str) -> str:
    response = requests.get(
        url,
        headers=HTTP_HEADERS,
        timeout=DOWNLOAD_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.text


def parse_immediate_children(html_text: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(html_text, "html.parser")
    base_url = page_url.rstrip("/") + "/"
    base_path = urlparse(base_url).path.rstrip("/") + "/"
    children: set[str] = set()

    for tag in soup.find_all("a", href=True):
        href = tag["href"].split("#", 1)[0].strip()
        if not href:
            continue

        absolute_url = urljoin(base_url, href)
        parsed = urlparse(absolute_url)
        if parsed.netloc != urlparse(base_url).netloc:
            continue

        path = parsed.path.rstrip("/")
        if not path.startswith(base_path):
            continue

        remainder = unquote(path[len(base_path) :]).strip("/")
        if remainder and "/" not in remainder and SAFE_SLUG.fullmatch(remainder):
            children.add(remainder)

    return sorted(children, key=str.lower)


def parse_taurex_files(
    html_text: str,
    page_url: str,
    molecule: str,
    isotopologue: str,
    line_list: str,
) -> list[dict]:
    soup = BeautifulSoup(html_text, "html.parser")
    found: dict[str, str] = {}

    for tag in soup.find_all("a", href=True):
        absolute_url = urljoin(page_url, tag["href"].strip())
        filename = unquote(Path(urlparse(absolute_url).path).name)
        parsed = urlparse(absolute_url)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.netloc != urlparse(page_url).netloc:
            continue
        if filename.endswith(TAUREX_SUFFIX):
            found[filename] = absolute_url

    datasets = []
    for filename, url in sorted(found.items()):
        datasets.append(
            {
                "key": f"{molecule}/{isotopologue}/{line_list}/{filename}",
                "molecule": molecule,
                "isotopologue": isotopologue,
                "lineList": line_list,
                "dataset": f"{isotopologue}__{line_list}",
                "configuration": parse_configuration(filename),
                "fileName": filename,
                "url": url,
                "sourceType": "remote",
                "label": (
                    f"{isotopologue} / {line_list} / {filename}"
                ),
            }
        )

    return datasets


def build_local_dataset_record(path: Path, root: Path) -> dict | None:
    filename = path.name
    if not filename.endswith(TAUREX_SUFFIX):
        return None

    relative = path.relative_to(root)
    parts = relative.parts
    molecule_key = parts[-4] if len(parts) >= 4 else None
    isotopologue = parts[-3] if len(parts) >= 3 else None
    line_list = parts[-2] if len(parts) >= 2 else None
    molecule_label = molecule_key.replace("_p", "+") if molecule_key else None

    try:
        with h5py.File(path, "r") as handle:
            validate_local_taurex_file(handle)
            molecule_label = read_hdf5_text(handle, "mol_name") or molecule_label
            key_iso_ll = read_hdf5_text(handle, "key_iso_ll")
    except (OSError, ValueError):
        return None

    if key_iso_ll and "__" in key_iso_ll:
        isotopologue, line_list = key_iso_ll.split("__", 1)

    if molecule_label:
        molecule_key = label_to_key(molecule_label)

    if not molecule_key or not isotopologue or not line_list:
        return None

    return {
        "key": f"{molecule_key}/{isotopologue}/{line_list}/{filename}",
        "molecule": molecule_key,
        "isotopologue": isotopologue,
        "lineList": line_list,
        "dataset": f"{isotopologue}__{line_list}",
        "configuration": parse_configuration(filename),
        "fileName": filename,
        "url": None,
        "sourceType": "local",
        "localPath": str(path),
        "label": f"{isotopologue} / {line_list} / {filename}",
    }


@lru_cache(maxsize=4)
def discover_local_taurex_catalog(root_string: str) -> tuple[dict, ...]:
    root = Path(root_string)
    datasets = [
        record
        for path in root.rglob(f"*{TAUREX_SUFFIX}")
        if (record := build_local_dataset_record(path, root)) is not None
    ]
    return tuple(
        sorted(
            datasets,
            key=lambda item: (
                item["molecule"].lower(),
                item["isotopologue"].lower(),
                item["lineList"].lower(),
                item["fileName"].lower(),
            ),
        )
    )


def discover_local_opacity_molecules(root: Path) -> list[dict]:
    molecules: dict[str, str] = {}
    for dataset in discover_local_taurex_catalog(str(root)):
        key = dataset["molecule"]
        molecules[key] = key.replace("_p", "+")
    return [
        {"key": key, "label": label}
        for key, label in sorted(molecules.items(), key=lambda item: item[1].lower())
    ]


def discover_local_taurex_datasets(molecule: str, root: Path) -> list[dict]:
    if not SAFE_SLUG.fullmatch(molecule):
        raise ValueError("Invalid molecule identifier.")

    return [
        dict(dataset)
        for dataset in discover_local_taurex_catalog(str(root))
        if dataset["molecule"] == molecule
    ]


@lru_cache(maxsize=4)
def discover_link_file_taurex_catalog(
    links_file_string: str,
    local_root_string: str = "",
) -> tuple[dict, ...]:
    links_file = Path(links_file_string)
    local_root = Path(local_root_string) if local_root_string else None
    datasets: dict[str, dict] = {}

    for line in links_file.read_text(encoding="utf-8").splitlines():
        record = build_link_file_dataset_record(line, local_root)
        if record is not None:
            datasets[record["key"]] = record

    return tuple(
        sorted(
            datasets.values(),
            key=lambda item: (
                item["molecule"].lower(),
                item["isotopologue"].lower(),
                item["lineList"].lower(),
                item["fileName"].lower(),
            ),
        )
    )


def discover_link_file_opacity_molecules(
    links_file: Path,
    local_root: Path | None = None,
) -> list[dict]:
    molecules: dict[str, str] = {}
    for dataset in discover_link_file_taurex_catalog(
        str(links_file),
        str(local_root) if local_root is not None else "",
    ):
        key = dataset["molecule"]
        molecules[key] = key.replace("_p", "+")
    return [
        {"key": key, "label": label}
        for key, label in sorted(molecules.items(), key=lambda item: item[1].lower())
    ]


def discover_link_file_taurex_datasets(
    molecule: str,
    links_file: Path,
    local_root: Path | None = None,
) -> list[dict]:
    if not SAFE_SLUG.fullmatch(molecule):
        raise ValueError("Invalid molecule identifier.")

    return [
        dict(dataset)
        for dataset in discover_link_file_taurex_catalog(
            str(links_file),
            str(local_root) if local_root is not None else "",
        )
        if dataset["molecule"] == molecule
    ]


def discover_opacity_molecules() -> list[dict]:
    if catalog_cache_source_available():
        payload = get_catalog_cache_payload()
        return molecules_from_datasets(payload["datasets"])

    html_text = fetch_html(f"{EXOMOL_OPACITY_BASE}/")
    molecule_slugs = parse_immediate_children(
        html_text,
        f"{EXOMOL_OPACITY_BASE}/",
    )
    return [
        {
            "key": molecule,
            "label": molecule.replace("_p", "+"),
        }
        for molecule in molecule_slugs
    ]


def discover_taurex_datasets(molecule: str) -> list[dict]:
    if catalog_cache_source_available():
        if not SAFE_SLUG.fullmatch(molecule):
            raise ValueError("Invalid molecule identifier.")
        payload = get_catalog_cache_payload()
        return [
            dict(dataset)
            for dataset in payload["datasets"]
            if dataset["molecule"] == molecule
        ]

    if not SAFE_SLUG.fullmatch(molecule):
        raise ValueError("Invalid molecule identifier.")

    molecule_url = f"{EXOMOL_OPACITY_BASE}/{molecule}/"
    isotopologues = parse_immediate_children(
        fetch_html(molecule_url),
        molecule_url,
    )

    datasets: list[dict] = []
    for isotopologue in isotopologues:
        isotopologue_url = f"{molecule_url}{isotopologue}/"
        line_lists = parse_immediate_children(
            fetch_html(isotopologue_url),
            isotopologue_url,
        )

        for line_list in line_lists:
            dataset_url = f"{isotopologue_url}{line_list}/"
            datasets.extend(
                parse_taurex_files(
                    fetch_html(dataset_url),
                    dataset_url,
                    molecule=molecule,
                    isotopologue=isotopologue,
                    line_list=line_list,
                )
            )

    return sorted(
        datasets,
        key=lambda item: (
            item["isotopologue"].lower(),
            item["lineList"].lower(),
            item["fileName"].lower(),
        ),
    )


def download_taurex_file(dataset: dict, cache_dir: Path) -> Path:
    if dataset.get("sourceType") == "local":
        return Path(dataset["localPath"])

    cache_dir.mkdir(parents=True, exist_ok=True)
    filename = Path(dataset["fileName"]).name
    destination = cache_dir / filename

    if destination.is_file() and destination.stat().st_size > 0:
        return destination

    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with requests.get(
            dataset["url"],
            headers=HTTP_HEADERS,
            stream=True,
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
        ) as response:
            response.raise_for_status()
            with temporary.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        output.write(chunk)

        temporary.replace(destination)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise

    return destination
