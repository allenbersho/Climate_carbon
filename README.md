# CarbonTrack

CarbonTrack is a backend platform for **Measurement, Reporting, and Verification (MRV)** of carbon-removal projects (afforestation, regenerative agriculture, and biochar).

## Features & Progress
- **Phase 0: Setup and skeleton** (FastAPI, SQLAlchemy 2.0, Pydantic v2, PostgreSQL/SQLite fallback, Dependency Injection).

## Quickstart

### 1. Environment Configuration
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

### 2. Run the API Locally
```bash
uvicorn app.main:app --reload
```
Interactive API docs are available at `http://localhost:8000/docs`.

### 3. Run Tests
```bash
pytest
```
