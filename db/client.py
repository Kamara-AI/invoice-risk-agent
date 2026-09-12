"""Supabase client singleton.

Instantiated once at module import time and reused across all DB calls.
Using a singleton avoids opening a new connection pool on every request,
which is especially important under concurrent FastAPI load.

Usage:
    from db.client import supabase
    result = supabase.table("vendor_ledger").select("*").eq("email", email).execute()
"""

from __future__ import annotations

from supabase import Client, create_client

from config import settings

# Module-level singleton. Supabase Python client is thread-safe.
supabase: Client = create_client(
    supabase_url=settings.supabase_url,
    supabase_key=settings.supabase_key,
)
