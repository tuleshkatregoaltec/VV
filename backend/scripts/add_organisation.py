import sys
from sqlmodel import Session, select

from backend.app.db.session import engine
from backend.app.db.models import Organisation


def add_organization(name: str, domain: str, max_users: int = 5):
    """Add a new organization manually"""
    with Session(engine) as session:
        statement = select(Organisation).where(Organisation.email_domain == domain)
        existing = session.exec(statement).first()

        if existing:
            print(f"❌ Organization with domain '{domain}' already exists!")
            return

        org = Organisation(
            name=name, email_domain=domain, max_users=max_users, is_active=True
        )
        session.add(org)
        session.commit()
        session.refresh(org)

        print("✅ Organization created successfully!")
        print(f"   Name: {org.name}")
        print(f"   Domain: {org.email_domain}")
        print(f"   Max Users: {org.max_users}")
        print(f"   ID: {org.id}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python add_organization.py <name> <domain> [max_users]")
        print("Example: python add_organization.py 'Acme Corp' 'acme.com' 10")
        sys.exit(1)

    name = sys.argv[1]
    domain = sys.argv[2]
    max_users = int(sys.argv[3]) if len(sys.argv) > 3 else 5

    add_organization(name, domain, max_users)
