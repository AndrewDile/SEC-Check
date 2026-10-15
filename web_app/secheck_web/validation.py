"""Validation driven by the OpenAPI contract files.

Supports the subset of OpenAPI 3.0 / JSON Schema used by our specs: $ref, allOf,
type, nullable, enum, pattern, minLength, maxLength, minimum, maximum, minItems,
maxItems, items, required, properties, additionalProperties: false,
minProperties and format: date-time.

Because rules come from the contract, changing a constraint in the spec (an
enum value, a max length, a required field) changes validation without code
changes. Regenerate contracts with tools/sync_contracts.py.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

HTTP_METHODS = ("get", "post", "put", "patch", "delete")


def parse_datetime(value: Any) -> Optional[datetime]:
    """Parse an RFC 3339 / ISO 8601 date-time. Naive values are treated as UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text[-1] in "Zz":
        text = text[:-1] + "+00:00"
    # Python < 3.11 only accepts 3 or 6 fractional digits; normalise to 6.
    match = re.match(r"^(.*T\d{2}:\d{2}:\d{2})\.(\d+)(.*)$", text)
    if match:
        text = f"{match.group(1)}.{match.group(2)[:6].ljust(6, '0')}{match.group(3)}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def format_utc(dt: datetime) -> str:
    """Format as UTC with millisecond precision and a Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def utc_now() -> str:
    return format_utc(datetime.now(timezone.utc))


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return True


class Spec:
    """An OpenAPI document plus helpers to resolve and validate against it."""

    def __init__(self, doc: Dict[str, Any]):
        self.doc = doc

    @classmethod
    def load(cls, path: Path) -> "Spec":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    # ---- lookups -------------------------------------------------------
    def resolve(self, node: Any) -> Any:
        seen = 0
        while isinstance(node, dict) and "$ref" in node:
            ref = node["$ref"]
            if not ref.startswith("#/"):
                raise ValueError(f"Only local $ref values are supported: {ref}")
            target: Any = self.doc
            for part in ref[2:].split("/"):
                target = target[part]
            node = target
            seen += 1
            if seen > 50:
                raise ValueError(f"$ref loop at {ref}")
        return node

    def base_path(self) -> str:
        servers = self.doc.get("servers") or [{}]
        url = (servers[0] or {}).get("url") or ""
        return url.rstrip("/")

    def operations(self):
        """Yield (path, method, operation, path_item) for every operation."""
        for path, item in (self.doc.get("paths") or {}).items():
            for method in HTTP_METHODS:
                if method in item:
                    yield path, method, item[method], item

    def parameters(self, op: Dict[str, Any], path_item: Dict[str, Any]) -> List[Dict[str, Any]]:
        params = {}
        for raw in list(path_item.get("parameters", [])) + list(op.get("parameters", [])):
            p = self.resolve(raw)
            params[(p["name"], p["in"])] = p
        return list(params.values())

    def request_schema(self, op: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        body = self.resolve(op.get("requestBody") or {})
        return ((body.get("content") or {}).get("application/json") or {}).get("schema")

    def request_body_required(self, op: Dict[str, Any]) -> bool:
        return bool(self.resolve(op.get("requestBody") or {}).get("required"))

    def property_names(self, schema: Any) -> set:
        """All property names of an object schema, following $ref and allOf."""
        schema = self.resolve(schema) or {}
        names = set((schema.get("properties") or {}).keys())
        for sub in schema.get("allOf", []):
            names |= self.property_names(sub)
        return names

    # ---- validation ------------------------------------------------------
    def validate(self, value: Any, schema: Any, path: str = "") -> List[str]:
        errors: List[str] = []
        self._check(value, schema, path, errors)
        return errors

    def _check(self, value: Any, schema: Any, path: str, errors: List[str]) -> None:
        schema = self.resolve(schema)
        if not isinstance(schema, dict) or not schema:
            return
        label = path or "value"
        for sub in schema.get("allOf", []):
            self._check(value, sub, path, errors)
        if value is None:
            if not schema.get("nullable") and ("type" in schema or "enum" in schema):
                errors.append(f"{label} must not be null")
            return
        expected = schema.get("type")
        if expected and not _type_ok(value, expected):
            errors.append(f"{label} must be of type {expected}")
            return
        if "enum" in schema and value not in schema["enum"]:
            errors.append(f"{label} must be one of: {', '.join(str(v) for v in schema['enum'])}")
        if isinstance(value, str):
            if "minLength" in schema and len(value) < schema["minLength"]:
                errors.append(f"{label} must be at least {schema['minLength']} characters")
            if "maxLength" in schema and len(value) > schema["maxLength"]:
                errors.append(f"{label} must be at most {schema['maxLength']} characters")
            if "pattern" in schema and not re.search(schema["pattern"], value):
                errors.append(f"{label} has an invalid format")
            if schema.get("format") == "date-time" and parse_datetime(value) is None:
                errors.append(f"{label} must be an RFC 3339 date-time, e.g. 2026-09-25T20:00:00Z")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                errors.append(f"{label} must be >= {schema['minimum']}")
            if "maximum" in schema and value > schema["maximum"]:
                errors.append(f"{label} must be <= {schema['maximum']}")
        if isinstance(value, list):
            if "minItems" in schema and len(value) < schema["minItems"]:
                errors.append(f"{label} must contain at least {schema['minItems']} item(s)")
            if "maxItems" in schema and len(value) > schema["maxItems"]:
                errors.append(f"{label} must contain at most {schema['maxItems']} item(s)")
            if "items" in schema:
                for i, item in enumerate(value):
                    self._check(item, schema["items"], f"{label}[{i}]", errors)
        if isinstance(value, dict):
            props = schema.get("properties") or {}
            for name in schema.get("required", []):
                if name not in value:
                    errors.append(f"{_join(path, name)} is required")
            for name, sub in props.items():
                if name in value:
                    self._check(value[name], sub, _join(path, name), errors)
            if schema.get("additionalProperties") is False:
                allowed = self.property_names(schema)
                for name in value:
                    if name not in allowed:
                        errors.append(f"{_join(path, name)} is not an allowed field")
            if "minProperties" in schema and len(value) < schema["minProperties"]:
                errors.append(f"{label} must contain at least {schema['minProperties']} field(s)")


def _join(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name


def coerce_query(raw: str, schema: Dict[str, Any]) -> Any:
    """Convert a query-string value to the type its schema declares."""
    kind = (schema or {}).get("type")
    if kind == "integer":
        try:
            return int(raw)
        except ValueError:
            return raw
    if kind == "number":
        try:
            return float(raw)
        except ValueError:
            return raw
    if kind == "boolean":
        lowered = raw.lower()
        if lowered in ("true", "1", "yes"):
            return True
        if lowered in ("false", "0", "no"):
            return False
        return raw
    return raw
