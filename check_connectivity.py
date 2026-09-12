"""Connectivity check for OFAC, Stripe, and Supabase.

Run this before build day to confirm all three integrations are reachable
with the keys in .env. Does NOT import config.py — avoids validation failure
on incomplete keys (OpenAI, Gmail, Slack not yet set).

Usage:
    python check_connectivity.py
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

PASS = "  [PASS]"
FAIL = "  [FAIL]"


# ==============================================================================
# 1. OFAC
# ==============================================================================
def check_ofac() -> bool:
    """POST a known-clean vendor name to OFAC and expect a valid response."""
    import httpx

    api_key = os.getenv("OFAC_API_KEY")
    base_url = os.getenv("OFAC_API_BASE_URL", "https://api.ofac-api.com/v4")

    print("\n[1] OFAC Sanctions API")
    print(f"    URL : {base_url}")
    print(f"    Key : {api_key[:8]}...{api_key[-4:]}" if api_key else "    Key : NOT SET")

    if not api_key:
        print(f"{FAIL} OFAC_API_KEY not set in .env")
        return False

    try:
        response = httpx.post(
            f"{base_url}/search",
            json={
                "apiKey": api_key,
                "minScore": 85,
                "sources": ["SDN"],
                "cases": [{"name": "Apple Inc"}],
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        print(f"{PASS} HTTP {response.status_code} — response received")
        print(f"    Matches for 'Apple Inc': {data}")
        return True
    except httpx.HTTPStatusError as e:
        print(f"{FAIL} HTTP {e.response.status_code}: {e.response.text[:200]}")
        return False
    except Exception as e:
        print(f"{FAIL} {type(e).__name__}: {e}")
        return False


# ==============================================================================
# 2. Stripe
# ==============================================================================
def check_stripe() -> bool:
    """List Stripe customers (limit 1) to verify key is valid."""
    import stripe as stripe_sdk

    api_key = os.getenv("STRIPE_API_KEY")

    print("\n[2] Stripe API")
    print(f"    Key : {api_key[:12]}...{api_key[-4:]}" if api_key else "    Key : NOT SET")

    if not api_key:
        print(f"{FAIL} STRIPE_API_KEY not set in .env")
        return False

    try:
        stripe_sdk.api_key = api_key
        customers = stripe_sdk.Customer.list(limit=1)
        print(f"{PASS} Connected — Customer.list returned {len(customers.data)} record(s)")
        return True
    except stripe_sdk.AuthenticationError as e:
        print(f"{FAIL} Authentication failed: {e}")
        return False
    except Exception as e:
        print(f"{FAIL} {type(e).__name__}: {e}")
        return False


# ==============================================================================
# 3. Supabase
# ==============================================================================
def check_supabase() -> bool:
    """Query vendor_ledger (limit 1) to verify DB connection and table exists."""
    from supabase import create_client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    print("\n[3] Supabase")
    print(f"    URL : {url}")
    print(f"    Key : {key[:12]}...{key[-4:]}" if key else "    Key : NOT SET")

    if not url or not key:
        print(f"{FAIL} SUPABASE_URL or SUPABASE_KEY not set in .env")
        return False

    try:
        client = create_client(url, key)
        result = client.table("vendor_ledger").select("vendor_id").limit(1).execute()
        print(f"{PASS} Connected — vendor_ledger query OK ({len(result.data)} rows)")
        return True
    except Exception as e:
        print(f"{FAIL} {type(e).__name__}: {e}")
        return False


# ==============================================================================
# Main
# ==============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Invoice Risk Agent — Connectivity Check")
    print("=" * 60)

    results = {
        "OFAC": check_ofac(),
        "Stripe": check_stripe(),
        "Supabase": check_supabase(),
    }

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {name:<12} {status}")

    all_passed = all(results.values())
    print("=" * 60)
    sys.exit(0 if all_passed else 1)
