from core.config import settings
from elasticsearch import AsyncElasticsearch
from services.auth_service import hash_password


async def ensure_default_admin(es: AsyncElasticsearch):
    """
    Ensure that the default admin user exists in Elasticsearch.

    This function checks the Elasticsearch "users" index for a document
    whose ID matches the configured default admin username. If no such
    document is found, it will create one with the password and role
    from your settings.

    Args:
        es: An AsyncElasticsearch client instance, connected to your cluster.

    Example:
        # Called during application startup to guarantee the admin account
        # is present before serving any requests.
        await ensure_default_admin(es)
    """
    admin = settings.security.admin_username
    pwd = settings.security.admin_password
    resp = await es.get(index="users", id=admin, ignore=[404])
    if not resp.get("found"):
        await es.index(
            index="users",
            id=admin,
            document={
                "username": admin,
                "hashed_password": hash_password(pwd),
                "role": "admin",
            },
        )
