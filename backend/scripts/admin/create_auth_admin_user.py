import requests

from app.config import settings


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.AUTH_SERVICE_ROLE_KEY}",
        "apikey": settings.AUTH_SERVICE_ROLE_KEY,
        "Content-Type": "application/json",
    }


def _payload() -> dict:
    return {
        "email": settings.AUTH_ADMIN_EMAIL,
        "password": settings.AUTH_ADMIN_PASSWORD,
        "email_confirm": True,
        "role": "supabase_admin",
        "app_metadata": {
            "is_admin": True,
            "daily_token_limit": 500000,
        },
    }


def create_user():
    if not settings.AUTH_ADMIN_EMAIL or not settings.AUTH_ADMIN_PASSWORD:
        raise RuntimeError("AUTH_ADMIN_EMAIL and AUTH_ADMIN_PASSWORD must be configured")

    response = requests.post(
        f"{settings.AUTH_URL}/admin/users",
        headers=_headers(),
        json=_payload(),
        timeout=10,
    )

    if response.status_code == 201 or response.status_code == 200:
        print("Admin user created.")
        print(f"email: '{settings.AUTH_ADMIN_EMAIL}'")
        print(response.json())
        return

    if response.status_code in {400, 422}:
        users_response = requests.get(
            f"{settings.AUTH_URL}/admin/users?page=1&per_page=200",
            headers=_headers(),
            timeout=10,
        )
        users_response.raise_for_status()
        users = users_response.json().get("users", [])
        existing_user = next(
            (user for user in users if user.get("email") == settings.AUTH_ADMIN_EMAIL), None
        )

        if existing_user:
            update_response = requests.put(
                f"{settings.AUTH_URL}/admin/users/{existing_user['id']}",
                headers=_headers(),
                json=_payload(),
                timeout=10,
            )
            if update_response.status_code in {200, 201}:
                print("Admin user updated.")
                print(f"email: '{settings.AUTH_ADMIN_EMAIL}'")
                print(update_response.json())
                return
            print(f"Failed to update existing admin: {update_response.status_code}")
            print(update_response.text)
            raise SystemExit(1)
    else:
        print(f"Failed: {response.status_code}")
        print(response.text)
        raise SystemExit(1)


if __name__ == "__main__":
    create_user()
