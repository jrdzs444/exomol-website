# ExoMol Opacity Visualizer

A containerized web application for discovering and visualizing existing
ExoMolOP TauREx cross-section data.

The production scope is intentionally narrow: users select a published opacity
dataset, temperature, pressure, and browser display resolution, then inspect the
pre-calculated cross-section spectrum. ExoCross/HPC job submission is disabled
by default and should remain future work until authentication, quota control,
queue integration, and server policy are agreed.

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
- Can use a server-local HDF5 data directory when `EXOMOL_OPACITY_DATA_DIR` is
  configured.
- Falls back to the live ExoMolOP catalogue and caches downloaded TauREx HDF5
  files when no local data directory is configured.
- Lists published `.xsec.TauREx.h5` datasets for each molecule.
- Reads temperature and pressure grids from the selected HDF5 file.
- Returns one pressure-temperature cross-section slice from FastAPI.
- Down-samples large spectra to a browser-friendly display resolution.
- Displays an interactive Plotly graph with hover, zoom, pan, and PNG export.

Only TauREx cross-section HDF5 files are used by the visualizer. Other ExoMolOP
formats, including petitRADTRANS and NEMESIS k-tables, are intentionally
excluded.

## ExoWeb / Podman Deployment

On `exoweb`, the app can be built and run with Podman under the project account.
For a public `/opacity/` deployment, build the frontend with:

```bash
podman build --build-arg VITE_BASE_PATH=/opacity/ -t exomol-opacity-app-frontend .
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
  -e EXOMOL_JOBS_DIR=/data/jobs \
  -e TAUREX_H5_CACHE_DIR=/data/opacities \
  -e EXOCROSS_JOB_BUILDER_ENABLED=false \
  -e EXOCROSS_AUTO_RUN=false \
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

The public web server should then proxy the chosen public path, for example
`https://exomol.com/opacity/`, to the frontend listener on the server. The
backend port should not be opened publicly.

## Server-Local Opacity Data

If ExoMol provides a read-only directory containing published TauREx HDF5 files,
mount it into the backend container and set `EXOMOL_OPACITY_DATA_DIR`.

Example:

```bash
podman run -d \
  --name backend \
  --network exomol-net \
  --network-alias backend \
  -e EXOMOL_OPACITY_DATA_DIR=/data/exomol-opacities \
  -e EXOMOL_JOBS_DIR=/data/jobs \
  -e TAUREX_H5_CACHE_DIR=/data/opacities \
  -e EXOCROSS_JOB_BUILDER_ENABLED=false \
  -v /path/on/server/opacities:/data/exomol-opacities:ro,Z \
  -v /mnt/data/rundongji/jobs:/data/jobs:Z \
  -v /mnt/data/rundongji/opacities:/data/opacities:Z \
  exomol-opacity-app-backend
```

When `EXOMOL_OPACITY_DATA_DIR` is set, the catalogue is generated from local
`.xsec.TauREx.h5` files and selected spectra are read directly from disk. When
it is not set, the app uses the live ExoMolOP web catalogue and downloads
selected HDF5 files into the cache directory.

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
curl -I http://127.0.0.1:5173/
podman exec frontend wget -q -O - http://backend:8000/
podman logs frontend
podman logs backend
```

## Configuration

- `EXOMOL_OPACITY_DATA_DIR`: optional read-only directory containing local
  `.xsec.TauREx.h5` files.
- `EXOMOL_OPACITY_BASE`: ExoMolOP web catalogue URL used when no local data
  directory is configured.
- `EXOMOL_DOWNLOAD_TIMEOUT_SECONDS`: remote download timeout.
- `TAUREX_H5_FILE`: optional single local TauREx HDF5 file.
- `TAUREX_H5_CACHE_DIR`: downloaded HDF5 cache directory.
- `EXOMOL_JOBS_DIR`: generated job directory for disabled legacy workflows.
- `EXOCROSS_JOB_BUILDER_ENABLED`: defaults to `false`.
- `EXOCROSS_AUTO_RUN`: defaults to `false` in container deployments.
- `VITE_BASE_PATH`: frontend build base path, for example `/opacity/`.
- `VITE_API_BASE_URL`: optional explicit API prefix. If unset, the frontend
  derives the API prefix from `VITE_BASE_PATH`.
