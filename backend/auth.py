
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash

# Password hashing using Argon2
password_hash = PasswordHash.recommended()

# JWT authentication
SECRET_KEY = os.environ.get("JANUS_SECRET_KEY")

if not SECRET_KEY:
    raise RuntimeError(
        "JANUS_SECRET_KEY must be set before starting the server"
    )

ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = 60

security = HTTPBearer()


def hash_password(password: str) -> str:
    """Convert a plaintext password into a secure hash."""
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """Check whether a password matches its stored hash."""
    return password_hash.verify(password, hashed_password)


def create_access_token(username: str) -> str:
    """Generate a signed login token."""
    expires = datetime.now(timezone.utc) + timedelta(
        minutes=TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "sub": username,
        "exp": expires,
    }

    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str:
    """Validate a token and return its username."""
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
        )

        username = payload.get("sub")

        if not isinstance(username, str) or not username:
            raise ValueError("Invalid username")

        return username

    except (InvalidTokenError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
        )


def get_current_username(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """Require a valid Bearer token for an HTTP endpoint."""
    return decode_access_token(credentials.credentials)
