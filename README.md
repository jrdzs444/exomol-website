# ExoMol Opacity Visualizer

A containerized web application for discovering and visualizing existing
ExoMolOP TauREx cross-section data.

The production scope is intentionally narrow: users select a molecule,
isotopologue, published opacity dataset, temperature, pressure, and browser
display resolution, then inspect the pre-calculated cross-section spectrum.
ExoCross/HPC job submission is disabled by default and should remain future work
until authentication, quota control, queue integration, and server policy are
agreed.

## Quick Start

Prerequisite: Docker Desktop or Docker Engine with Docker Compose.

```bash
git clone https://github.com/jrdzs444/exomol-website.git
cd exomol-website
docker compose up --build
```

Open:

```text
http://127.0.0.1:5173/
```

The backend is not exposed directly by Docker Compose. The frontend Nginx
container proxies `/api` requests to the backend container.

## Current Functionality

- Reads the ExoMolOP opacity catalogue dynamically rather than hard-coding
  molecule and dataset options.
- Ships with Christian Hill's `backend/opacity-links.txt` catalogue, filtering it
  to currently supported `.xsec.TauREx.h5` files.
- Can use a server-local HDF5 data directory when `EXOMOL_OPACITY_DATA_DIR` is
  configured.
- Maps catalogue `/db/...` entries to server-local files when the ExoMol data
  directory is mounted; otherwise it falls back to downloading the selected
  TauREx HDF5 file.
- Falls back to the live ExoMolOP web catalogue only when no local/link-file
  catalogue is available.
- Lists published `.xsec.TauREx.h5` datasets by molecule, isotopologue, and
  dataset.
- Reads temperature and pressure grids from the selected HDF5 file.
- Returns one pressure-temperature cross-section slice from FastAPI.
- Down-samples large spectra to a browser-friendly display resolution.
- Displays an interactive Plotly graph with hover, zoom, pan, and PNG export.

Only TauREx cross-section HDF5 files are used by the visualizer. Other ExoMolOP
formats, including petitRADTRANS and NEMESIS k-tables, are intentionally
excluded.

## ExoWeb / Podman Deployment

On `exoweb`, the app can be built and run with Podman under the project account.
For the public `https://exomol.com/opacityapp/` deployment, build the frontend
with relative asset paths:

```bash
podman build --build-arg VITE_BASE_PATH=./ -t exomol-opacity-app-frontend .
podman build -t exomol-opacity-app-backend ./backend
```

Run the backend on the internal Podman network only:

```bash
mkdir -p /mnt/data/rundongji/jobs /mnt/data/rundongji/opacities
podman network create exomol-net

podman run -d \
  --name backend \
  --network exomol-net \
  --network-alias backend \
  -e EXOMOL_OPACITY_DATA_DIR=/data/exomol3_data \
  -e EXOMOL_JOBS_DIR=/data/jobs \
  -e TAUREX_H5_CACHE_DIR=/data/opacities \
  -e EXOCROSS_JOB_BUILDER_ENABLED=false \
  -e EXOCROSS_AUTO_RUN=false \
  -v /mnt/data/exomol/exomol3_data:/data/exomol3_data:ro,Z \
  -v /mnt/data/rundongji/jobs:/data/jobs:Z \
  -v /mnt/data/rundongji/opacities:/data/opacities:Z \
  exomol-opacity-app-backend
```

Run the frontend:

```bash
podman run -d \
  --name frontend \
  --network exomol-net \
  -p 5173:80 \
  exomol-opacity-app-frontend
```

The public web server should then proxy `https://exomol.com/opacityapp/` to the
frontend listener on the server. The backend port should not be opened publicly.

## Server-Local Opacity Data

Christian Hill confirmed that the ExoMol opacity data are stored on `exoweb` at:

```text
/mnt/data/exomol/exomol3_data/
```

The directory structure is:

```text
<molecule>/<isotopologue>/<dataset>/
```

For example:

```text
BeH/9Be-1H/Darby-Lewis/
```

Mount this directory read-only into the backend container and set
`EXOMOL_OPACITY_DATA_DIR`. The bundled `backend/opacity-links.txt` catalogue
uses `/db/...` paths and the backend maps those paths onto this mounted data
directory when matching files exist.

Example:

```bash
podman run -d \
  --name backend \
  --network exomol-net \
  --network-alias backend \
  -e EXOMOL_OPACITY_DATA_DIR=/data/exomol3_data \
  -e EXOMOL_JOBS_DIR=/data/jobs \
  -e TAUREX_H5_CACHE_DIR=/data/opacities \
  -e EXOCROSS_JOB_BUILDER_ENABLED=false \
  -v /mnt/data/exomol/exomol3_data:/data/exomol3_data:ro,Z \
  -v /mnt/data/rundongji/jobs:/data/jobs:Z \
  -v /mnt/data/rundongji/opacities:/data/opacities:Z \
  exomol-opacity-app-backend
```

When `EXOMOL_OPACITY_DATA_DIR` is set, selected spectra are read directly from
disk whenever the bundled catalogue entry maps to an existing local file. When
it is not set, the app uses the same catalogue to download selected HDF5 files
into the cache directory. You can replace or refresh the catalogue by mounting a
new file and setting `EXOMOL_OPACITY_LINKS_FILE`.

## Development Without Docker

Install and run the frontend:

```bash
npm ci
npm run dev
```

In a separate terminal, create a Python environment and run the backend:

```bash
cd backend
python -m venv .venv
# Activate .venv for your shell
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000
```

Vite proxies `/api` requests to `http://127.0.0.1:8000`.

## Verification

```bash
npm ci
npm run lint
npm run build
python -m unittest discover -s backend/tests -v
docker compose config
docker compose build
```

Useful server checks:

```bash
podman ps
curl -I http://127.0.0.1:5173/opacityapp/
podman exec frontend wget -q -O - http://backend:8000/
podman logs frontend
podman logs backend
```

## Configuration

- `EXOMOL_OPACITY_DATA_DIR`: optional read-only directory containing local
  `.xsec.TauREx.h5` files.
- `EXOMOL_OPACITY_LINKS_FILE`: optional opacity link catalogue. If unset, the
  backend uses the bundled `backend/opacity-links.txt` file when present.
- `EXOMOL_OPACITY_LINK_BASE`: base URL for relative catalogue paths, defaulting
  to `https://exomol.com`.
- `EXOMOL_OPACITY_BASE`: ExoMolOP web catalogue URL used when no local data
  directory or link-file catalogue is configured.
- `EXOMOL_DOWNLOAD_TIMEOUT_SECONDS`: remote download timeout.
- `TAUREX_H5_FILE`: optional single local TauREx HDF5 file.
- `TAUREX_H5_CACHE_DIR`: downloaded HDF5 cache directory.
- `EXOMOL_JOBS_DIR`: generated job directory for disabled legacy workflows.
- `EXOCROSS_JOB_BUILDER_ENABLED`: defaults to `false`.
- `EXOCROSS_AUTO_RUN`: defaults to `false` in container deployments.
- `EXOCROSS_EXE`: optional path to a Linux-compatible ExoCross executable.
- `EXOMOL_LINE_LIST_DATA_DIR`: optional read-only ExoMol line-list data
  directory. If unset, the backend reuses `EXOMOL_OPACITY_DATA_DIR` when
  available.
- `EXOCROSS_MAX_NPOINTS`: maximum points allowed for a generated calculation.
- `EXOCROSS_MAX_RANGE_WIDTH`: maximum submitted spectral range width in cm-1.
- `EXOCROSS_MAX_TRANSITION_FILES`: maximum number of transition chunks a job may
  prepare.
- `VITE_BASE_PATH`: frontend build base path. The container default is `./`,
  which keeps asset and API URLs relative so the app can run under
  `/opacityapp/` or another proxied sub-path.
- `VITE_API_BASE_URL`: optional explicit API prefix. If unset, the frontend
  derives the API prefix from `VITE_BASE_PATH`.

## Task 2 / ExoCross Job Builder

The Job Builder tab is no longer hard-coded off in the frontend. It reads
`/api/runtime` and enables the form only when the backend deployment is
configured for it.

For a controlled private deployment that prepares job inputs without running
ExoCross automatically:

```bash
-e EXOCROSS_JOB_BUILDER_ENABLED=true \
-e EXOCROSS_AUTO_RUN=false \
-e EXOMOL_LINE_LIST_DATA_DIR=/data/exomol3_data
```

For a deployment that actually runs ExoCross, the backend also needs a real
Linux-compatible executable:

```bash
-e EXOCROSS_JOB_BUILDER_ENABLED=true \
-e EXOCROSS_AUTO_RUN=true \
-e EXOCROSS_EXE=/path/to/exocross
```

The current `exoweb` account has the ExoMol data directory and job storage, but
no `exocross`, `sbatch`, `squeue`, or `qsub` command is available in `PATH`.
Therefore the public production deployment should keep Task 2 disabled until
Christian/Edd provide the approved ExoCross executable or HPC submission script.

When enabled, the backend validates molecule/isotopologue/line-list choices
against `EXOMOL.master`, applies range and size limits, writes a per-job working
directory, resolves `.states`, `.trans`, and `.pf` files from the local ExoMol
data directory when possible, and exposes job status, input download, output
download, stdout/stderr logs, and a best-effort two-column output spectrum API.

## Scope Notes From Christian Hill

- The first production version should remain a read-only visualizer for existing
  pre-calculated opacity data.
- Anonymous read-only access is reasonable, subject to agreement from Janahan
  and Sergey.
- New ExoCross/HPC calculation submission requires a separate database,
  metadata, quota, authentication, and queue-management decision and remains
  future work.
- Browser display should be down-sampled for desktop users. The UI therefore
  defaults to 2,000 displayed points and no longer offers very large display
  resolutions.
