"""Containers can reach exactly the containers the model connects them to.

Docker networks can't tell who opens a connection, so reachability is checked both ways round;
the direction in the model only matters for the addresses a container is configured with.
"""

import itertools
import re

from architecture.verify.core import check

URL = re.compile(r"https?://([A-Za-z0-9_.-]+)(?::(\d+))?")


def networks_of(service):
    # Compose puts a service with no networks key on "default"; list and map forms both give names
    return set(service.get("networks") or ["default"])


def env_values(service):
    env = service.get("environment") or {}
    if isinstance(env, list):
        return [item.partition("=")[2] for item in env]
    return [str(value) for value in env.values()]


@check("network.reachability")
def reachability(repo):
    """Two containers share a network exactly when the model connects them."""
    names = sorted(set(repo.model.services) & set(repo.compose))
    for a, b in itertools.combinations(names, 2):
        common = networks_of(repo.compose[a]) & networks_of(repo.compose[b])
        connected = repo.model.connects(a, b)
        if common and not connected:
            nets = ", ".join(sorted(common))
            yield f"{a} and {b} share network {nets}, but the model doesn't connect them"
        elif connected and not common:
            yield f"the model connects {a} and {b}, but they share no network"


@check("network.addresses")
def addresses(repo):
    """Container URLs in compose environments and Caddyfile routes are modelled connections."""
    services = repo.model.services
    calls = [(name, value) for name in repo.compose for value in env_values(repo.compose[name])]
    calls += [
        ("caddy", f"http://{t}") for t in re.findall(r"reverse_proxy\s+(\S+)", repo.caddyfile)
    ]
    for caller, value in calls:
        for host, port in URL.findall(value):
            if host not in services:
                continue  # localhost, public sites
            if not repo.model.calls(caller, host):
                yield f"{caller} is configured to call {host} ({value}), not in the model"
            elif int(port or 80) != services[host].port:
                yield f"{caller} calls {host} on {value}, but {host} listens on {services[host].port}"
