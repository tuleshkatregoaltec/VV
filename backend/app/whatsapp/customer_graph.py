"""Minimal Meta Graph client for Embedded Signup. Never logs tokens or response bodies."""

import httpx

GRAPH_URL = "https://graph.facebook.com"


class GraphError(Exception):
    """A failed Graph call, carrying only allowlisted numeric codes."""

    def __init__(self, response=None):
        self.error_code = "meta_unreachable"
        if response is not None:
            self.error_code = f"meta_http_{response.status_code}"
            try:
                code = response.json().get("error", {}).get("code")
                if type(code) is int:
                    self.error_code = f"meta_{code}"
            except (ValueError, TypeError, AttributeError):
                pass
        super().__init__(self.error_code)


async def _call(method, path, config, *, token=None, params=None, json=None):
    url = f"{GRAPH_URL}/{config.WHATSAPP_GRAPH_API_VERSION}/{path}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.request(method, url, headers=headers, params=params, json=json)
    except httpx.HTTPError:
        raise GraphError() from None
    if response.status_code != 200:
        raise GraphError(response)
    try:
        data = response.json()
    except ValueError:
        raise GraphError(response) from None
    if not isinstance(data, dict):
        raise GraphError(response)
    return data


async def exchange_code(code, config):
    """Exchange the ~30 second Embedded Signup code for a business integration token."""
    data = await _call(
        "GET",
        "oauth/access_token",
        config,
        params={
            "client_id": config.WHATSAPP_APP_ID,
            "client_secret": config.WHATSAPP_APP_SECRET,
            "code": code,
        },
    )
    token = data.get("access_token")
    if not isinstance(token, str) or not 1 <= len(token) <= 4096:
        raise GraphError()
    return token


async def phone_numbers(waba_id, token, config):
    data = await _call(
        "GET",
        f"{waba_id}/phone_numbers",
        config,
        token=token,
        params={"fields": "id,display_phone_number,verified_name,quality_rating"},
    )
    numbers = data.get("data")
    return [item for item in numbers if isinstance(item, dict)] if isinstance(numbers, list) else []


async def subscribe_app(waba_id, token, config):
    await _call("POST", f"{waba_id}/subscribed_apps", config, token=token)


async def unsubscribe_app(waba_id, token, config):
    await _call("DELETE", f"{waba_id}/subscribed_apps", config, token=token)


async def register_number(phone_number_id, token, pin, config):
    """Cloud API-only numbers. Coexistence numbers are already registered."""
    await _call(
        "POST",
        f"{phone_number_id}/register",
        config,
        token=token,
        json={"messaging_product": "whatsapp", "pin": pin},
    )


async def request_contacts_sync(phone_number_id, token, config):
    """One-time coexistence contacts sync; must run within 24h of onboarding.

    Message history (`sync_type: history`) is deliberately never requested.
    """
    data = await _call(
        "POST",
        f"{phone_number_id}/smb_app_data",
        config,
        token=token,
        json={"messaging_product": "whatsapp", "sync_type": "smb_app_state_sync"},
    )
    request_id = data.get("request_id")
    return request_id if isinstance(request_id, str) else None


async def phone_health(phone_number_id, token, config):
    data = await _call(
        "GET", phone_number_id, config, token=token, params={"fields": "health_status"}
    )
    return data.get("health_status")
