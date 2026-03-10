import requests

from app.config import settings

AUTH_URL = "https://auth.vitevue.com"


def create_user():
    if not settings.SYSTEM_ADMIN_EMAIL or not settings.AUTH_ADMIN_PASSWORD:
        raise RuntimeError("SYSTEM_ADMIN_EMAIL and AUTH_ADMIN_PASSWORD must be configured")

    service_role_key = settings.AUTH_SERVICE_ROLE_KEY
    headers = {
        "Authorization": f"Bearer {service_role_key}",
        "apikey": service_role_key,
        "Content-Type": "application/json",
    }

    data = {
        "email": settings.SYSTEM_ADMIN_EMAIL,
        "password": settings.AUTH_ADMIN_PASSWORD,
        "email_confirm": True,  # Automatically confirms the email
        "user_metadata": {"role": "admin", "full_name": "Admin Vitevue"},
    }

    response = requests.post(f"{AUTH_URL}/admin/users", headers=headers, json=data)

    if response.status_code == 201 or response.status_code == 200:
        print("Admin user created.")
        print(response.json())
    else:
        print(f"Failed: {response.status_code}")
        print(response.text)


if __name__ == "__main__":
    create_user()
