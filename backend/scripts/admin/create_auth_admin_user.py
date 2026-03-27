import requests

from app.config import settings


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.AUTH_SERVICE_ROLE_KEY}",
        "apikey": settings.AUTH_SERVICE_ROLE_KEY,
        "Content-Type": "application/json",
    }


def _list_auth_users() -> list[dict]:
    users: list[dict] = []
    page = 1
    per_page = 200

    while True:
        response = requests.get(
            f"{settings.AUTH_URL}/admin/users?page={page}&per_page={per_page}",
            headers=_headers(),
            timeout=10,
        )
        response.raise_for_status()
        page_users = response.json().get("users", [])
        users.extend(page_users)
        if len(page_users) < per_page:
            break
        page += 1

    return users


def _payload() -> dict:
    return {
        "email": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
        "email_confirm": True,
        "role": "supabase_admin",
        "user_metadata": {
            "first_name": "Admin",
            "last_name": "User",
        },
        "app_metadata": {
            "is_admin": True,
            "daily_token_limit": 500000,
        },
    }


def create_user():
    if not settings.bootstrap_superuser_enabled:
        raise RuntimeError("FIRST_SUPERUSER and FIRST_SUPERUSER_PASSWORD must be configured")

    response = requests.post(
        f"{settings.AUTH_URL}/admin/users",
        headers=_headers(),
        json=_payload(),
        timeout=10,
    )

    if response.status_code == 201 or response.status_code == 200:
        print("Admin user created.")
        print(f"email: '{settings.FIRST_SUPERUSER}'")
        print(response.json())
        return

    if response.status_code in {400, 422}:
        users = _list_auth_users()
        existing_user = next(
            (user for user in users if user.get("email") == settings.FIRST_SUPERUSER), None
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
                print(f"email: '{settings.FIRST_SUPERUSER}'")
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
