"""Read-only CRM latency probe against a deployed API (GETs only).

Usage:
  VV_LOGIN_FILE=~/.config/vv-deploy/vitevue-login-passwords-2026-11-11.txt \
  python backend/scripts/crm/measure_crm_endpoints.py [--api https://api-pilot.vitevue.com] [--label before]

Signs in as jad@demo.com through Supabase password grant (key read from frontend/wrangler.jsonc),
never prints the password or token, and prints one line per request:
  label  name  status  seconds  bytes  extra
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]


def _public_auth() -> tuple[str, str]:
    text = (ROOT / "frontend" / "wrangler.jsonc").read_text()
    url = re.search(r'"PUBLIC_AUTH_BASE_URL":\s*"([^"]+)"', text).group(1)
    key = re.search(r'"PUBLIC_AUTH_PUBLISHABLE_KEY":\s*"([^"]+)"', text).group(1)
    return url, key


def _password(email: str) -> str:
    path = Path(os.path.expanduser(os.environ["VV_LOGIN_FILE"]))
    for line in path.read_text().splitlines():
        fields = line.split("\t")
        if len(fields) >= 2 and fields[0].strip() == email:
            return fields[1].strip()
    raise SystemExit(f"no login for {email}")


async def _token(client: httpx.AsyncClient, email: str) -> str:
    url, key = _public_auth()
    response = await client.post(
        f"{url.rstrip('/').removesuffix('/auth/v1')}/auth/v1/token?grant_type=password",
        headers={"apikey": key, "Content-Type": "application/json"},
        json={"email": email, "password": _password(email)},
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _extra(name: str, body: bytes) -> str:
    try:
        data = json.loads(body)
    except ValueError:
        return ""
    if isinstance(data, dict):
        keys = [k for k in ("total", "on_file", "detail") if k in data]
        parts = [f"{k}={data[k]}" for k in keys]
        items = data.get("items") or data.get("leads") or data.get("owners")
        if isinstance(items, list):
            parts.append(f"n={len(items)}")
            if items and isinstance(items[0], dict):
                lead = items[0].get("lead", items[0])
                if isinstance(lead, dict) and "lease_end" in lead:
                    ends = [
                        (it.get("lead", it) or {}).get("lease_end") for it in items if isinstance(it, dict)
                    ]
                    ends = [e for e in ends if e]
                    parts.append(f"lease_end={min(ends)}..{max(ends)}")
        if "tab_counts" in data:
            parts.append(f"tabs={data['tab_counts']}")
        return " ".join(parts)
    if isinstance(data, list):
        return f"n={len(data)}"
    return ""


async def _get(client, api, token, label, name, path):
    started = time.perf_counter()
    response = await client.get(f"{api}{path}", headers={"Authorization": f"Bearer {token}"})
    elapsed = time.perf_counter() - started
    print(
        f"{label}\t{name}\t{response.status_code}\t{elapsed:.2f}s\t{len(response.content)}\t"
        f"{_extra(name, response.content)}",
        flush=True,
    )
    return response


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="https://api-pilot.vitevue.com")
    parser.add_argument("--label", default="run")
    parser.add_argument("--email", default="jad@demo.com")
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    crm = "/api/v1/crm"
    async with httpx.AsyncClient(timeout=120) as client:
        token = await _token(client, args.email)
        g = lambda name, path: _get(client, args.api, token, args.label, name, f"{crm}{path}")  # noqa: E731
        steps = {
            "solo": [
                ("enquiries_alone", "/inbound/enquiries?limit=100"),
                ("dashboard", "/dashboard"),
                ("dashboard_again", "/dashboard"),
                ("dashboard_junk_area", "/dashboard?area=zzzz-no-such-area"),
                ("renewal_areas", "/renewal-areas"),
                ("renewals", "/renewals"),
                ("renewal_leads_default", "/renewal-leads?limit=500"),
                ("renewal_leads_upcoming", "/renewal-leads?kind=upcoming&limit=100"),
                ("renewal_leads_upcoming_p2", "/renewal-leads?kind=upcoming&limit=100&offset=100"),
                ("renewal_leads_expired", "/renewal-leads?kind=expired&limit=100"),
                ("lead_unknown", "/leads/zzzz-not-a-lead"),
                ("owner_registry_1", "/owner-registry?limit=1"),
                ("owner_registry_100", "/owner-registry?limit=100"),
            ],
        }
        selected = set(filter(None, args.only.split(",")))
        lead_id = None
        for name, path in steps["solo"]:
            if selected and name not in selected:
                continue
            response = await g(name, path)
            if name.startswith("renewal_leads_upcoming") and response.status_code == 200 and not lead_id:
                items = response.json().get("items") or []
                lead_id = items[0]["lead"]["lead_id"] if items else None
        if lead_id and (not selected or "lead_detail" in selected):
            await g("lead_detail", f"/leads/{lead_id}")
            await g("lead_report", f"/leads/{lead_id}/report")
        if not selected or "contention" in selected:
            # Cheap calls while the dashboard runs (fresh filter so it is not a cache hit).
            dashboard = asyncio.create_task(g("contention_dashboard", "/dashboard?expired_days=400"))
            await asyncio.sleep(0.5)
            await g("contention_enquiries", "/inbound/enquiries?limit=100")
            await g("contention_workspaces", "/workspaces")
            await dashboard
        if not selected or "owners_parallel" in selected:
            await asyncio.gather(
                g("owners_par_all", "/owner-registry?limit=100&scope=all"),
                g("owners_par_registry", "/owner-registry?limit=100&scope=registry"),
                g("owners_par_prior", "/owner-registry?limit=100&scope=prior_owners"),
            )


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
