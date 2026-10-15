"""The ingestion worker's API, defined in openapi.yaml. Only the Core API calls it."""

import secrets

from fastapi import Depends, FastAPI, Header, HTTPException

from ingestion_worker import config, dependency_cache
from ingestion_worker.models import Dependency

app = FastAPI(title="Ingestion Worker")


def _check_token(authorization: str = Header("")) -> None:
    if not secrets.compare_digest(authorization, f"Bearer {config.INBOUND_TOKEN}"):
        raise HTTPException(status_code=401)


@app.put("/dependencies/{dependency_id}", status_code=204, dependencies=[Depends(_check_token)])
def put_dependency(dependency_id: str, dependency: Dependency) -> None:
    """A dependency was added or changed."""
    dependency_cache.put(dependency_id, dependency)


@app.delete("/dependencies/{dependency_id}", status_code=204, dependencies=[Depends(_check_token)])
def delete_dependency(dependency_id: str) -> None:
    """A dependency was removed."""
    dependency_cache.delete(dependency_id)
