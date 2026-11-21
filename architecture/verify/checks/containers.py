"""docker-compose.yml runs the containers the model lists, exposed as it says."""

from architecture.verify.core import check


@check("containers.match")
def containers_match(repo):
    """Every container is in both the model and docker-compose.yml."""
    modelled, composed = set(repo.model.services), set(repo.compose)
    for name in sorted(composed - modelled):
        yield f"{name}: in docker-compose.yml but not in the model"
    for name in sorted(modelled - composed):
        yield f"{name}: in the model but not in docker-compose.yml"


@check("containers.published-ports")
def published_ports(repo):
    """Containers publish exactly the host ports the model lists."""
    for name, service in sorted(repo.model.services.items()):
        if name not in repo.compose:
            continue  # containers.match reports it
        want = sorted(service.published)
        got = sorted(str(port) for port in repo.compose[name].get("ports", []))
        if got != want:
            yield f"{name}: publishes {got or 'no ports'}, the model says {want or 'none'}"
