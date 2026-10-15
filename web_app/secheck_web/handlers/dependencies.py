"""Dependencies (Web App API 4.15)."""
from __future__ import annotations

from typing import Any, Dict

from . import Context, Request, extension, operation


@operation("addDependency")
def add_dependency(ctx: Context, req: Request) -> Dict[str, Any]:
    return ctx.core.dp_new(None, req.json["dp_name"])


@operation("matchDependency")
def match_dependency(ctx: Context, req: Request) -> Dict[str, Any]:
    return ctx.core.dp_match(None, req.path_params["dp_name"])


@operation("removeDependency")
def remove_dependency(ctx: Context, req: Request) -> Dict[str, Any]:
    return ctx.core.dp_remove(None, req.path_params["dp_name"])


@extension("GET", "/dependencies", note="PROPOSED list of all dependencies (gap G-5)")
def list_dependencies(ctx: Context, req: Request) -> Dict[str, Any]:
    return {"Dependencies": ctx.core.dp_list(None)}
