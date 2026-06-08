from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


EXOMOL_OPACITY_BASE = os.environ.get(
    "EXOMOL_OPACITY_BASE",
    "https://exomol.com/data/data-types/opacity",
).rstrip("/")
DOWNLOAD_TIMEOUT_SECONDS = int(
    os.environ.get("EXOMOL_DOWNLOAD_TIMEOUT_SECONDS", "180")
)
HTTP_HEADERS = {
    "User-Agent": "ExoMol-Opacity-App/0.5 (+local development)"
}
SAFE_SLUG = re.compile(r"^[A-Za-z0-9_+\-]+$")


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
        if filename.endswith(".xsec.TauREx.h5"):
            found[filename] = absolute_url

    datasets = []
    for filename, url in sorted(found.items()):
        configuration = filename
        match = re.search(
            r"(?:\.|__)(R\d.+)\.xsec\.TauREx\.h5$",
            filename,
        )
        if match:
            configuration = match.group(1)

        datasets.append(
            {
                "key": f"{molecule}/{isotopologue}/{line_list}/{filename}",
                "molecule": molecule,
                "isotopologue": isotopologue,
                "lineList": line_list,
                "dataset": f"{isotopologue}__{line_list}",
                "configuration": configuration,
                "fileName": filename,
                "url": url,
                "label": (
                    f"{isotopologue} / {line_list} / {filename}"
                ),
            }
        )

    return datasets


@lru_cache(maxsize=1)
def discover_opacity_molecules() -> list[dict]:
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


@lru_cache(maxsize=128)
def discover_taurex_datasets(molecule: str) -> list[dict]:
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
