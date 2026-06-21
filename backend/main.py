from __future__ import annotations

import bz2
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

try:
    from .opacity import get_opacity_options, get_opacity_spectrum
    from .opacity_catalog import (
        catalog_source,
        discover_opacity_molecules,
        discover_taurex_datasets,
        download_taurex_file,
    )
except ImportError:
    from opacity import get_opacity_options, get_opacity_spectrum
    from opacity_catalog import (
        catalog_source,
        discover_opacity_molecules,
        discover_taurex_datasets,
        download_taurex_file,
    )


def get_default_jobs_dir() -> Path:
    desktop = Path.home() / "Desktop"
    base = desktop if desktop.exists() else Path.home()
    return base / "ExoMolJobs"


def detect_default_exocross_exe(base_dir: Path) -> Path | None:
    candidates = [
        base_dir / "exocross.exe",
        base_dir / "exocross",
        base_dir / "bin" / "exocross.exe",
        base_dir / "bin" / "exocross",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


BASE_DIR = Path(__file__).resolve().parent
MASTER_FILE = Path(os.environ.get("EXOMOL_MASTER_FILE", str(BASE_DIR / "EXOMOL.master")))
JOBS_BASE_DIR = Path(os.environ.get("EXOMOL_JOBS_DIR", str(get_default_jobs_dir())))
EXOMOL_DATASET_BASE = os.environ.get("EXOMOL_DATASET_BASE", "https://exomol.com/data/molecules")
DEFAULT_EXOCROSS_EXE = detect_default_exocross_exe(BASE_DIR)
EXOCROSS_EXE = Path(os.environ["EXOCROSS_EXE"]) if os.environ.get("EXOCROSS_EXE") else DEFAULT_EXOCROSS_EXE
EXOCROSS_TIMEOUT_SECONDS = int(os.environ.get("EXOCROSS_TIMEOUT_SECONDS", "180"))
AUTO_RUN_ON_SUBMIT = env_bool("EXOCROSS_AUTO_RUN", True)
JOB_BUILDER_ENABLED = env_bool("EXOCROSS_JOB_BUILDER_ENABLED", False)
DOWNLOAD_TIMEOUT_SECONDS = int(os.environ.get("EXOMOL_DOWNLOAD_TIMEOUT_SECONDS", "180"))
TAUREX_H5_FILE = (
    Path(os.environ["TAUREX_H5_FILE"])
    if os.environ.get("TAUREX_H5_FILE")
    else BASE_DIR / "opacity_data" / "opacity.h5"
)
TAUREX_H5_CACHE_DIR = Path(
    os.environ.get("TAUREX_H5_CACHE_DIR", str(BASE_DIR / "opacity_data"))
)

JOBS_BASE_DIR.mkdir(parents=True, exist_ok=True)

HTTP_HEADERS = {
    "User-Agent": "ExoMol-Opacity-App/0.4 (+local development)"
}

# 你明确给过的精确质量
MASS_OVERRIDES: dict[tuple[str, str, str], float] = {
    ("NaH", "23Na-1H", "Rivlin"): 23.997594,
}

app = FastAPI(title="ExoMol Opacity App API", version="0.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_job_builder_enabled() -> None:
    if not JOB_BUILDER_ENABLED:
        raise HTTPException(
            status_code=404,
            detail="ExoCross job preparation is disabled in this deployment.",
        )


class SubmitRequest(BaseModel):
    molecule: str
    isotopologue: str
    lineList: str
    temperature: float = Field(gt=0)
    rangeMin: float = Field(ge=0)
    rangeMax: float = Field(gt=0)
    npoints: int = Field(gt=1)
    profile: Literal["Doppler"] = "Doppler"
    mass: float = Field(gt=0)


def slugify(value: str) -> str:
    value = value.strip()
    value = re.sub(r"[^\w\-.]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_") or "job"


def strip_trailing_comment(line: str) -> str:
    return re.sub(r"\s+#.*$", "", line.rstrip())


def read_master_lines(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(
            f"EXOMOL.master not found: {path}. "
            f"Please put EXOMOL.master into backend folder."
        )

    cleaned: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = strip_trailing_comment(raw).strip()
        if line:
            cleaned.append(line)
    return cleaned


def estimate_mass_from_iso_slug(iso_slug: str) -> float | None:
    total = 0.0

    for part in iso_slug.split("-"):
        part = part.replace("_p", "")
        match = re.fullmatch(r"(\d+)([A-Z][a-z]?)(\d*)", part)
        if not match:
            continue

        isotope_number, _element, count_text = match.groups()
        count = int(count_text) if count_text else 1
        total += int(isotope_number) * count

    return round(total, 6) if total > 0 else None


def build_dataset_files(iso_slug: str, line_list: str) -> dict[str, str]:
    return {
        "states": f"{iso_slug}__{line_list}.states",
        "transitions": f"{iso_slug}__{line_list}.trans",
        "pf": f"{iso_slug}__{line_list}.pf",
    }


@lru_cache(maxsize=1)
def load_catalog() -> dict:
    lines = read_master_lines(MASTER_FILE)

    if len(lines) < 6:
        raise RuntimeError("EXOMOL.master format is incomplete.")

    database_id = lines[0]
    database_version = lines[1]

    idx = 6
    molecules: list[dict] = []

    while idx < len(lines):
        alias_count = int(lines[idx])
        idx += 1

        aliases = lines[idx : idx + alias_count]
        idx += alias_count

        molecule_formula = lines[idx]
        idx += 1

        isotopologue_count = int(lines[idx])
        idx += 1

        iso_map: dict[str, dict] = {}

        for _ in range(isotopologue_count):
            if idx + 4 >= len(lines):
                raise RuntimeError("EXOMOL.master ended unexpectedly while reading isotopologues.")

            inchikey = lines[idx]
            iso_slug = lines[idx + 1]
            iso_formula = lines[idx + 2]
            dataset_name = lines[idx + 3]
            dataset_version = lines[idx + 4]
            idx += 5

            iso_entry = iso_map.setdefault(
                iso_slug,
                {
                    "key": iso_slug,
                    "label": iso_slug,
                    "isoFormula": iso_formula,
                    "inchikey": inchikey,
                    "lineLists": [],
                },
            )

            mass_da = MASS_OVERRIDES.get(
                (molecule_formula, iso_slug, dataset_name),
                estimate_mass_from_iso_slug(iso_slug),
            )

            iso_entry["lineLists"].append(
                {
                    "key": dataset_name,
                    "label": dataset_name,
                    "version": dataset_version,
                    "massDa": mass_da,
                    "files": build_dataset_files(iso_slug, dataset_name),
                }
            )

        molecules.append(
            {
                "key": molecule_formula,
                "label": molecule_formula,
                "aliases": aliases,
                "isotopologues": list(iso_map.values()),
            }
        )

    molecules.sort(key=lambda x: x["key"].lower())
    for molecule in molecules:
        molecule["isotopologues"].sort(key=lambda x: x["key"].lower())
        for iso in molecule["isotopologues"]:
            iso["lineLists"].sort(key=lambda x: x["key"].lower())

    return {
        "databaseId": database_id,
        "databaseVersion": database_version,
        "masterFile": str(MASTER_FILE),
        "molecules": molecules,
    }


def get_catalog_payload() -> dict:
    return load_catalog()


def resolve_line_list(molecule: str, isotopologue: str, line_list: str) -> dict:
    catalog = load_catalog()

    molecule_data = next((item for item in catalog["molecules"] if item["key"] == molecule), None)
    if not molecule_data:
        raise HTTPException(status_code=400, detail="Unsupported molecule.")

    iso_data = next(
        (item for item in molecule_data["isotopologues"] if item["key"] == isotopologue),
        None,
    )
    if not iso_data:
        raise HTTPException(status_code=400, detail="Unsupported isotopologue.")

    line_list_data = next((item for item in iso_data["lineLists"] if item["key"] == line_list), None)
    if not line_list_data:
        raise HTTPException(status_code=400, detail="Unsupported line list.")

    return {
        "molecule": molecule_data,
        "isotopologue": iso_data,
        "lineList": line_list_data,
    }


def build_output_stem(request: SubmitRequest) -> str:
    temp = f"{request.temperature:g}".replace(".", "p")
    span = f"{request.rangeMin:g}-{request.rangeMax:g}".replace(".", "p")
    return slugify(f"{request.molecule}_T{temp}K_{request.profile}_{span}cm-1")


def build_dataset_page_url(molecule: str, isotopologue: str, line_list: str) -> str:
    return (
        f"{EXOMOL_DATASET_BASE}/"
        f"{quote(molecule, safe='')}/"
        f"{quote(isotopologue, safe='')}/"
        f"{quote(line_list, safe='')}/"
    )


def basename_from_url(url: str) -> str:
    return unquote(Path(urlparse(url).path).name)


def link_matches_dataset_file(basename: str, prefix: str) -> bool:
    if not basename.startswith(prefix):
        return False

    valid_suffixes = (
        ".states",
        ".states.bz2",
        ".pf",
        ".pf.bz2",
        ".def",
        ".def.json",
        ".trans",
        ".trans.bz2",
    )
    return basename.endswith(valid_suffixes)


def parse_dataset_links_from_html(html_text: str, page_url: str, prefix: str) -> list[dict]:
    soup = BeautifulSoup(html_text, "html.parser")
    found: dict[str, str] = {}

    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href:
            continue

        absolute_url = urljoin(page_url, href)
        basename = basename_from_url(absolute_url)

        if link_matches_dataset_file(basename, prefix):
            found[basename] = absolute_url

    # BeautifulSoup 之外再做一次正则兜底
    for href in re.findall(r'href=["\']([^"\']+)["\']', html_text, flags=re.IGNORECASE):
        absolute_url = urljoin(page_url, href)
        basename = basename_from_url(absolute_url)
        if link_matches_dataset_file(basename, prefix):
            found[basename] = absolute_url

    items = [{"name": name, "url": url} for name, url in found.items()]
    return items


def choose_preferred_single_file(
    items: list[dict],
    suffixes_in_order: list[str],
) -> dict | None:
    for suffix in suffixes_in_order:
        for item in items:
            if item["name"].endswith(suffix):
                return item
    return None


def parse_transition_window_from_name(filename: str) -> tuple[float, float] | None:
    match = re.search(r"__([0-9]+(?:\.[0-9]+)?)-([0-9]+(?:\.[0-9]+)?)\.trans(?:\.bz2)?$", filename)
    if not match:
        return None
    start = float(match.group(1))
    end = float(match.group(2))
    return start, end


def transitions_overlap_range(filename: str, range_min: float, range_max: float) -> bool:
    window = parse_transition_window_from_name(filename)
    if window is None:
        return True
    start, end = window
    return not (end < range_min or start > range_max)


def sort_transition_items(items: list[dict]) -> list[dict]:
    def sort_key(item: dict):
        window = parse_transition_window_from_name(item["name"])
        if window is None:
            return (1, item["name"])
        return (0, window[0], window[1], item["name"])

    return sorted(items, key=sort_key)


def try_head_or_get(url: str) -> bool:
    try:
        response = requests.head(
            url,
            headers=HTTP_HEADERS,
            allow_redirects=True,
            timeout=30,
        )
        if response.ok:
            return True
    except Exception:
        pass

    try:
        response = requests.get(
            url,
            headers=HTTP_HEADERS,
            allow_redirects=True,
            stream=True,
            timeout=30,
        )
        ok = response.ok
        response.close()
        return ok
    except Exception:
        return False


def discover_remote_dataset_files(
    molecule: str,
    isotopologue: str,
    line_list: str,
    range_min: float,
    range_max: float,
) -> dict:
    dataset_page_url = build_dataset_page_url(molecule, isotopologue, line_list)
    prefix = f"{isotopologue}__{line_list}"

    response = requests.get(
        dataset_page_url,
        headers=HTTP_HEADERS,
        timeout=DOWNLOAD_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    all_links = parse_dataset_links_from_html(response.text, dataset_page_url, prefix)

    states_item = choose_preferred_single_file(all_links, [".states.bz2", ".states"])
    pf_item = choose_preferred_single_file(all_links, [".pf", ".pf.bz2"])

    transition_items = [
        item for item in all_links
        if item["name"].endswith(".trans") or item["name"].endswith(".trans.bz2")
    ]
    transition_items = sort_transition_items(transition_items)

    filtered_transition_items = [
        item for item in transition_items
        if transitions_overlap_range(item["name"], range_min, range_max)
    ]
    if filtered_transition_items:
        transition_items = filtered_transition_items

    # 如果页面里没抓到，就尝试简单文件名兜底
    if states_item is None:
        for candidate_name in [f"{prefix}.states.bz2", f"{prefix}.states"]:
            candidate_url = urljoin(dataset_page_url, candidate_name)
            if try_head_or_get(candidate_url):
                states_item = {"name": candidate_name, "url": candidate_url}
                break

    if pf_item is None:
        for candidate_name in [f"{prefix}.pf", f"{prefix}.pf.bz2"]:
            candidate_url = urljoin(dataset_page_url, candidate_name)
            if try_head_or_get(candidate_url):
                pf_item = {"name": candidate_name, "url": candidate_url}
                break

    if not transition_items:
        for candidate_name in [f"{prefix}.trans.bz2", f"{prefix}.trans"]:
            candidate_url = urljoin(dataset_page_url, candidate_name)
            if try_head_or_get(candidate_url):
                transition_items = [{"name": candidate_name, "url": candidate_url}]
                break

    return {
        "datasetPageUrl": dataset_page_url,
        "states": states_item,
        "pf": pf_item,
        "transitions": transition_items,
        "allDiscoveredLinks": all_links,
    }


def local_name_from_remote_name(remote_name: str) -> str:
    if remote_name.endswith(".bz2"):
        return remote_name[:-4]
    return remote_name


def download_file(url: str, destination_path: Path) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    with requests.get(url, headers=HTTP_HEADERS, stream=True, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
        response.raise_for_status()
        with open(destination_path, "wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    output.write(chunk)


def download_and_prepare_remote_file(
    remote_item: dict,
    job_dir: Path,
) -> dict:
    remote_name = remote_item["name"]
    remote_url = remote_item["url"]
    local_name = local_name_from_remote_name(remote_name)
    local_path = job_dir / local_name

    if local_path.exists():
        return {
            "remoteName": remote_name,
            "remoteUrl": remote_url,
            "localName": local_name,
            "localPath": str(local_path),
        }

    if remote_name.endswith(".bz2"):
        compressed_path = job_dir / remote_name
        download_file(remote_url, compressed_path)
        with bz2.open(compressed_path, "rb") as src, open(local_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
    else:
        download_file(remote_url, local_path)

    return {
        "remoteName": remote_name,
        "remoteUrl": remote_url,
        "localName": local_name,
        "localPath": str(local_path),
    }


def download_and_prepare_dataset_files(
    remote_dataset: dict,
    job_dir: Path,
) -> dict:
    prepared_files: dict[str, object] = {}
    remote_files: dict[str, object] = {}
    missing_files: list[str] = []

    states_item = remote_dataset.get("states")
    pf_item = remote_dataset.get("pf")
    transition_items = remote_dataset.get("transitions", [])

    if states_item is not None:
        states_local = download_and_prepare_remote_file(states_item, job_dir)
        prepared_files["states"] = states_local["localPath"]
        remote_files["states"] = states_local["remoteUrl"]
    else:
        missing_files.append("states")

    if pf_item is not None:
        pf_local = download_and_prepare_remote_file(pf_item, job_dir)
        prepared_files["pf"] = pf_local["localPath"]
        remote_files["pf"] = pf_local["remoteUrl"]
    else:
        missing_files.append("pf")

    prepared_transitions: list[str] = []
    remote_transitions: list[str] = []

    if transition_items:
        for item in transition_items:
            local = download_and_prepare_remote_file(item, job_dir)
            prepared_transitions.append(local["localPath"])
            remote_transitions.append(local["remoteUrl"])
        prepared_files["transitions"] = prepared_transitions
        remote_files["transitions"] = remote_transitions
    else:
        missing_files.append("transitions")

    return {
        "preparedFiles": prepared_files,
        "remoteFiles": remote_files,
        "missingFiles": missing_files,
        "datasetPageUrl": remote_dataset.get("datasetPageUrl"),
    }


def build_input_text(
    request: SubmitRequest,
    states_name: str,
    pf_name: str,
    transition_names: list[str],
    output_stem: str,
) -> str:
    lines = [
        f"Temperature {request.temperature:g}",
        "",
        f"Range {request.rangeMin:g} {request.rangeMax:g} (cm-1)",
        "",
        f"Npoints {request.npoints}",
        "",
        (
            f"(This file was generated by the ExoMol Opacity App "
            f"for {request.molecule} / {request.isotopologue} / {request.lineList}.)"
        ),
        "",
        "absorption",
        request.profile,
        "",
        f"mass {request.mass:g}",
        "",
        f"States {states_name}",
    ]

    if len(transition_names) <= 1:
        if transition_names:
            lines.append(f"Transitions {transition_names[0]}")
    else:
        lines.append("Transitions")
        for name in transition_names:
            lines.append(f" {name}")
        lines.append("end")

    lines.extend(
        [
            "",
            f"pffile {pf_name}",
            "",
            f"output {output_stem}",
            "",
        ]
    )

    return "\n".join(lines)


def run_exocross(
    job_dir: Path,
    input_filename: str,
    output_stem: str,
) -> dict:
    if EXOCROSS_EXE is None or not EXOCROSS_EXE.exists():
        return {
            "status": "waiting_for_exocross",
            "message": "Input and dataset files are ready, but exocross executable is not configured.",
            "outputFile": None,
            "stdoutFile": None,
            "stderrFile": None,
            "returnCode": None,
        }

    output_path = job_dir / f"{output_stem}.out"
    stdout_path = job_dir / "exocross_stdout.txt"
    stderr_path = job_dir / "exocross_stderr.txt"

    if output_path.exists():
        output_path.unlink()

    try:
        completed = subprocess.run(
            [str(EXOCROSS_EXE), input_filename],
            cwd=job_dir,
            text=True,
            capture_output=True,
            timeout=EXOCROSS_TIMEOUT_SECONDS,
        )

        stdout_path.write_text(completed.stdout or "", encoding="utf-8", errors="ignore")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8", errors="ignore")

        if output_path.exists():
            return {
                "status": "completed",
                "message": "ExoCross run completed and output file was generated.",
                "outputFile": str(output_path),
                "stdoutFile": str(stdout_path),
                "stderrFile": str(stderr_path),
                "returnCode": completed.returncode,
            }

        return {
            "status": "run_failed",
            "message": "ExoCross finished, but no .out file was generated.",
            "outputFile": None,
            "stdoutFile": str(stdout_path),
            "stderrFile": str(stderr_path),
            "returnCode": completed.returncode,
        }

    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text((exc.stdout or ""), encoding="utf-8", errors="ignore")
        stderr_path.write_text((exc.stderr or ""), encoding="utf-8", errors="ignore")
        return {
            "status": "run_failed",
            "message": f"ExoCross run timed out after {EXOCROSS_TIMEOUT_SECONDS} seconds.",
            "outputFile": None,
            "stdoutFile": str(stdout_path),
            "stderrFile": str(stderr_path),
            "returnCode": None,
        }
    except Exception as exc:
        stderr_path.write_text(str(exc), encoding="utf-8", errors="ignore")
        return {
            "status": "run_failed",
            "message": f"Failed to run ExoCross: {exc}",
            "outputFile": None,
            "stdoutFile": None,
            "stderrFile": str(stderr_path),
            "returnCode": None,
        }


def metadata_path_for(job_dir: Path) -> Path:
    return job_dir / "metadata.json"


def save_metadata(job_dir: Path, metadata: dict) -> None:
    metadata_path_for(job_dir).write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_job_metadata(job_id: str) -> tuple[Path, dict]:
    if not re.fullmatch(r"\d{8}_\d{6}_[0-9a-f]{8}", job_id):
        raise HTTPException(status_code=404, detail="Job not found.")

    job_dir = JOBS_BASE_DIR / job_id
    metadata_path = metadata_path_for(job_dir)
    if not metadata_path.exists():
        raise HTTPException(status_code=404, detail="Job not found.")

    return job_dir, json.loads(metadata_path.read_text(encoding="utf-8"))


def build_job_response(metadata: dict) -> dict:
    output_file = metadata.get("outputFile")
    output_name = Path(output_file).name if output_file else None

    stdout_file = metadata.get("stdoutFile")
    stderr_file = metadata.get("stderrFile")

    return {
        "jobId": metadata["jobId"],
        "status": metadata["status"],
        "jobDir": metadata["jobDir"],
        "inputFileName": Path(metadata["inputFile"]).name,
        "inputFilePath": metadata["inputFile"],
        "downloadUrl": f"/api/jobs/{metadata['jobId']}/input",
        "inputContent": metadata["inputContent"],
        "resolvedFiles": metadata["resolvedFiles"],
        "preparedFiles": metadata.get("preparedFiles", {}),
        "remoteFiles": metadata.get("remoteFiles", {}),
        "missingFiles": metadata.get("missingFiles", []),
        "datasetPageUrl": metadata.get("datasetPageUrl"),
        "message": metadata["message"],
        "outputFileName": output_name,
        "outputFilePath": output_file,
        "outputDownloadUrl": f"/api/jobs/{metadata['jobId']}/output" if output_file else None,
        "stdoutFilePath": stdout_file,
        "stderrFilePath": stderr_file,
        "stdoutDownloadUrl": f"/api/jobs/{metadata['jobId']}/stdout" if stdout_file else None,
        "stderrDownloadUrl": f"/api/jobs/{metadata['jobId']}/stderr" if stderr_file else None,
        "returnCode": metadata.get("returnCode"),
        "createdAt": metadata.get("createdAt"),
        "runAttempted": metadata.get("runAttempted", False),
    }


@app.get("/")
def root() -> dict:
    try:
        catalog = load_catalog()
        return {
            "message": "ExoMol Opacity App backend is running.",
            "jobsBaseDir": str(JOBS_BASE_DIR),
            "databaseVersion": catalog["databaseVersion"],
            "moleculeCount": len(catalog["molecules"]),
            "masterFile": catalog["masterFile"],
            "exocrossExe": str(EXOCROSS_EXE) if EXOCROSS_EXE else None,
            "jobBuilderEnabled": JOB_BUILDER_ENABLED,
            "datasetBaseUrl": EXOMOL_DATASET_BASE,
            "opacityCatalogSource": catalog_source(),
            "taurexOpacityFile": str(TAUREX_H5_FILE),
            "taurexOpacityFileAvailable": TAUREX_H5_FILE.is_file(),
        }
    except Exception as exc:
        return {
            "message": "Backend started, but catalog loading failed.",
            "error": str(exc),
            "masterFile": str(MASTER_FILE),
        }


@app.get("/api/options", include_in_schema=JOB_BUILDER_ENABLED)
def get_options() -> dict:
    require_job_builder_enabled()
    try:
        return get_catalog_payload()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load EXOMOL.master: {exc}")


def configured_taurex_matches(dataset: dict) -> bool:
    if not TAUREX_H5_FILE.is_file():
        return False

    try:
        options = get_opacity_options(TAUREX_H5_FILE)
    except (OSError, ValueError):
        return False

    return (
        options.get("molecule") == dataset["molecule"].replace("_p", "+")
        and options.get("dataset") == dataset["dataset"]
    )


def resolve_taurex_file(
    molecule: str | None = None,
    dataset_key: str | None = None,
) -> tuple[Path, dict | None]:
    if molecule is None and dataset_key is None:
        if TAUREX_H5_FILE.is_file():
            return TAUREX_H5_FILE, None
        raise HTTPException(
            status_code=503,
            detail=(
                "TauREx opacity file is not configured. Set TAUREX_H5_FILE "
                "to the path of a .h5 opacity file."
            ),
        )

    if not molecule or not dataset_key:
        raise HTTPException(
            status_code=400,
            detail="Both molecule and datasetKey are required.",
        )

    try:
        datasets = discover_taurex_datasets(molecule)
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to read the ExoMol opacity catalogue: {exc}",
        ) from exc

    dataset = next(
        (item for item in datasets if item["key"] == dataset_key),
        None,
    )
    if dataset is None:
        raise HTTPException(
            status_code=404,
            detail="The selected TauREx opacity dataset was not found.",
        )

    if configured_taurex_matches(dataset):
        return TAUREX_H5_FILE, dataset

    try:
        return download_taurex_file(dataset, TAUREX_H5_CACHE_DIR), dataset
    except (OSError, KeyError, requests.RequestException) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to prepare the selected TauREx file: {exc}",
        ) from exc


@app.get("/api/opacities/catalog")
def get_taurex_opacity_catalog() -> dict:
    try:
        molecules = discover_opacity_molecules()
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to read the ExoMol opacity catalogue: {exc}",
        ) from exc

    catalog_labels = {
        molecule["key"].replace("+", "_p"): molecule["label"]
        for molecule in load_catalog()["molecules"]
    }
    for molecule in molecules:
        molecule["label"] = catalog_labels.get(
            molecule["key"],
            molecule["label"],
        )

    return {
        "molecules": molecules,
        "source": catalog_source(),
    }


@app.get("/api/opacities/datasets")
def get_taurex_opacity_datasets(molecule: str = Query(min_length=1)) -> dict:
    try:
        datasets = discover_taurex_datasets(molecule)
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to read opacity datasets for {molecule}: {exc}",
        ) from exc

    return {
        "molecule": molecule,
        "datasets": datasets,
    }


@app.get("/api/opacities/options")
def get_taurex_opacity_options(
    molecule: str | None = Query(None),
    dataset_key: str | None = Query(None, alias="datasetKey"),
) -> dict:
    opacity_file, dataset = resolve_taurex_file(molecule, dataset_key)
    try:
        payload = get_opacity_options(opacity_file)
        if dataset:
            payload.update(
                {
                    "datasetKey": dataset["key"],
                    "sourceUrl": dataset.get("url"),
                    "sourceType": dataset.get("sourceType", "remote"),
                    "configuration": dataset["configuration"],
                }
            )
        return payload
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read TauREx opacity file: {exc}",
        ) from exc


@app.get("/api/opacities/spectrum")
def get_taurex_opacity_spectrum(
    temperature: float = Query(gt=0),
    pressure: float = Query(gt=0),
    max_points: int = Query(2000, alias="maxPoints", ge=100, le=5000),
    molecule: str | None = Query(None),
    dataset_key: str | None = Query(None, alias="datasetKey"),
) -> dict:
    opacity_file, dataset = resolve_taurex_file(molecule, dataset_key)
    try:
        payload = get_opacity_spectrum(
            opacity_file,
            temperature=temperature,
            pressure=pressure,
            max_points=max_points,
        )
        if dataset:
            payload["datasetKey"] = dataset["key"]
            payload["sourceType"] = dataset.get("sourceType", "remote")
        return payload
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read TauREx opacity spectrum: {exc}",
        ) from exc


@app.post("/api/submit", include_in_schema=JOB_BUILDER_ENABLED)
def submit_job(payload: SubmitRequest) -> dict:
    require_job_builder_enabled()
    if payload.rangeMax <= payload.rangeMin:
        raise HTTPException(status_code=400, detail="rangeMax must be greater than rangeMin.")

    resolved = resolve_line_list(payload.molecule, payload.isotopologue, payload.lineList)

    output_stem = build_output_stem(payload)
    job_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    job_dir = JOBS_BASE_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    remote_dataset = None
    download_result = None
    discovery_error = None

    try:
        remote_dataset = discover_remote_dataset_files(
            molecule=payload.molecule,
            isotopologue=payload.isotopologue,
            line_list=payload.lineList,
            range_min=payload.rangeMin,
            range_max=payload.rangeMax,
        )
        download_result = download_and_prepare_dataset_files(remote_dataset, job_dir)
    except Exception as exc:
        discovery_error = str(exc)
        download_result = {
            "preparedFiles": {},
            "remoteFiles": {},
            "missingFiles": ["states", "pf", "transitions"],
            "datasetPageUrl": build_dataset_page_url(payload.molecule, payload.isotopologue, payload.lineList),
        }

    # 输入文件引用本地 job 目录中的真实文件名；如果发现失败，则退回到默认命名
    states_name = resolved["lineList"]["files"]["states"]
    pf_name = resolved["lineList"]["files"]["pf"]
    transition_names = [resolved["lineList"]["files"]["transitions"]]

    prepared_files = download_result["preparedFiles"]

    if isinstance(prepared_files.get("states"), str):
        states_name = Path(prepared_files["states"]).name
    if isinstance(prepared_files.get("pf"), str):
        pf_name = Path(prepared_files["pf"]).name
    if isinstance(prepared_files.get("transitions"), list) and prepared_files["transitions"]:
        transition_names = [Path(path).name for path in prepared_files["transitions"]]

    input_filename = f"{output_stem}.inp"
    input_path = job_dir / input_filename

    input_text = build_input_text(
        request=payload,
        states_name=states_name,
        pf_name=pf_name,
        transition_names=transition_names,
        output_stem=output_stem,
    )
    input_path.write_text(input_text, encoding="utf-8")

    status = "input_created"
    message = "Input file created successfully."
    output_file = None
    stdout_file = None
    stderr_file = None
    return_code = None
    run_attempted = False

    if discovery_error is not None:
        status = "download_failed"
        message = f"Input file created, but automatic ExoMol download failed: {discovery_error}"
    elif download_result["missingFiles"]:
        status = "waiting_for_dataset_files"
        message = "Input file created, but some dataset files could not be discovered or downloaded."
    elif AUTO_RUN_ON_SUBMIT:
        run_attempted = True
        run_result = run_exocross(
            job_dir=job_dir,
            input_filename=input_filename,
            output_stem=output_stem,
        )
        status = run_result["status"]
        message = run_result["message"]
        output_file = run_result["outputFile"]
        stdout_file = run_result["stdoutFile"]
        stderr_file = run_result["stderrFile"]
        return_code = run_result["returnCode"]
    else:
        status = "waiting_for_exocross"
        message = "Input file and dataset files are ready. Auto-run is disabled."

    metadata = {
        "jobId": job_id,
        "status": status,
        "message": message,
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "jobDir": str(job_dir),
        "inputFile": str(input_path),
        "inputContent": input_text,
        "request": payload.model_dump(),
        "resolvedFiles": resolved["lineList"]["files"],
        "preparedFiles": download_result["preparedFiles"],
        "remoteFiles": download_result["remoteFiles"],
        "missingFiles": download_result["missingFiles"],
        "datasetPageUrl": download_result["datasetPageUrl"],
        "outputFile": output_file,
        "stdoutFile": stdout_file,
        "stderrFile": stderr_file,
        "returnCode": return_code,
        "runAttempted": run_attempted,
        "databaseVersion": load_catalog()["databaseVersion"],
    }

    save_metadata(job_dir, metadata)
    return build_job_response(metadata)


@app.get("/api/jobs/{job_id}", include_in_schema=JOB_BUILDER_ENABLED)
def get_job(job_id: str) -> dict:
    require_job_builder_enabled()
    _, metadata = load_job_metadata(job_id)
    return metadata


@app.get("/api/jobs/{job_id}/input", include_in_schema=JOB_BUILDER_ENABLED)
def download_input_file(job_id: str):
    require_job_builder_enabled()
    _, metadata = load_job_metadata(job_id)
    input_path = Path(metadata["inputFile"])

    if not input_path.exists():
        raise HTTPException(status_code=404, detail="Input file not found.")

    return FileResponse(
        path=input_path,
        media_type="text/plain",
        filename=input_path.name,
    )


@app.get("/api/jobs/{job_id}/output", include_in_schema=JOB_BUILDER_ENABLED)
def download_output_file(job_id: str):
    require_job_builder_enabled()
    _, metadata = load_job_metadata(job_id)
    output_file = metadata.get("outputFile")
    if not output_file:
        raise HTTPException(status_code=404, detail="Output file not found.")

    output_path = Path(output_file)
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Output file not found.")

    return FileResponse(
        path=output_path,
        media_type="text/plain",
        filename=output_path.name,
    )


@app.get("/api/jobs/{job_id}/stdout", include_in_schema=JOB_BUILDER_ENABLED)
def download_stdout_file(job_id: str):
    require_job_builder_enabled()
    _, metadata = load_job_metadata(job_id)
    stdout_file = metadata.get("stdoutFile")
    if not stdout_file:
        raise HTTPException(status_code=404, detail="stdout log not found.")

    stdout_path = Path(stdout_file)
    if not stdout_path.exists():
        raise HTTPException(status_code=404, detail="stdout log not found.")

    return FileResponse(
        path=stdout_path,
        media_type="text/plain",
        filename=stdout_path.name,
    )


@app.get("/api/jobs/{job_id}/stderr", include_in_schema=JOB_BUILDER_ENABLED)
def download_stderr_file(job_id: str):
    require_job_builder_enabled()
    _, metadata = load_job_metadata(job_id)
    stderr_file = metadata.get("stderrFile")
    if not stderr_file:
        raise HTTPException(status_code=404, detail="stderr log not found.")

    stderr_path = Path(stderr_file)
    if not stderr_path.exists():
        raise HTTPException(status_code=404, detail="stderr log not found.")

    return FileResponse(
        path=stderr_path,
        media_type="text/plain",
        filename=stderr_path.name,
    )
