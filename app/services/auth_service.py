from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi.security import OAuth2PasswordBearer
from jose import jwt
from passlib.context import CryptContext

from core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


def hash_password(password: str) -> str:
    """
    Hash a plaintext password using bcrypt.

    Args:
        password: The plaintext password to hash.

    Example:
        >>> hash_password("MySecret123")
        "$2b$12$K9QvX...wQe"
    """
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """
    Verify that a plaintext password matches its bcrypt hash.

    Args:
        plain: The plaintext password to verify.
        hashed: The bcrypt hash to check against.

    Example:
        >>> hashed = hash_password("MySecret123")
        >>> verify_password("MySecret123", hashed)
        True
        >>> verify_password("WrongPass", hashed)
        False
    """
    return pwd_context.verify(plain, hashed)


def create_access_token(
    data: dict, expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT access token with an expiration.

    Takes a payload dict (e.g. containing `"sub": username`) and signs it
    with the application’s secret key.  Automatically adds an `"exp"` claim
    set to `now + expires_delta` or to the default expiry.

    Args:
        data: A dict of claims to include in the token (e.g. {"sub": "alice"}).
        expires_delta: Optional timedelta for token lifetime. Defaults to
                       settings.security.access_token_expire_minutes.

    Example:
        >>> token = create_access_token({"sub": "alice"})
        >>> isinstance(token, str)
        True
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta
        or timedelta(minutes=settings.security.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(
        to_encode,
        settings.security.secret_key,
        algorithm=settings.security.algorithm,
    )


async def is_admin(role: str) -> bool:
    """
    Check whether a given role string corresponds to an admin user.

    Args:
        role: The user role to check (e.g. "user" or "admin").

    Example:
        >>> await is_admin("admin")
        True
        >>> await is_admin("user")
        False
    """
    if role == "admin":
        return True
