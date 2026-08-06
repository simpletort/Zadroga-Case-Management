"""
shared/middlewares/cors.py — CORS origin list for all SimpleTort services, sourced from
GCP Secret Manager (secret: "cors-allowed-origins").
"""

from __future__ import annotations

import json
from functools import lru_cache


@lru_cache(maxsize=None)
def _fetch_origins_config(gcp_project_id: str) -> dict:
    from google.cloud import secretmanager

    sm = secretmanager.SecretManagerServiceClient()
    name = f"projects/{gcp_project_id}/secrets/cors-allowed-origins/versions/latest"
    response = sm.access_secret_version(request={"name": name})
    return json.loads(response.payload.data.decode("utf-8"))


def get_cors_origins(environment: str, gcp_project_id: str) -> list[str]:
    """Return the allowed CORS origins for the given environment, fetched from Secret Manager.

    Raises if the secret cannot be fetched or parsed — services intentionally fail to start
    rather than run with a stale or missing origin list.
    """
    config = _fetch_origins_config(gcp_project_id)
    prod_origins = config["production"]
    if environment == "production":
        return list(prod_origins)
    return prod_origins + config["dev_extras"]
