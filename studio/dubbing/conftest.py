"""Pytest configuration. Set required Clerk env vars before app imports."""
import os

os.environ.setdefault("CLERK_ISSUER_URL", "https://clerk.doblaj.com")
os.environ.setdefault("CLERK_AUDIENCE", "dubbing-api")
