# ExoMol Opacity App Prototype

This repository contains a local prototype of a web interface for preparing
ExoCross opacity calculations from ExoMol line-list data.

## Overview

The application is split into two parts:

- Frontend: React + Vite, implemented mainly in `src/App.jsx`.
- Backend: Python + FastAPI, implemented in `backend/main.py`.

The frontend lets a user select a molecule, isotopologue, line list, temperature,
spectral range, number of points, line profile, and mass. The backend reads
`backend/EXOMOL.master`, builds the available molecule and line-list options,
generates an ExoCross input file, attempts to discover and download the required
`.states`, `.trans`, and `.pf` files, and can run ExoCross if a valid executable
is configured.

## Current Status

This is currently a local workflow prototype. It demonstrates the web interface,
parameter submission, ExoMol catalogue parsing, dataset preparation, ExoCross
input-file generation, and job metadata/output links.

The project does not yet submit jobs to the UCL/ExoMol Linux server or queue
system. A real Linux ExoCross executable and the server-side job submission
method still need to be configured.

## Local Development

Install frontend dependencies:

```bash
npm install
```

Run the frontend:

```bash
npm run dev
```

Create and activate a Python environment for the backend, then install:

```bash
cd backend
pip install -r requirements.txt
```

Run the backend:

```bash
uvicorn main:app --host 127.0.0.1 --port 8000
```

By default, the frontend expects the backend API at:

```text
http://127.0.0.1:8000
```

## Important Environment Variables

- `EXOMOL_MASTER_FILE`: optional path to `EXOMOL.master`.
- `EXOMOL_JOBS_DIR`: directory where generated jobs are stored.
- `EXOMOL_DATASET_BASE`: ExoMol dataset base URL.
- `EXOCROSS_EXE`: path to a valid ExoCross executable.
- `EXOCROSS_AUTO_RUN`: set to `false` to generate input files without running ExoCross.

## Next Step

The main next step is to replace local ExoCross execution with a remote
server/HPC workflow: create or upload the input file on the server, submit it
through the available queue system or existing scripts, monitor status, and
retrieve output/log files.
