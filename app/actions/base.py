"""Registry aksi + spesifikasi parameter.

Spec dipakai dua arah: validasi saat eksekusi, dan pembangunan form
dinamis di editor rule (GUI membaca spec, bukan hardcode field).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.models import ActionResult


@dataclass
class ParamSpec:
    """Satu parameter dari sebuah aksi."""

    name: str
    label: str
    kind: str = "str"                 # str | int | float | bool | choice | file
    default: Any = None
    choices: list[str] = field(default_factory=list)
    minimum: int | None = None
    maximum: int | None = None
    help: str = ""


@dataclass
class ActionSpec:
    """Metadata satu tipe aksi."""

    type: str
    label: str
    category: str                     # "adb" | "host"
    params: list[ParamSpec] = field(default_factory=list)
    dangerous: bool = False
    help: str = ""


# type -> ActionSpec
REGISTRY: dict[str, ActionSpec] = {}
# type -> callable(executor_ctx, params) -> ActionResult
HANDLERS: dict[str, Callable[..., ActionResult]] = {}


def register(spec: ActionSpec, handler: Callable[..., ActionResult]) -> None:
    REGISTRY[spec.type] = spec
    HANDLERS[spec.type] = handler


def get_spec(action_type: str) -> ActionSpec | None:
    return REGISTRY.get(action_type)


def specs_by_category() -> dict[str, list[ActionSpec]]:
    out: dict[str, list[ActionSpec]] = {}
    for spec in REGISTRY.values():
        out.setdefault(spec.category, []).append(spec)
    for items in out.values():
        items.sort(key=lambda s: s.label)
    return out


def coerce_params(action_type: str, params: dict[str, Any]) -> dict[str, Any]:
    """Terapkan default dan konversi tipe sesuai spec."""
    spec = REGISTRY.get(action_type)
    if spec is None:
        return dict(params)
    out: dict[str, Any] = {}
    for p in spec.params:
        raw = params.get(p.name, p.default)
        if raw is None or raw == "":
            out[p.name] = p.default
            continue
        try:
            if p.kind == "int":
                out[p.name] = int(raw)
            elif p.kind == "float":
                out[p.name] = float(raw)
            elif p.kind == "bool":
                out[p.name] = raw if isinstance(raw, bool) else str(raw).lower() in ("1", "true", "yes", "on")
            else:
                out[p.name] = str(raw)
        except (TypeError, ValueError):
            out[p.name] = p.default
    return out
