from __future__ import annotations

import json
import math
import os
import random
import shutil
import tempfile
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

import gradio as gr

import modules.scripts as scripts


BASE_PATH = Path(scripts.basedir())
PROFILES_PATH = BASE_PATH / "profiles.json"
DATA_PATH = BASE_PATH / "data"
USER_PRESETS_PATH = DATA_PATH / "user_presets.json"
BACKUP_PATH = DATA_PATH / "backups"
EXPORT_PATH = DATA_PATH / "user_presets-export.json"
LAST_PROFILES_PATH = DATA_PATH / "last_profiles.json"
PROFILE_OVERRIDES_PATH = DATA_PATH / "profile_overrides.json"
BEHAVIOR_SETTINGS_PATH = DATA_PATH / "behavior_settings.json"
HISTORY_PATH = DATA_PATH / "resolution_history.json"

MAX_USER_PRESETS = 8
MAX_CORE_PRESETS = 9
MAX_EXTENDED_PRESETS = 5
MAX_BUILTIN_PRESETS = MAX_CORE_PRESETS + MAX_EXTENDED_PRESETS
MAX_NAME_LENGTH = 32
MIN_DIMENSION = 16
MAX_DIMENSION = 16384
DEFAULT_ROUNDING = 8
MAX_HISTORY = 12


def _default_profiles() -> dict[str, Any]:
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


def _is_dimension(value: Any) -> bool:
    return isinstance(value, int) and MIN_DIMENSION <= value <= MAX_DIMENSION


def _load_profiles() -> tuple[list[str], dict[str, list[tuple[int, int]]], str]:
    source_path = PROFILE_OVERRIDES_PATH if PROFILE_OVERRIDES_PATH.exists() else PROFILES_PATH
    try:
        raw = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        try:
            raw = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            raw = _default_profiles()

    profile_names: list[str] = []
    profiles: dict[str, list[tuple[int, int]]] = {}
    for item in raw.get("profiles", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name or name in profiles:
            continue
        values: list[tuple[int, int]] = []
        for preset in item.get("presets", []):
            if not isinstance(preset, dict):
                continue
            width = preset.get("width")
            height = preset.get("height")
            if _is_dimension(width) and _is_dimension(height):
                values.append((width, height))
        if values:
            profile_names.append(name)
            profiles[name] = values[:MAX_BUILTIN_PRESETS]

    if not profile_names:
        fallback = _default_profiles()["profiles"][0]
        name = fallback["name"]
        profile_names = [name]
        profiles[name] = [(p["width"], p["height"]) for p in fallback["presets"]]

    default_profile = str(raw.get("default_profile", "")).strip()
    if default_profile not in profiles:
        default_profile = profile_names[0]
    return profile_names, profiles, default_profile


def _load_behavior_settings() -> dict[str, bool]:
    try:
        raw = json.loads(BEHAVIOR_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        raw = {}
    return {
        "randomize_default": bool(raw.get("randomize_default", False)) if isinstance(raw, dict) else False,
        "randomize_user_presets": bool(raw.get("randomize_user_presets", False)) if isinstance(raw, dict) else False,
    }


def _record_resolution_history(tab_key: str, profile_name: str, width: Any, height: Any) -> None:
    if not _is_dimension(width) or not _is_dimension(height):
        return
    try:
        raw = json.loads(HISTORY_PATH.read_text(encoding="utf-8")) if HISTORY_PATH.exists() else []
        history = raw if isinstance(raw, list) else []
        history = [
            item for item in history
            if not (
                isinstance(item, dict)
                and item.get("tab") == tab_key
                and item.get("profile") == profile_name
                and item.get("width") == width
                and item.get("height") == height
            )
        ]
        history.insert(0, {
            "tab": tab_key,
            "profile": profile_name,
            "width": width,
            "height": height,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        })
        DATA_PATH.mkdir(parents=True, exist_ok=True)
        HISTORY_PATH.write_text(json.dumps(history[:MAX_HISTORY], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, TypeError):
        pass


def _load_last_profiles() -> dict[str, str]:
    try:
        raw = json.loads(LAST_PROFILES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _load_last_profile(tab_key: str, profile_names: list[str], fallback: str) -> str:
    saved = str(_load_last_profiles().get(tab_key, "")).strip()
    return saved if saved in profile_names else fallback


def _save_last_profile(tab_key: str, profile_name: str) -> None:
    try:
        data = _load_last_profiles()
        data[tab_key] = profile_name
        DATA_PATH.mkdir(parents=True, exist_ok=True)
        LAST_PROFILES_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def _normalise_user_presets(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        raw = raw.get("presets", [])
    if not isinstance(raw, list):
        return []

    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()[:MAX_NAME_LENGTH]
        width = item.get("width")
        height = item.get("height")
        if name.startswith("{'value':") or name.startswith('{"value"'):
            continue
        if name and _is_dimension(width) and _is_dimension(height):
            result.append({"name": name, "width": width, "height": height})
        if len(result) >= MAX_USER_PRESETS:
            break
    return result


def _load_user_presets() -> list[dict[str, Any]]:
    try:
        return _normalise_user_presets(json.loads(USER_PRESETS_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return []


def _write_user_presets(presets: list[dict[str, Any]]) -> None:
    DATA_PATH.mkdir(parents=True, exist_ok=True)
    if USER_PRESETS_PATH.exists():
        BACKUP_PATH.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = BACKUP_PATH / f"user_presets-{stamp}.json"
        shutil.copy2(USER_PRESETS_PATH, backup)
        backups = sorted(BACKUP_PATH.glob("user_presets-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[10:]:
            old.unlink(missing_ok=True)

    fd, temp_name = tempfile.mkstemp(prefix="user_presets-", suffix=".tmp", dir=str(DATA_PATH))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump({"version": 1, "presets": presets}, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, USER_PRESETS_PATH)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _parse_ratio(value: Any) -> Fraction:
    text = str(value or "").strip().replace(" ", "")
    if not text:
        raise ValueError("アスペクト比を入力してください")
    if ":" in text:
        numerator, denominator = text.split(":", 1)
    elif "/" in text:
        numerator, denominator = text.split("/", 1)
    else:
        return Fraction(text)
    ratio = Fraction(numerator) / Fraction(denominator)
    if ratio <= 0:
        raise ValueError("アスペクト比は正の値にしてください")
    return ratio


def _round_dimension(value: float, rounding: int) -> int:
    return max(MIN_DIMENSION, int(round(value / rounding) * rounding))


def _calculate_dimensions(width: Any, height: Any, ratio: Any, rounding: Any) -> tuple[int, int]:
    if not _is_dimension(int(width)) or not _is_dimension(int(height)):
        raise ValueError("Width／Heightが不正です")
    ratio_value = _parse_ratio(ratio)
    rounding_value = int(rounding)
    if rounding_value not in (1, 2, 4, 8, 16, 32, 64, 128):
        raise ValueError("丸め幅が不正です")

    area = int(width) * int(height)
    target_width = math.sqrt(area * float(ratio_value))
    target_height = math.sqrt(area / float(ratio_value))
    return (
        _round_dimension(target_width, rounding_value),
        _round_dimension(target_height, rounding_value),
    )


def _ratio_result(width: Any, height: Any, ratio: Any, rounding: Any) -> str:
    try:
        result = _calculate_dimensions(width, height, ratio, rounding)
    except (ValueError, TypeError, ZeroDivisionError):
        return "—"
    return f"{result[0]}×{result[1]}"


def _same_resolution(width: Any, height: Any, current_width: Any, current_height: Any) -> bool:
    try:
        return int(width) == int(current_width) and int(height) == int(current_height)
    except (TypeError, ValueError):
        return False


def _current_info(width: Any, height: Any) -> str:
    try:
        width_value = int(width)
        height_value = int(height)
    except (TypeError, ValueError):
        return "Current —"
    if not _is_dimension(width_value) or not _is_dimension(height_value):
        return "Current —"
    grid = "8" if width_value % 8 == 0 and height_value % 8 == 0 else "—"
    megapixels = width_value * height_value / 1_000_000
    return f"Current `{width_value}×{height_value}` · {megapixels:.2f} MP · Grid {grid}"


def _resolution_pair(width: Any, height: Any) -> tuple[int, int] | None:
    try:
        pair = (int(width), int(height))
    except (TypeError, ValueError):
        return None
    return pair if _is_dimension(pair[0]) and _is_dimension(pair[1]) else None


def _button_update(
    label: str,
    visible: bool = True,
    variant: str = "secondary",
    elem_classes: list[str] | None = None,
) -> dict[str, Any]:
    update = gr.update(value=label, visible=visible, variant=variant)
    if elem_classes is not None:
        update["elem_classes"] = elem_classes
    return update


def _refresh_user_controls(
    user_count: Any,
    user_buttons: list[Any],
    user_rows: list[Any],
    user_labels: list[Any],
    delete_buttons: list[Any],
    status: Any | None = None,
    name_input: Any | None = None,
    message: str = "",
    current_width: Any | None = None,
    current_height: Any | None = None,
    overwrite_button: Any | None = None,
    show_overwrite: bool = False,
    clear_name: bool = True,
) -> list[Any]:
    presets = _load_user_presets()
    outputs: list[Any] = [gr.update(value=f"User ({len(presets)})")]

    for index in range(MAX_USER_PRESETS):
        if index < len(presets):
            preset = presets[index]
            variant = "primary" if _same_resolution(
                preset["width"], preset["height"], current_width, current_height
            ) else "secondary"
            outputs.append(_button_update(preset["name"], variant=variant))
            outputs.append(gr.update(visible=True))
            outputs.append(gr.update(value=f"{preset['name']}  {preset['width']}×{preset['height']}"))
            outputs.append(_button_update("Delete"))
        else:
            outputs.append(_button_update("", visible=False))
            outputs.append(gr.update(visible=False))
            outputs.append(gr.update(value=""))
            outputs.append(_button_update("Delete", visible=False))

    if status is not None:
        outputs.append(message)
    if name_input is not None:
        outputs.append(gr.update(value="") if clear_name else gr.update())
    if overwrite_button is not None:
        outputs.append(gr.update(visible=show_overwrite))
    return outputs


def _export_user_presets() -> tuple[Any, str]:
    presets = _load_user_presets()
    DATA_PATH.mkdir(parents=True, exist_ok=True)
    EXPORT_PATH.write_text(
        json.dumps({"version": 1, "presets": presets}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return gr.update(value=str(EXPORT_PATH), visible=True), f"書き出しました（{len(presets)}件）"


class ForgeNeoResolutionPresets(scripts.Script):
    sorting_priority = -100

    def title(self):
        return "Resolution Presets"

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def after_component(self, component, **kwargs):
        elem_id = kwargs.get("elem_id")
        if elem_id == "txt2img_width":
            self.t2i_w = component
        elif elem_id == "txt2img_height":
            self.t2i_h = component
        elif elem_id == "img2img_width":
            self.i2i_w = component
        elif elem_id == "img2img_height":
            self.i2img_h = component
        elif elem_id == "txt2img_generate":
            self.t2i_generate = component
        elif elem_id == "img2img_generate":
            self.i2img_generate = component

    def before_process(self, p, randomize_enabled=False, profile_name=None):
        if not bool(randomize_enabled):
            return
        _, profiles, _ = _load_profiles()
        values = profiles.get(str(profile_name), [])
        if _load_behavior_settings()["randomize_user_presets"]:
            values += [
                (item["width"], item["height"])
                for item in _load_user_presets()
            ]
        if values:
            p.width, p.height = random.choice(values)

    def ui(self, is_img2img):
        profile_names, profiles, default_profile = _load_profiles()
        initial_user_presets = _load_user_presets()
        if is_img2img:
            width_component = getattr(self, "i2i_w", None)
            height_component = getattr(self, "i2img_h", None)
            generate_component = getattr(self, "i2img_generate", None)
            tab_key = "img2img"
        else:
            width_component = getattr(self, "t2i_w", None)
            height_component = getattr(self, "t2i_h", None)
            generate_component = getattr(self, "t2i_generate", None)
            tab_key = "txt2img"

        if width_component is None or height_component is None:
            return []

        root_id = f"fnp__{tab_key}_container"
        profile_id = f"fnp__{tab_key}_profile"
        preset_row_id = f"fnp__{tab_key}_preset_row"
        initial_width = getattr(width_component, "value", None)
        initial_height = getattr(height_component, "value", None)
        selected_profile = _load_last_profile(tab_key, profile_names, default_profile)
        randomize_default = _load_behavior_settings()["randomize_default"]
        randomize_state = gr.State(randomize_default)
        previous_resolution = gr.State(None)
        more_open = gr.State(False)

        def preset_button_updates(values, start, count, current_width, current_height):
            updates = []
            for index in range(start, start + count):
                if index < len(values):
                    width, height = values[index]
                    exact = _same_resolution(width, height, current_width, current_height)
                    rotated = not exact and _same_resolution(
                        height, width, current_width, current_height
                    )
                    classes = ["fnp__preset_button"]
                    if rotated:
                        classes.append("fnp__rotated_match")
                    updates.append(
                        _button_update(
                            f"{width}×{height}",
                            variant="primary" if exact else "secondary",
                            elem_classes=classes,
                        )
                    )
                else:
                    updates.append(
                        _button_update(
                            "",
                            visible=False,
                            elem_classes=["fnp__preset_button"],
                        )
                    )
            return updates

        def builtin_button_updates(selected, current_width, current_height):
            values = profiles.get(selected, [])
            return preset_button_updates(
                values, 0, MAX_CORE_PRESETS, current_width, current_height
            ) + preset_button_updates(
                values, MAX_CORE_PRESETS, MAX_EXTENDED_PRESETS, current_width, current_height
            )

        with gr.Accordion(
            "Resolution Presets",
            open=True,
            elem_id=root_id,
            elem_classes=["fnp__accordion"],
        ):
            with gr.Row(elem_id=preset_row_id, elem_classes=["fnp__preset_row"]):
                preset_buttons: list[Any] = []
                for index in range(MAX_CORE_PRESETS):
                    initial = profiles[selected_profile][index] if index < len(profiles[selected_profile]) else None
                    label = f"{initial[0]}×{initial[1]}" if initial else ""
                    exact = initial and _same_resolution(
                        initial[0], initial[1], initial_width, initial_height
                    )
                    rotated = initial and not exact and _same_resolution(
                        initial[1], initial[0], initial_width, initial_height
                    )
                    button = gr.Button(
                        label,
                        visible=initial is not None,
                        variant="primary" if exact else "secondary",
                        elem_classes=["fnp__preset_button"]
                        + (["fnp__rotated_match"] if rotated else []),
                    )
                    preset_buttons.append(button)

                with gr.Row(elem_classes=["fnp__profile_group"]):
                    randomize_button = gr.Button(
                        "Randomize",
                        size="sm",
                        variant="primary" if randomize_default else "secondary",
                        elem_classes=["fnp__randomize_button"],
                    )
                    reset_button = gr.Button("Reset", size="sm", elem_classes=["fnp__reset_button"])
                    undo_button = gr.Button(
                        "Undo",
                        size="sm",
                        interactive=False,
                        elem_classes=["fnp__undo_button"],
                    )
                    copy_button = gr.Button("Copy", size="sm", elem_classes=["fnp__copy_button"])
                    gr.Markdown("Profile", elem_classes=["fnp__profile_label"])
                    profile = gr.Dropdown(
                        choices=profile_names,
                        value=selected_profile,
                        show_label=False,
                        container=False,
                        filterable=False,
                        min_width=0,
                        elem_id=profile_id,
                        elem_classes=["fnp__profile"],
                    )

            extended_buttons: list[Any] = []
            with gr.Row(visible=False, elem_classes=["fnp__extended_row"]) as extended_row:
                for index in range(MAX_EXTENDED_PRESETS):
                    initial_index = MAX_CORE_PRESETS + index
                    initial = (
                        profiles[selected_profile][initial_index]
                        if initial_index < len(profiles[selected_profile])
                        else None
                    )
                    extended_buttons.append(
                        gr.Button(
                            f"{initial[0]}×{initial[1]}" if initial else "",
                            visible=initial is not None,
                            variant=(
                                "primary"
                                if initial
                                and _same_resolution(
                                    initial[0], initial[1], initial_width, initial_height
                                )
                                else "secondary"
                            ),
                            elem_classes=["fnp__preset_button", "fnp__extended_button"]
                            + (
                                ["fnp__rotated_match"]
                                if initial
                                and not _same_resolution(
                                    initial[0], initial[1], initial_width, initial_height
                                )
                                and _same_resolution(
                                    initial[1], initial[0], initial_width, initial_height
                                )
                                else []
                            ),
                        )
                    )

            with gr.Row(elem_classes=["fnp__user_row"]):
                user_count = gr.Markdown(f"User ({len(initial_user_presets)})", elem_classes=["fnp__user_count"])
                user_buttons: list[Any] = []
                for index in range(MAX_USER_PRESETS):
                    initial_user = initial_user_presets[index] if index < len(initial_user_presets) else None
                    user_buttons.append(
                        gr.Button(
                            initial_user["name"] if initial_user else "",
                            visible=initial_user is not None,
                            variant=(
                                "primary"
                                if initial_user
                                and _same_resolution(
                                    initial_user["width"],
                                    initial_user["height"],
                                    initial_width,
                                    initial_height,
                                )
                                else "secondary"
                            ),
                            elem_classes=["fnp__user_button"],
                        )
                    )
                more_button = gr.Button(
                    "More Portrait",
                    size="sm",
                    elem_classes=["fnp__more_button"],
                )
                current_info = gr.Markdown(
                    _current_info(initial_width, initial_height),
                    elem_classes=["fnp__current_info"],
                )
                manage_button = gr.Button("Manage", elem_classes=["fnp__manage_button"])

            manage_open = gr.State(False)

            with gr.Column(visible=False, elem_classes=["fnp__manage_panel"]) as manage_panel:
                gr.Markdown(
                    "Save the current Width / Height with a name. Click a saved preset to load it.",
                    elem_classes=["fnp__manage_hint"],
                )
                with gr.Row(elem_classes=["fnp__manage_form"]):
                    name_input = gr.Textbox(
                        label="",
                        placeholder="Preset name",
                        show_label=False,
                        container=False,
                        max_lines=1,
                        elem_classes=["fnp__name_input"],
                    )
                    save_button = gr.Button("Save current", size="sm", elem_classes=["fnp__save_button"])
                    overwrite_button = gr.Button(
                        "Update",
                        size="sm",
                        visible=False,
                        elem_classes=["fnp__overwrite_button"],
                    )
                manage_status = gr.Markdown("", elem_classes=["fnp__status"])
                with gr.Row(elem_classes=["fnp__transfer_row"]):
                    export_button = gr.Button("Export", size="sm", elem_classes=["fnp__export_button"])
                    import_file = gr.UploadButton(
                        "Choose JSON",
                        size="sm",
                        file_count="single",
                        file_types=[".json"],
                        type="filepath",
                        elem_classes=["fnp__import_file"],
                    )
                    import_button = gr.Button("Import", size="sm", elem_classes=["fnp__import_button"])
                    merge_button = gr.Button("Merge", size="sm", elem_classes=["fnp__merge_button"])
                export_file = gr.File(
                    label="",
                    show_label=False,
                    interactive=False,
                    visible=False,
                    elem_classes=["fnp__export_file"],
                )
                manage_rows: list[Any] = []
                manage_labels: list[Any] = []
                delete_buttons: list[Any] = []
                for index in range(MAX_USER_PRESETS):
                    has_preset = index < len(initial_user_presets)
                    with gr.Row(visible=has_preset, elem_classes=["fnp__manage_row"]) as manage_row:
                        initial_text = ""
                        if has_preset:
                            preset = initial_user_presets[index]
                            initial_text = f"{preset['name']}  {preset['width']}×{preset['height']}"
                        manage_labels.append(gr.Markdown(initial_text, elem_classes=["fnp__manage_label"]))
                        delete_buttons.append(gr.Button("Delete", elem_classes=["fnp__delete_button"]))
                    manage_rows.append(manage_row)

            quick_ratio_buttons: list[Any] = []
            with gr.Accordion(
                "Advanced Ratio Calculator",
                open=False,
                elem_classes=["fnp__ratio_accordion"],
            ):
                with gr.Row(elem_classes=["fnp__ratio_row"]):
                    gr.Markdown("Ratio", elem_classes=["fnp__ratio_label"])
                    aspect_ratio = gr.Textbox(
                        value="16:9",
                        show_label=False,
                        container=False,
                        max_lines=1,
                        elem_classes=["fnp__ratio_input"],
                    )
                    gr.Markdown("Area: current", elem_classes=["fnp__ratio_basis"])
                    gr.Markdown("Round", elem_classes=["fnp__rounding_label"])
                    rounding = gr.Dropdown(
                        choices=[8, 16, 32, 64],
                        value=DEFAULT_ROUNDING,
                        show_label=False,
                        container=False,
                        filterable=False,
                        min_width=55,
                        elem_classes=["fnp__rounding"],
                    )
                    result = gr.Markdown("—", elem_classes=["fnp__ratio_result"])
                    apply_ratio = gr.Button("Apply", elem_classes=["fnp__apply_button"])
                with gr.Row(elem_classes=["fnp__ratio_quick_row"]):
                    gr.Markdown("Quick", elem_classes=["fnp__ratio_quick_label"])
                    for quick_ratio in ("1:1", "4:5", "3:4", "2:3", "9:16"):
                        quick_ratio_buttons.append(
                            gr.Button(quick_ratio, size="sm", elem_classes=["fnp__ratio_quick_button"])
                        )
                gr.Markdown(
                    "Built-in: `profiles.json`  |  User: `data/user_presets.json`  |  Backup: `data/backups/`",
                    elem_classes=["fnp__path_note"],
                )

        def user_button_updates(current_width, current_height):
            presets = _load_user_presets()
            return [
                _button_update(
                    preset["name"] if index < len(presets) else "",
                    visible=index < len(presets),
                    variant=(
                        "primary"
                        if index < len(presets)
                        and _same_resolution(
                            presets[index]["width"],
                            presets[index]["height"],
                            current_width,
                            current_height,
                        )
                        else "secondary"
                    ),
                )
                for index in range(MAX_USER_PRESETS)
            ]

        def profile_changed(selected, current_width, current_height):
            _save_last_profile(tab_key, selected)
            values = profiles.get(selected, [])
            more_visible = len(values) > MAX_CORE_PRESETS
            return builtin_button_updates(selected, current_width, current_height) + [
                gr.update(value="More Portrait", visible=more_visible),
                gr.update(visible=False),
                False,
            ]

        profile.change(
            profile_changed,
            inputs=[profile, width_component, height_component],
            outputs=preset_buttons + extended_buttons + [more_button, extended_row, more_open],
            show_progress="hidden",
        )

        def toggle_more(is_open):
            next_open = not bool(is_open)
            return (
                gr.update(visible=next_open),
                gr.update(value="Less Portrait" if next_open else "More Portrait"),
                next_open,
            )

        more_button.click(
            toggle_more,
            inputs=[more_open],
            outputs=[extended_row, more_button, more_open],
            show_progress="hidden",
        )

        def dimension_changed(selected, current_width, current_height):
            _record_resolution_history(tab_key, selected, current_width, current_height)
            return (
                builtin_button_updates(selected, current_width, current_height)
                + user_button_updates(current_width, current_height)
                + [_current_info(current_width, current_height)]
            )

        for dimension_component in [width_component, height_component]:
            dimension_change = getattr(dimension_component, "change", None)
            if dimension_change is not None:
                dimension_change(
                    dimension_changed,
                    inputs=[profile, width_component, height_component],
                    outputs=preset_buttons + extended_buttons + user_buttons + [current_info],
                    show_progress="hidden",
                )

        resolution_outputs = [
            width_component,
            height_component,
            previous_resolution,
            undo_button,
        ] + preset_buttons + extended_buttons + user_buttons + [current_info]

        def resolution_action(selected, target_w, target_h, current_w, current_h):
            _record_resolution_history(tab_key, selected, target_w, target_h)
            previous = _resolution_pair(current_w, current_h)
            return [
                target_w,
                target_h,
                previous,
                gr.update(interactive=previous is not None),
            ] + builtin_button_updates(selected, target_w, target_h) + user_button_updates(
                target_w, target_h
            ) + [_current_info(target_w, target_h)]

        for index, button in enumerate(preset_buttons + extended_buttons):
            preset_index = index

            def apply_builtin_preset(selected, current_w, current_h, preset_index=preset_index):
                values = profiles.get(selected, [])
                if preset_index < len(values):
                    preset_w, preset_h = values[preset_index]
                    if _same_resolution(preset_w, preset_h, current_w, current_h):
                        target_w, target_h = preset_h, preset_w
                    elif _same_resolution(preset_h, preset_w, current_w, current_h):
                        target_w, target_h = preset_w, preset_h
                    else:
                        target_w, target_h = preset_w, preset_h
                    return resolution_action(
                        selected, target_w, target_h, current_w, current_h
                    )
                return resolution_action(selected, current_w, current_h, current_w, current_h)

            button.click(
                apply_builtin_preset,
                inputs=[profile, width_component, height_component],
                outputs=resolution_outputs,
                show_progress="hidden",
            )

        for index, button in enumerate(user_buttons):
            def apply_user_preset(selected, current_w, current_h, index=index):
                presets = _load_user_presets()
                if index < len(presets):
                    return resolution_action(
                        selected,
                        presets[index]["width"],
                        presets[index]["height"],
                        current_w,
                        current_h,
                    )
                return resolution_action(selected, current_w, current_h, current_w, current_h)

            button.click(
                apply_user_preset,
                inputs=[profile, width_component, height_component],
                outputs=resolution_outputs,
                show_progress="hidden",
            )

        def toggle_randomize(is_enabled):
            next_enabled = not bool(is_enabled)
            return (
                gr.update(variant="primary" if next_enabled else "secondary"),
                next_enabled,
            )

        randomize_button.click(
            toggle_randomize,
            inputs=[randomize_state],
            outputs=[randomize_button, randomize_state],
            show_progress="hidden",
        )

        def reset_profile(selected, current_width, current_height):
            values = profiles.get(selected, [])
            previous = _resolution_pair(current_width, current_height)
            if not values:
                return current_width, current_height, None, gr.update(interactive=False)
            return values[0][0], values[0][1], previous, gr.update(interactive=previous is not None)

        reset_button.click(
            reset_profile,
            inputs=[profile, width_component, height_component],
            outputs=[width_component, height_component, previous_resolution, undo_button],
            show_progress="hidden",
        )

        def undo_resolution(current_width, current_height, previous):
            if not isinstance(previous, (list, tuple)) or len(previous) != 2:
                return current_width, current_height, None, gr.update(interactive=False)
            return previous[0], previous[1], None, gr.update(interactive=False)

        undo_button.click(
            undo_resolution,
            inputs=[width_component, height_component, previous_resolution],
            outputs=[width_component, height_component, previous_resolution, undo_button],
            show_progress="hidden",
        )

        copy_button.click(
            fn=None,
            inputs=[width_component, height_component],
            outputs=[],
            js="(width, height) => { navigator.clipboard?.writeText(`${width}×${height}`); }",
        )

        user_outputs: list[Any] = [user_count]
        for index in range(MAX_USER_PRESETS):
            user_outputs.extend([user_buttons[index], manage_rows[index], manage_labels[index], delete_buttons[index]])

        def toggle_manage(is_open):
            next_open = not bool(is_open)
            return (
                gr.update(visible=next_open),
                gr.update(value="Close" if next_open else "Manage"),
                next_open,
            )

        manage_button.click(
            toggle_manage,
            inputs=[manage_open],
            outputs=[manage_panel, manage_button, manage_open],
            show_progress="hidden",
        )

        save_outputs = user_outputs + [manage_status, name_input, overwrite_button]

        def save_current(name, width, height):
            try:
                cleaned = str(name or "").strip()[:MAX_NAME_LENGTH]
                if not cleaned:
                    raise ValueError("プリセット名を入力してください")
                if cleaned.startswith("{'value':") or cleaned.startswith('{"value"'):
                    raise ValueError("無効なプリセット名です")
                if not _is_dimension(int(width)) or not _is_dimension(int(height)):
                    raise ValueError("現在のWidth／Heightが不正です")
                presets = _load_user_presets()
                if any(preset["name"].casefold() == cleaned.casefold() for preset in presets):
                    return _refresh_user_controls(
                        user_count,
                        user_buttons,
                        manage_rows,
                        manage_labels,
                        delete_buttons,
                        manage_status,
                        name_input,
                        "同名のプリセットがあります。Updateで上書きできます。",
                        current_width=width,
                        current_height=height,
                        overwrite_button=overwrite_button,
                        show_overwrite=True,
                        clear_name=False,
                    )
                if len(presets) >= MAX_USER_PRESETS:
                    raise ValueError(f"保存できるユーザープリセットは{MAX_USER_PRESETS}件までです")
                presets.append({"name": cleaned, "width": int(width), "height": int(height)})
                _write_user_presets(presets)
                return _refresh_user_controls(
                    user_count,
                    user_buttons,
                    manage_rows,
                    manage_labels,
                    delete_buttons,
                    manage_status,
                    name_input,
                    "保存しました",
                    current_width=width,
                    current_height=height,
                    overwrite_button=overwrite_button,
                )
            except (OSError, ValueError, TypeError) as exc:
                return _refresh_user_controls(
                    user_count,
                    user_buttons,
                    manage_rows,
                    manage_labels,
                    delete_buttons,
                    manage_status,
                    name_input,
                    f"保存できません: {exc}",
                    current_width=width,
                    current_height=height,
                    overwrite_button=overwrite_button,
                )

        save_button.click(
            save_current,
            inputs=[name_input, width_component, height_component],
            outputs=save_outputs,
            show_progress="hidden",
        )

        def overwrite_current(name, width, height):
            try:
                cleaned = str(name or "").strip()[:MAX_NAME_LENGTH]
                if not cleaned:
                    raise ValueError("プリセット名を入力してください")
                if not _is_dimension(int(width)) or not _is_dimension(int(height)):
                    raise ValueError("現在のWidth／Heightが不正です")
                presets = _load_user_presets()
                match = next(
                    (index for index, preset in enumerate(presets)
                     if preset["name"].casefold() == cleaned.casefold()),
                    None,
                )
                if match is None:
                    raise ValueError("対象のプリセットが見つかりません")
                presets[match] = {
                    "name": presets[match]["name"],
                    "width": int(width),
                    "height": int(height),
                }
                _write_user_presets(presets)
                return _refresh_user_controls(
                    user_count,
                    user_buttons,
                    manage_rows,
                    manage_labels,
                    delete_buttons,
                    manage_status,
                    name_input,
                    "更新しました",
                    current_width=width,
                    current_height=height,
                    overwrite_button=overwrite_button,
                )
            except (OSError, ValueError, TypeError) as exc:
                return _refresh_user_controls(
                    user_count,
                    user_buttons,
                    manage_rows,
                    manage_labels,
                    delete_buttons,
                    manage_status,
                    name_input,
                    f"更新できません: {exc}",
                    current_width=width,
                    current_height=height,
                    overwrite_button=overwrite_button,
                    show_overwrite=True,
                    clear_name=False,
                )

        overwrite_button.click(
            overwrite_current,
            inputs=[name_input, width_component, height_component],
            outputs=save_outputs,
            show_progress="hidden",
        )

        def import_user_presets(source_path, current_width, current_height, merge=False):
            try:
                if not source_path:
                    raise ValueError("JSONファイルを選択してください")
                source = Path(str(source_path))
                if source.suffix.lower() != ".json":
                    raise ValueError("JSONファイルを選択してください")
                imported = _normalise_user_presets(json.loads(source.read_text(encoding="utf-8")))
                unique: list[dict[str, Any]] = []
                names: set[str] = set()
                for preset in imported:
                    key = preset["name"].casefold()
                    if key not in names:
                        names.add(key)
                        unique.append(preset)
                if not unique:
                    raise ValueError("有効なプリセットがありません")
                if merge:
                    presets = _load_user_presets()
                    positions = {preset["name"].casefold(): index for index, preset in enumerate(presets)}
                    for preset in unique:
                        key = preset["name"].casefold()
                        if key in positions:
                            presets[positions[key]] = preset
                        elif len(presets) < MAX_USER_PRESETS:
                            positions[key] = len(presets)
                            presets.append(preset)
                    result_count = len(presets)
                else:
                    presets = unique[:MAX_USER_PRESETS]
                    result_count = len(presets)
                _write_user_presets(presets)
                return _refresh_user_controls(
                    user_count,
                    user_buttons,
                    manage_rows,
                    manage_labels,
                    delete_buttons,
                    manage_status,
                    None,
                    f"{'Mergeしました' if merge else '読み込みました'}（{result_count}件）",
                    current_width=current_width,
                    current_height=current_height,
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                return _refresh_user_controls(
                    user_count,
                    user_buttons,
                    manage_rows,
                    manage_labels,
                    delete_buttons,
                    manage_status,
                    None,
                    f"読み込めません: {exc}",
                    current_width=current_width,
                    current_height=current_height,
                )

        export_button.click(
            _export_user_presets,
            inputs=None,
            outputs=[export_file, manage_status],
            show_progress="hidden",
        )
        import_button.click(
            lambda source_path, current_width, current_height: import_user_presets(
                source_path, current_width, current_height, False
            ),
            inputs=[import_file, width_component, height_component],
            outputs=user_outputs + [manage_status],
            show_progress="hidden",
        )
        merge_button.click(
            lambda source_path, current_width, current_height: import_user_presets(
                source_path, current_width, current_height, True
            ),
            inputs=[import_file, width_component, height_component],
            outputs=user_outputs + [manage_status],
            show_progress="hidden",
        )

        for index, delete_button in enumerate(delete_buttons):
            def delete_current(current_width, current_height, index=index):
                presets = _load_user_presets()
                if index >= len(presets):
                    return _refresh_user_controls(
                        user_count,
                        user_buttons,
                        manage_rows,
                        manage_labels,
                        delete_buttons,
                        manage_status,
                        None,
                        "",
                        current_width=current_width,
                        current_height=current_height,
                    )
                del presets[index]
                try:
                    _write_user_presets(presets)
                    message = "削除しました"
                except OSError as exc:
                    message = f"削除できません: {exc}"
                return _refresh_user_controls(
                    user_count,
                    user_buttons,
                    manage_rows,
                    manage_labels,
                    delete_buttons,
                    manage_status,
                    None,
                    message,
                    current_width=current_width,
                    current_height=current_height,
                )

            delete_button.click(
                delete_current,
                inputs=[width_component, height_component],
                outputs=user_outputs + [manage_status],
                show_progress="hidden",
            )

        ratio_inputs = [width_component, height_component, aspect_ratio, rounding]
        for quick_ratio, quick_button in zip(("1:1", "4:5", "3:4", "2:3", "9:16"), quick_ratio_buttons):
            quick_button.click(
                lambda current_width, current_height, current_rounding, ratio=quick_ratio: (
                    ratio,
                    _ratio_result(current_width, current_height, ratio, current_rounding),
                ),
                inputs=[width_component, height_component, rounding],
                outputs=[aspect_ratio, result],
                show_progress="hidden",
            )

        for component in [width_component, height_component, aspect_ratio, rounding]:
            event = getattr(component, "input", None) if component is aspect_ratio else getattr(component, "change", None)
            if event is not None:
                event(
                    _ratio_result,
                    inputs=ratio_inputs,
                    outputs=[result],
                    show_progress="hidden",
                )

        def apply_ratio_values(width, height, ratio, precision):
            try:
                return _calculate_dimensions(width, height, ratio, precision)
            except (ValueError, TypeError, ZeroDivisionError):
                return width, height

        apply_ratio.click(
            apply_ratio_values,
            inputs=ratio_inputs,
            outputs=[width_component, height_component],
            show_progress="hidden",
        )

        return [randomize_state, profile]
