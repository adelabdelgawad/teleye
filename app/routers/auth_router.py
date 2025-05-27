from typing import List

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm

from core.config import settings
from core.models import TokenResponse, User, UserCreate, UserRead
from services.auth_service import (
    create_access_token,
    hash_password,
    verify_password,
)
from services.dependancies import get_elasticsearch_client, require_role

router = APIRouter()


@router.post("/token", response_model=TokenResponse)
async def login_for_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    es: AsyncElasticsearch = Depends(get_elasticsearch_client),
) -> TokenResponse:
    """
    Obtain a new access token for a valid user.

    This endpoint checks the provided username and password against the
    Elasticsearch “users” index. If the credentials are correct, it
    returns a JWT access token.

    Args:
        form_data: OAuth2PasswordRequestForm containing `username` and `password`.
        es: AsyncElasticsearch client dependency.

    Example:
        POST /token
        Content-Type: application/x-www-form-urlencoded

        grant_type=&username=john&password=secret
    """
    resp = await es.options(ignore_status=[404]).get(
        index="users", id=form_data.username
    )
    if not resp.get("found") or not verify_password(
        form_data.password, resp["_source"]["hashed_password"]
    ):
        raise HTTPException(
            status_code=401, detail="Incorrect username or password"
        )
    token = create_access_token({"sub": form_data.username})
    return {"access_token": token, "token_type": "bearer"}


@router.post(
    "/users",
    response_model=UserRead,
    dependencies=[Depends(require_role("admin"))],
)
async def create_user(
    user: UserCreate,
    es: AsyncElasticsearch = Depends(get_elasticsearch_client),
) -> UserRead:
    """
    Create a new user with a hashed password and assigned role.

    Only users with the “admin” role may call this endpoint. The new
    user is stored in Elasticsearch under the “users” index.

    Args:
        user: UserCreate schema containing `username`, `password`, and `role`.
        es: AsyncElasticsearch client dependency.

    Example:
        POST /users
        Content-Type: application/json

        {
          "username": "alice",
          "password": "SuperSecret!",
          "role": "user"
        }
    """
    hashed = hash_password(user.password)
    await es.index(
        index="users",
        id=user.username,
        document={
            "username": user.username,
            "hashed_password": hashed,
            "role": user.role,
        },
    )
    return {"username": user.username, "role": user.role}


@router.delete(
    "/users/{username}", dependencies=[Depends(require_role("admin"))]
)
async def delete_user(
    username: str, es: AsyncElasticsearch = Depends(get_elasticsearch_client)
) -> dict:
    """
    Delete an existing user from the system.

    The default admin user (as configured in settings) may not be deleted.
    Only admins may call this endpoint.

    Args:
        username: The username of the user to delete.
        es: AsyncElasticsearch client dependency.
    """
    if username == settings.security.admin_username:
        raise HTTPException(
            status_code=400, detail="Default admin cannot be deleted"
        )
    await es.delete(index="users", id=username, ignore=[404])
    return {"message": f"User {username} deleted"}


@router.put("/users/{username}", dependencies=[Depends(require_role("admin"))])
async def update_user(
    username: str,
    user: UserCreate,
    es: AsyncElasticsearch = Depends(get_elasticsearch_client),
) -> List[User]:
    """
    Update an existing user’s password and role.

    This endpoint re-hashes the provided password and updates the
    user’s role. Only admins are authorized.

    Args:
        username: The username of the user to update.
        user: UserCreate schema with the new `password` and `role`.
        es: AsyncElasticsearch client dependency.

    Example:
        PUT /users/alice
        Content-Type: application/json
    """
    await es.update(
        index="users",
        id=username,
        doc={
            "hashed_password": hash_password(user.password),
            "role": user.role,
        },
    )
    return {"username": username, "role": user.role}
