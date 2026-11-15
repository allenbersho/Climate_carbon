"""CLI script to seed default methodologies into the database."""

import sys
from pathlib import Path

# Ensure repository root is on sys.path for direct CLI execution
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.session import SessionLocal
from app.services.methodology_service import seed_default_methodologies


def main() -> None:
    """Seed Afforestation v1 and Soil Carbon v1 methodologies."""
    db = SessionLocal()
    try:
        methodologies = seed_default_methodologies(db)
        print(f"Successfully seeded {len(methodologies)} methodologies:")
        for m in methodologies:
            print(f" - [{m.id}] {m.name} {m.version} (active={m.is_active})")
    except Exception as exc:
        print(f"Error seeding methodologies: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
