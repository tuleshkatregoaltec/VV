import sys
from pathlib import Path

# Add parent directory to path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import SQLModel
from backend.app.db.session import engine
from backend.app.db.models import Organisation, User  # Import to register tables


def create_auth_tables():
    """Create Organization and User tables"""
    print("Creating authentication tables...")

    # This will only create tables that don't exist yet
    SQLModel.metadata.create_all(engine)

    print("✓ Authentication tables created successfully!")
    print("\nTables created:")
    print("  - organisations")
    print("  - users")


if __name__ == "__main__":
    create_auth_tables()
