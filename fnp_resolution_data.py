"""Pure profile validation/recovery and process-local history synchronization.

No Forge imports or route registration. Each caller supplies its own file paths.
"""
from __future__ import annotations
import json
import threading
from pathlib import Path
from typing import Any

MIN_DIMENSION = 16
MAX_DIMENSION = 16384
MAX_PRESETS = 15
MAX_NAME_LENGTH = 32
HISTORY_LOCK = threading.Lock()


def _is_dimension(value):
    return isinstance(value, int) and not isinstance(value, bool) and MIN_DIMENSION <= value <= MAX_DIMENSION


def default_profiles() -> dict[str, Any]:
    return {
        "default_profile": "Anima",
        "profiles": [
            {
                "name": "Anima",
                "presets": [
                    {"width": 1024, "height": 1024},
                    {"width": 1280, "height": 1280},
                    {"width": 896, "height": 1152},
                    {"width": 1024, "height": 1344},
                    {"width": 960, "height": 1280},
                    {"width": 832, "height": 1152},
                    {"width": 832, "height": 1216},
                    {"width": 1024, "height": 1536},
                    {"width": 768, "height": 1280},
                    {"width": 1136, "height": 1424},
                    {"width": 1104, "height": 1472},
                    {"width": 1040, "height": 1552},
                    {"width": 960, "height": 1696},
                ],
            }
        ],
    }



def normalise_document(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Profile JSONが不正です")

    profiles: list[dict[str, Any]] = []
    names: set[str] = set()
    items = raw.get("profiles")
    if not isinstance(items, list):
        raise ValueError("Profile listが不正です")
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name or len(name) > MAX_NAME_LENGTH:
            raise ValueError("Profile名は1～32文字で入力してください")
        key = name.casefold()
        if key in names:
            raise ValueError(f"Profile名が重複しています: {name}")
        presets: list[dict[str, int]] = []
        pairs: set[tuple[int, int]] = set()
        values = item.get("presets")
        if not isinstance(values, list):
            raise ValueError("Preset listが不正です")
        for preset in values:
            if not isinstance(preset, dict):
                continue
            width = preset.get("width")
            height = preset.get("height")
            if not _is_dimension(width) or not _is_dimension(height):
                continue
            if width % 8 or height % 8:
                raise ValueError(f"{name}: Width／Heightは8の倍数にしてください")
            pair = (width, height)
            if pair in pairs:
                raise ValueError(f"{name}: 重複した解像度があります（{width}×{height}）")
            pairs.add(pair)
            presets.append({"width": width, "height": height})
            if len(presets) >= MAX_PRESETS:
                break
        if not presets:
            raise ValueError(f"{name}: プリセットがありません")
        names.add(key)
        profiles.append({"name": name, "presets": presets})

    if not profiles:
        raise ValueError("Profileがありません")
    default_profile = str(raw.get("default_profile", "")).strip()
    if default_profile.casefold() not in {item["name"].casefold() for item in profiles}:
        default_profile = profiles[0]["name"]
    else:
        default_profile = next(
            item["name"] for item in profiles if item["name"].casefold() == default_profile.casefold()
        )
    return {"default_profile": default_profile, "profiles": profiles}



def load_profiles_document(override: Path, builtin: Path):
    # Recovery is read-only. Invalid overrides never overwrite the user's file.
    for path in (override, builtin):
        try:
            return normalise_document(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            continue
    return normalise_document(default_profiles())


def clear_history(path: Path):
    with HISTORY_LOCK:
        path.unlink(missing_ok=True)
