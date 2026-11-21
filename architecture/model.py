"""The system model (architecture/model.yaml), parsed and validated.

Checks read the model through these types, never the raw YAML. To model something new, add a
section to model.yaml, a type and a parser for it here, and checks that use it.
"""

from dataclasses import dataclass

SECTIONS = {"services", "connections", "generated"}


class ModelError(Exception):
    """model.yaml is malformed, so nothing can be checked against it."""


@dataclass(frozen=True)
class Service:
    name: str
    port: int  # what it listens on inside the compose network
    published: tuple[str, ...] = ()  # compose `ports` entries, exactly as written


@dataclass(frozen=True)
class Connection:
    source: str
    target: str
    why: str


@dataclass(frozen=True)
class Generated:
    file: str
    sources: tuple[str, ...]  # what it's generated from; edit these instead
    command: str  # takes the output path as its first argument, defaulting to file


@dataclass(frozen=True)
class Model:
    services: dict[str, Service]
    connections: tuple[Connection, ...]
    generated: tuple[Generated, ...] = ()

    @classmethod
    def parse(cls, data):
        errors = [f"unknown section {key}" for key in sorted(set(data) - SECTIONS)]

        services = {}
        for name, raw in (data.get("services") or {}).items():
            if not isinstance(raw.get("port"), int):
                errors.append(f"service {name}: port must be a number")
            services[name] = Service(name, raw.get("port"), tuple(raw.get("published", ())))

        connections = []
        for raw in data.get("connections") or []:
            if missing := {"from", "to", "why"} - set(raw):
                errors.append(f"connection {raw}: missing {', '.join(sorted(missing))}")
                continue
            for end in (raw["from"], raw["to"]):
                if end not in services:
                    errors.append(f"connection {raw['from']} -> {raw['to']}: no service {end}")
            connections.append(Connection(raw["from"], raw["to"], raw["why"]))

        generated = []
        for raw in data.get("generated") or []:
            if missing := {"file", "from", "command"} - set(raw):
                errors.append(f"generated {raw}: missing {', '.join(sorted(missing))}")
                continue
            generated.append(Generated(raw["file"], tuple(raw["from"]), raw["command"]))

        if errors:
            raise ModelError("\n".join(errors))
        return cls(services, tuple(connections), tuple(generated))

    def calls(self, source, target):
        """Whether the model has a source -> target connection."""
        return any(c.source == source and c.target == target for c in self.connections)

    def connects(self, a, b):
        """Whether a and b may reach each other, whichever one opens the connection."""
        return self.calls(a, b) or self.calls(b, a)
