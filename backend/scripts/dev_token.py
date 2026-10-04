"""Mint a local access token for the API (DEVELOPMENT TOOL ONLY; never run against production).

The token is HS256-signed with SUPABASE_JWT_SECRET, the backend's legacy-secret verification mode,
so the backend must run with SUPABASE_JWT_SECRET set and SUPABASE_JWKS_URL unset. It lets you call
the API with curl without signing in through Supabase:

    $env:SUPABASE_JWT_SECRET = '<at least 32 characters>'
    uv run python scripts/dev_token.py [--user-id <uuid>] [--email me@example.com] [--hours 12]
    curl -H "Authorization: Bearer <token>" http://localhost:8000/me

When SUPABASE_URL is set the token carries the matching issuer (<SUPABASE_URL>/auth/v1), as the
backend requires in that case. Anyone holding the secret can mint tokens for any user id: keep it
out of git and never reuse a production secret here.
"""

import argparse
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import jwt

from app.config import get_settings
from app.security.auth import AUDIENCE, MIN_SECRET_LENGTH


def mint_token(
    secret: str,
    *,
    user_id: str,
    email: str,
    supabase_url: str | None = None,
    hours: float = 12.0,
) -> str:
    now = int(time.time())
    claims: dict[str, object] = {
        "sub": user_id,
        "aud": AUDIENCE,
        "role": "authenticated",
        "email": email,
        "iat": now,
        "exp": now + int(hours * 3600),
    }
    base = (supabase_url or "").strip().rstrip("/")
    if base:
        claims["iss"] = f"{base}/auth/v1"
    return jwt.encode(claims, secret, algorithm="HS256")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--user-id", default=None, help="the token's subject (default: a new UUID)")
    parser.add_argument("--email", default="dev@example.com")
    parser.add_argument("--hours", type=float, default=12.0, help="lifetime in hours (default 12)")
    args = parser.parse_args()

    settings = get_settings()
    secret = (settings.SUPABASE_JWT_SECRET or "").strip()
    if not secret:
        print("SUPABASE_JWT_SECRET is not set; refusing to mint a token.", file=sys.stderr)
        return 1
    if len(secret) < MIN_SECRET_LENGTH:
        print(f"SUPABASE_JWT_SECRET must be at least {MIN_SECRET_LENGTH} characters.", file=sys.stderr)
        return 1
    if (settings.SUPABASE_JWKS_URL or "").strip():
        print(
            "warning: SUPABASE_JWKS_URL is set, so the backend verifies with the JWKS keys and will "
            "reject this token. Unset it for local development.",
            file=sys.stderr,
        )
    user_id = args.user_id or str(uuid.uuid4())
    print("DEVELOPMENT TOKEN - for local use only", file=sys.stderr)
    token = mint_token(
        secret, user_id=user_id, email=args.email, supabase_url=settings.SUPABASE_URL, hours=args.hours
    )
    print(f"user id: {user_id}")
    print(f"token:   {token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
