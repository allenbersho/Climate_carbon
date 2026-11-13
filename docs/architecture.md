# CarbonTrack System Architecture

## Layering
The application enforces strict architectural layering:
```
HTTP Request
     │
     ▼
[ Routers ] (app/api/routes)
  - Thin controllers
  - Request parameter parsing & HTTP status codes
     │
     ▼
[ Dependencies & Auth ] (app/api/deps.py)
  - DB session lifecycle (get_db)
  - Authentication & Role verification
     │
     ▼
[ Service Layer ] (app/services)
  - Pure business logic (MRV rules, Carbon Engine, Validation)
  - Orchestrates domain models
     │
     ▼
[ Data Access / Models ] (app/models, app/db)
  - SQLAlchemy 2.0 ORM models
  - Unit of work & database queries
     │
     ▼
[ Database ] (PostgreSQL / SQLite fallback)
```

## Schemas vs Models Separation
- **Schemas (`app/schemas`)**: Pydantic models validating untrusted input and formatting API responses.
- **Models (`app/models`)**: SQLAlchemy classes mapped directly to database tables. Database models are never directly returned from route handlers.
