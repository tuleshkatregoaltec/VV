import jwt
import time
import os
import requests


from pathlib import Path
from dotenv import load_dotenv

from app.config import settings

# Load .env file from backend directory
load_dotenv(Path(__file__).parent.parent / ".env")


def make_jwt():
    payload = {
        "role": "supabase_admin",
        "iss": "supabase",
        "iat": int(time.time()),
        "exp": int(time.time()) + 600,  # 10 minutes
    }
    return jwt.encode(payload, os.environ.get("JWT_SECRET"), algorithm="HS256")


def create_user():
    token = make_jwt()

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    data = {
        "email": os.environ.get("AUTH_ADMIN_EMAIL"),
        "password": os.environ.get("AUTH_ADMIN_PASSWORD"),
        "email_confirm": True,  # Automatically confirms the email,
        "role": "supabase_admin",
    }

    response = requests.post(
        f"{settings.AUTH_URL}/admin/users", headers=headers, json=data
    )

    if response.status_code == 201 or response.status_code == 200:
        print("Admin user created.")
        print(f"email: '{os.environ.get('AUTH_ADMIN_EMAIL')}'")
        print(response.json())
    else:
        print(f"Failed: {response.status_code}")
        print(response.text)


if __name__ == "__main__":
    create_user()
