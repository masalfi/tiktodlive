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
    category: str
    params: list[ParamSpec] = field(default_factory=list)
    dangerous: bool = False
    help: str = ""
    # Urutan tampil dalam kelompoknya - yang sering dipakai diletakkan di
    # atas. Tanpa ini daftar tersusun alfabetis dan aksi penting tenggelam.
    order: int = 100
    # Aksi lama yang sudah digantikan. Tetap jalan untuk rule yang sudah
    # ada, tapi disembunyikan dari daftar supaya tidak membingungkan.
    hidden: bool = False


# Kelompok aksi dalam bahasa sehari-hari, beserta urutan tampilnya.
CATEGORY_LABEL = {
    "overlay": "Overlay (tampil di OBS)",
    "adb": "Kontrol HP",
    "app": "Aplikasi di HP",
    "game": "Game",
    "host": "Komputer",
}
CATEGORY_ORDER = ["overlay", "adb", "app", "game", "host"]


# type -> ActionSpec
REGISTRY: dict[str, ActionSpec] = {}
# type -> callable(executor_ctx, params) -> ActionResult
HANDLERS: dict[str, Callable[..., ActionResult]] = {}


# Urutan tampil & aksi lama, dikumpulkan di satu tempat supaya mudah
# ditinjau: mana yang sering dipakai, mana yang sudah ada penggantinya.
# (order, hidden)
ACTION_META: dict[str, tuple[int, bool]] = {
    # --- Kontrol HP: yang paling sering dipakai di atas
    "adb.tap": (10, False),
    "adb.swipe": (20, False),
    "adb.keyevent": (30, False),
    "adb.text": (40, False),
    "adb.volume": (50, False),
    "adb.brightness": (60, False),
    "adb.rotate": (70, False),
    "adb.screenshot": (80, False),
    "adb.open_url": (90, False),
    "adb.wifi": (100, False),
    "adb.airplane": (110, False),
    "adb.reboot": (120, False),
    "adb.shell": (130, False),
    # Digantikan aksi kelompok "Aplikasi di HP" yang punya pemilih aplikasi.
    "adb.open_app": (900, True),
    "adb.close_app": (900, True),
    # --- Aplikasi
    "app.close_game": (10, False),
    "app.restart_game": (20, False),
    "app.close_foreground": (30, False),
    "app.open": (40, False),
    "app.close": (50, False),
    "app.restart": (60, False),
    "app.clear_background": (70, False),
    # --- Game
    "game.tap_button": (10, False),
    "game.hold_button": (20, False),
    "game.combo": (30, False),
    "game.aim_skill": (40, False),
    "game.move": (50, False),
    # --- Komputer
    "host.wait": (10, False),
    "host.sound": (20, False),
    "host.keypress": (30, False),
    "host.launch_scrcpy": (40, False),
    "host.stop_scrcpy": (50, False),
    "host.script": (60, False),
}


def register(spec: ActionSpec, handler: Callable[..., ActionResult]) -> None:
    meta = ACTION_META.get(spec.type)
    if meta is not None:
        spec.order, spec.hidden = meta
    REGISTRY[spec.type] = spec
    HANDLERS[spec.type] = handler


def get_spec(action_type: str) -> ActionSpec | None:
    return REGISTRY.get(action_type)


def specs_by_category(include_hidden: bool = False) -> dict[str, list[ActionSpec]]:
    """Aksi per kelompok, sudah urut. Aksi lama disembunyikan."""
    out: dict[str, list[ActionSpec]] = {}
    for spec in REGISTRY.values():
        if spec.hidden and not include_hidden:
            continue
        out.setdefault(spec.category, []).append(spec)
    for items in out.values():
        items.sort(key=lambda s: (s.order, s.label))
    return out


def grouped_specs(include_hidden: bool = False) -> list[tuple[str, list[ActionSpec]]]:
    """[(judul kelompok, aksi)] dalam urutan yang enak dibaca."""
    by_category = specs_by_category(include_hidden)
    groups: list[tuple[str, list[ActionSpec]]] = []
    for key in CATEGORY_ORDER:
        if by_category.get(key):
            groups.append((CATEGORY_LABEL.get(key, key), by_category.pop(key)))
    # Kelompok tak terduga tetap ditampilkan, jangan sampai aksi hilang.
    for key, items in sorted(by_category.items()):
        groups.append((CATEGORY_LABEL.get(key, key), items))
    return groups


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
