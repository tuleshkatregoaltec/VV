"""Fire the Owners page's parallel CRM reads N times at once and tally status codes.

    VV_LOGIN_FILE=~/.config/vv-deploy/vitevue-login-passwords-2026-11-11.txt \
      python3 e2e/tools/crm-owners-burst.py maan@demo.com [pages=3]

The login file is tab-separated "email<TAB>password"; credentials are never printed.
Exits 1 if any request returned 429.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

API = os.environ.get("VV_API", "https://api-pilot.vitevue.com")
AUTH = os.environ.get("VV_AUTH", "https://fxszmyazeonmxxeixzoh.supabase.co/auth/v1")
WRANGLER = os.path.join(
    os.path.dirname(__file__), "..", "..", "frontend", "wrangler.jsonc"
)
# Cloudflare's browser integrity check rejects the default Python-urllib agent (1010).
AGENT = "Mozilla/5.0 (X11; Linux x86_64) vv-crm-owners-burst"
# The reads the Owners page issues together on load (from the live access log).
OWNERS_PAGE = [
    "/api/v1/crm/owner-registry?scope=current_owners&limit=10&offset=0",
    "/api/v1/crm/contact-imports",
    "/api/v1/crm/owner-workspaces",
    "/api/v1/crm/inbound/imports",
    "/api/v1/crm/renewal-leads?limit=500",
]


def publishable_key() -> str:
    for line in open(WRANGLER):
        if "PUBLIC_AUTH_PUBLISHABLE_KEY" in line:
            return line.split(":", 1)[1].strip().strip(",").strip('"')
    raise SystemExit("publishable key not found in wrangler.jsonc")


def token(email: str) -> str:
    with open(os.path.expanduser(os.environ["VV_LOGIN_FILE"])) as handle:
        rows = dict(line.rstrip("\n").split("\t", 1) for line in handle if "\t" in line)
    request = urllib.request.Request(
        f"{AUTH}/token?grant_type=password",
        data=json.dumps({"email": email, "password": rows[email]}).encode(),
        headers={
            "apikey": publishable_key(),
            "Content-Type": "application/json",
            "User-Agent": AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)["access_token"]


def get(path: str, bearer: str) -> tuple[str, int, float]:
    started = time.monotonic()
    request = urllib.request.Request(
        API + path,
        headers={
            "Authorization": f"Bearer {bearer}",
            "Origin": "https://vitevue.com",
            "User-Agent": AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            response.read()
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    return path, status, time.monotonic() - started


def main() -> None:
    email = sys.argv[1]
    pages = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    bearer = token(email)
    paths = OWNERS_PAGE * pages
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(paths)) as pool:
        results = list(pool.map(lambda path: get(path, bearer), paths))
    tally = Counter(status for _, status, _ in results)
    print(f"requests={len(results)} wall={time.monotonic() - started:.1f}s")
    print("status tally:", dict(sorted(tally.items())))
    for path, status, seconds in results:
        if status != 200:
            print(f"  {status} {path} {seconds:.1f}s")
    print(f"slowest={max(seconds for *_, seconds in results):.1f}s")
    sys.exit(1 if tally.get(429) else 0)


if __name__ == "__main__":
    main()
