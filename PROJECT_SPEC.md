# PROJECT_SPEC.md: CarbonTrack

> Source of truth for the project. The agent reads this at the start of every session.
> Update the **Progress tracker** (section 9) after each phase.

## 1. Overview

**CarbonTrack** is a backend platform for **MRV (Measurement, Reporting, Verification)** of carbon-removal projects:
afforestation, regenerative agriculture and (later) biochar.

It lets an organisation:
1. Register farmers and their land parcels.
2. Enrol parcels into carbon projects with a baseline.
3. Record activities (planting, cover cropping, etc.).
4. Collect monitoring observations (soil organic carbon, tree counts) over time.
5. Validate data quality automatically.
6. Estimate CO₂e removal with a transparent, versioned methodology.
7. Produce project-level analytics and reports.

> **Disclaimer:** This is a simplified educational prototype inspired by the carbon-removal domain.
> It is NOT a validated registry methodology and is not an existing Varaha system.

## 2. Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| API | FastAPI + Pydantic v2 |
| Database | PostgreSQL 16 (PostGIS added later) |
| ORM / migrations | SQLAlchemy 2.0 + Alembic |
| Auth | JWT (access tokens), bcrypt/argon2 password hashing, roles |
| Testing | pytest, httpx, pytest-cov |
| Lint / format | ruff |
| Containers | Docker + Docker Compose |
| CI | GitHub Actions |
| Later (optional) | Redis + Celery/ARQ, PostGIS, Streamlit/React dashboard |

## 3. Folder structure

```
carbontrack/
├── app/
│   ├── main.py
│   ├── core/            # config, security, logging, exceptions
│   ├── db/              # session, base, seed
│   ├── models/          # SQLAlchemy models
│   ├── schemas/         # Pydantic schemas
│   ├── api/
│   │   ├── deps.py      # shared dependencies (db session, current user, role check)
│   │   └── routes/      # one file per resource
│   ├── services/        # business logic (validation, carbon engine, analytics)
│   └── tests/
├── alembic/
├── docs/
│   ├── methodology.md
│   └── architecture.md
├── scripts/             # seed data, utilities
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── pyproject.toml
├── CLAUDE.md
├── PROJECT_SPEC.md
└── README.md
```

## 4. Domain glossary

- **MRV:** Measurement, Reporting, Verification. The process of proving carbon removal happened.
- **Baseline:** Measurement before the project activity. Removal = project state minus baseline.
- **Additionality:** The activity would not have happened without the carbon program.
- **Permanence / buffer:** A percentage of credits withheld as insurance against reversal (e.g. trees dying).
- **Uncertainty:** A discount applied because estimates are not exact.
- **CO₂e:** Carbon dioxide equivalent. Carbon (C) to CO₂ uses a factor of 44/12.
- **SOC:** Soil organic carbon, in percent of soil mass.
- **Net credits:** CO₂e after uncertainty and buffer deductions.

## 5. Data model

| Table | Key columns |
|---|---|
| `users` | id, email, hashed_password, role (`admin`, `field_officer`, `verifier`), is_active |
| `farmers` | id, name, phone, village, district, state, consent_given, is_deleted, created_at |
| `projects` | id, name, type (`afforestation`, `regen_ag`, `biochar`), status (`draft`, `active`, `closed`), methodology_id, start_date |
| `land_parcels` | id, farmer_id, area_acres, geometry (later), soil_type, crop |
| `enrollments` | id, project_id, parcel_id, farmer_id, baseline_date, status, additionality_note |
| `activities` | id, enrollment_id, type, activity_date, details (JSON) |
| `observations` | id, enrollment_id, type (`soil`, `tree_count`, `biomass`), values (JSON), observed_at, observer_id, is_baseline, superseded_by |
| `methodologies` | id, name, version, parameters (JSON), is_active |
| `carbon_estimates` | id, enrollment_id, methodology_id, methodology_version, inputs_snapshot (JSON), co2e_tonnes, uncertainty_pct, buffer_pct, net_credits, status, computed_at |
| `validation_issues` | id, observation_id, rule, severity (`info`, `warning`, `error`), message |
| `audit_logs` | id, user_id, action, entity, entity_id, before (JSON), after (JSON), created_at |

## 6. Business rules

1. Observations are **append-only**. Corrections create a new row and set `superseded_by` on the old one.
2. A parcel cannot be in two **active** enrollments of the same project type.
3. Estimation requires a baseline observation and at least one later observation.
4. Observations with `error`-severity validation issues are **excluded** from estimates.
5. Every estimate stores `inputs_snapshot` and `methodology_version` so it can be reproduced exactly.
6. Farmers cannot be hard-deleted (soft delete only), and consent must be recorded.
7. Future-dated observations are rejected.
8. Role permissions:
   - `admin`: everything
   - `field_officer`: create farmers, parcels, activities, observations
   - `verifier`: read everything, approve estimates

## 7. Carbon engine (starting assumptions, ALL must be documented in docs/methodology.md)

- **Afforestation:** `CO2e = trees × avg_biomass_per_tree_kg × carbon_fraction (0.47 ASSUMPTION) × 44/12 ÷ 1000` (tonnes)
- **Soil carbon:** `SOC_stock (t C/ha) = SOC% × bulk_density (g/cm³) × depth (cm)`; the change from baseline is converted to CO₂e with × 44/12 and scaled by area.
- **Net credits** = `co2e × (1 − uncertainty_pct) × (1 − buffer_pct)`
- Parameters live in the `methodologies` table (versioned), never hard-coded in calculators.

## 8. API conventions

- Base path `/api/v1`.
- Errors return `{"error": {"code": "...", "message": "...", "details": ...}}`.
- Lists return `{"items": [...], "total": n, "page": n, "page_size": n}`.
- Timestamps are UTC ISO-8601.
- Use proper status codes: 201 create, 204 delete, 401 unauthenticated, 403 forbidden, 404 not found, 409 conflict, 422 validation.

## 9. Progress tracker (update after each phase)

- [x] Phase 0: Setup and skeleton
- [x] Phase 1: Auth and users
- [x] Phase 2: Farmers, projects, parcels
- [x] Phase 3: Enrollments and activities
- [x] Phase 4: Monitoring and observations
- [x] Phase 5: Validation pipeline
- [ ] Phase 6: Carbon engine
- [ ] Phase 7: Analytics and reporting
- [ ] Phase 8: Bulk import and background jobs
- [ ] Phase 9: Audit, security, hardening
- [ ] Phase 10: Testing, CI, deployment
- [ ] Upgrades: PostGIS, verification workflow, anomaly detection

## 10. Out of scope (for now)

Frontend, payments, blockchain/credit trading, real registry compliance, ML models.
