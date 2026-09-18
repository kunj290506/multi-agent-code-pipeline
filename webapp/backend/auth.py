"""
Authentication module — users table, password helpers, JWT helpers, auth router.

Provides:
  - SQLite ``users`` table initialisation (``init_db``)
  - ``hash_password`` / ``verify_password`` via passlib bcrypt
  - ``create_jwt`` / ``decode_jwt`` using HS256 (secret from env JWT_SECRET)
  - FastAPI ``APIRouter`` with /auth/signup, /auth/login, /auth/me, /auth/logout
  - ``get_current_user`` dependency for protecting non-auth routes
"""

import logging
import os
import db
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import APIRouter, Cookie, HTTPException
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("webapp-backend")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Database path sits next to this file.
DB_PATH: str = os.path.join(os.path.dirname(__file__), "users.db")

# JWT settings — secret MUST come from env; the fallback is dev-only.
JWT_SECRET: str = os.environ.get("JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRY_SECONDS: int = 86400  # 24 h

# Cookie name used for session management.
SESSION_COOKIE: str = "session"

# Optional application hook invoked after a successful login.
_login_hook: Callable[[], None] | None = None


def set_login_hook(hook: Callable[[], None]) -> None:
    """Register an application callback to run after successful login."""
    global _login_hook
    _login_hook = hook

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of the given plain-text password."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches the stored *hashed* password."""
    return _pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def create_jwt(user_id: int, username: str) -> str:
    """Return a signed HS256 JWT with a 24-hour expiry.

    The secret is read from the ``JWT_SECRET`` environment variable.
    A hardcoded fallback is provided for local development only — it must be
    overridden via env in any deployed environment.
    """
    expire = datetime.now(timezone.utc) + timedelta(seconds=JWT_EXPIRY_SECONDS)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "username": username,
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> dict | None:
    """Decode and verify a JWT.  Returns the payload dict or None if invalid/expired."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None


# ---------------------------------------------------------------------------
# Database initialisation
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Create the ``users`` table if it does not already exist."""
    db.execute_write(DB_PATH,
        """
        CREATE TABLE IF NOT EXISTS users (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            username         TEXT    UNIQUE NOT NULL,
            email            TEXT    UNIQUE NOT NULL,
            hashed_password  TEXT    NOT NULL,
            created_at       TEXT    NOT NULL
        )
        """
    )
    logger.info("Auth DB initialised at %s", DB_PATH)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class SignupRequest(BaseModel):
    username: str = Field(..., min_length=1)
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=1)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Helper — build a JSON response that sets the session cookie
# ---------------------------------------------------------------------------


def _session_response(user_id: int, username: str) -> JSONResponse:
    """Return a JSONResponse carrying the session cookie and user info."""
    token = create_jwt(user_id, username)
    resp = JSONResponse(content={"username": username, "id": user_id})
    resp.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=JWT_EXPIRY_SECONDS,
        path="/",
    )
    return resp


# ---------------------------------------------------------------------------
# Auth router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup")
def signup(req: SignupRequest) -> JSONResponse:
    """Create a new user account and return a session cookie.

    Returns 409 if the username or email is already taken.
    """
    created_at = datetime.now(timezone.utc).isoformat()
    hashed = hash_password(req.password)
    try:
        user_id = db.execute_write(DB_PATH,
            "INSERT INTO users (username, email, hashed_password, created_at) VALUES (?, ?, ?, ?)",
            (req.username, req.email, hashed, created_at)
        )
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise HTTPException(status_code=409, detail="Username or email already exists.")
        raise
    logger.info("New user registered: %s (id=%d)", req.username, user_id)
    return _session_response(user_id, req.username)


@router.post("/login")
def login(req: LoginRequest) -> JSONResponse:
    """Verify credentials and return a session cookie.

    Returns 401 on bad credentials.
    """
    rows = db.execute_query(DB_PATH,
        "SELECT id, hashed_password FROM users WHERE username = ?",
        (req.username,)
    )
    if not rows or not verify_password(req.password, rows[0]["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    if _login_hook is not None:
        _login_hook()
    user_id: int = rows[0]["id"]
    logger.info("User logged in: %s (id=%d)", req.username, user_id)
    return _session_response(user_id, req.username)


@router.get("/me")
def me(session: str | None = Cookie(default=None)) -> dict:
    """Return the current authenticated user's info, or 401 if not authenticated."""
    if session is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    payload = decode_jwt(session)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session.")
    return {"username": payload["username"], "id": int(payload["sub"])}


@router.post("/logout")
def logout() -> JSONResponse:
    """Clear the session cookie."""
    resp = JSONResponse(content={"status": "logged_out"})
    resp.delete_cookie(key=SESSION_COOKIE, path="/")
    return resp


# ---------------------------------------------------------------------------
# Dependency — get_current_user
# ---------------------------------------------------------------------------


def get_current_user(session: str | None = Cookie(default=None)) -> dict:
    """FastAPI dependency that validates the session cookie and returns the user.

    Raises HTTPException(401) if the cookie is absent or the JWT is invalid/expired.
    """
    if session is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    payload = decode_jwt(session)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session.")
    return {"id": int(payload["sub"]), "username": payload["username"]}
