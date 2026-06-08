# ExoMol Opacity Visualizer

A containerized web application for discovering and visualizing existing
ExoMolOP TauREx cross-section data.

The short-term project deliverable is the visualizer: users select a molecule,
published TauREx dataset, temperature, and pressure, then inspect an interactive
cross-section plot at a browser-friendly resolution.

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

No local Node.js or Python installation is required. The first time a dataset is
selected, its TauREx HDF5 file is downloaded from ExoMol and cached in a Docker
volume. These files can be hundreds of megabytes, so the first load may take
some time.

Stop the application with:

```bash
docker compose down
```

## Implemented Functionality

- Reads the live ExoMolOP opacity catalogue rather than using a hard-coded list.
- Lists molecules and all published `.xsec.TauREx.h5` datasets.
- Reads the temperature and pressure grids from the selected HDF5 file.
- Returns one pressure-temperature cross-section slice from FastAPI.
- Down-samples large spectra to a configurable browser display resolution.
- Displays an interactive Plotly graph with hover, zoom, pan, and PNG export.
- Caches downloaded HDF5 files in the `exomol_opacity_cache` Docker volume.
- Preserves the earlier ExoCross input/job-builder prototype in a separate tab.

Only TauREx cross-section HDF5 files are used by the visualizer. Other ExoMolOP
formats, including petitRADTRANS and NEMESIS k-tables, are intentionally
excluded.

## Architecture

- Frontend: React, Vite, Plotly, and Nginx.
- Backend: Python, FastAPI, h5py, NumPy, Requests, and Beautiful Soup.
- Catalogue source: `https://exomol.com/data/data-types/opacity/`.
- Persistent data:
  - `exomol_opacity_cache` stores downloaded TauREx HDF5 files.
  - `exomol_jobs` stores generated ExoCross prototype jobs.

Nginx serves the production frontend and proxies `/api` to FastAPI. The
containers expose:

- Web application: `http://127.0.0.1:5173/`
- Backend API and OpenAPI docs: `http://127.0.0.1:8000/docs`

## Current Scope

The visualizer works with existing, pre-calculated opacity data. It does not
submit computationally expensive opacity calculations to an HPC system.

The ExoCross job builder is retained as an earlier prototype. In Docker,
automatic ExoCross execution is disabled because no production HPC
authentication, user management, queue integration, or ExoCross executable is
configured.

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

## Configuration

The Docker defaults work without a `.env` file. Available backend environment
variables include:

- `EXOMOL_MASTER_FILE`: optional path to `EXOMOL.master`.
- `EXOMOL_JOBS_DIR`: generated job directory.
- `EXOMOL_DATASET_BASE`: ExoMol line-list base URL.
- `EXOMOL_OPACITY_BASE`: ExoMolOP opacity catalogue URL.
- `EXOMOL_DOWNLOAD_TIMEOUT_SECONDS`: remote download timeout.
- `TAUREX_H5_FILE`: optional local TauREx HDF5 file.
- `TAUREX_H5_CACHE_DIR`: downloaded HDF5 cache directory.
- `EXOCROSS_EXE`: optional ExoCross executable path.
- `EXOCROSS_AUTO_RUN`: enable or disable local ExoCross execution.
