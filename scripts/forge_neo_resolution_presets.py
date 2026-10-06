from __future__ import annotations

import inspect
import json
import math
import os
import random
import shutil
import tempfile
import threading
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

import gradio as gr

import modules.scripts as scripts
from modules import shared


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
MAX_BUILTIN_PRESETS = 14
MAX_NAME_LENGTH = 32
MIN_DIMENSION = 16
MAX_DIMENSION = 16384
DEFAULT_ROUNDING = 8
SUPPORTED_RESOLUTION_STEPS = (8, 16, 32, 64, 128, 256)
MAX_HISTORY = 12
MAX_IMPORT_BYTES = 5 * 1024 * 1024
HISTORY_LOCK = threading.Lock()


def register_click_compatible(component, *, js_code=None, **kwargs):
    """Register a click handler across Gradio variants using js or _js."""
    parameters = inspect.signature(component.click).parameters
    accepts_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )

    if js_code is not None:
        if "js" in parameters or accepts_kwargs:
            kwargs["js"] = js_code
        elif "_js" in parameters:
            kwargs["_js"] = js_code
        else:
            raise TypeError(
                "This Gradio click handler supports neither 'js' nor '_js'."
            )

    return component.click(**kwargs)


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
    return (
        isinstance(value, int)
        and MIN_DIMENSION <= value <= MAX_DIMENSION
        and value % 8 == 0
    )


def _resolution_step() -> int:
    try:
        step = int(getattr(shared.opts, "res_step", DEFAULT_ROUNDING))
    except (TypeError, ValueError):
        step = DEFAULT_ROUNDING
    return step if step > 0 else DEFAULT_ROUNDING


def _component_number(component: Any, name: str, fallback: int) -> int:
    try:
        return int(getattr(component, name))
    except (AttributeError, TypeError, ValueError):
        return fallback


def _native_constraints(width_component: Any = None, height_component: Any = None) -> tuple[int, int, int]:
    components = [component for component in (width_component, height_component) if component is not None]
    minimum = max(
        [MIN_DIMENSION]
        + [_component_number(component, "minimum", MIN_DIMENSION) for component in components]
    )
    maximum = min(
        [MAX_DIMENSION]
        + [_component_number(component, "maximum", MAX_DIMENSION) for component in components]
    )
    step = _resolution_step()
    for component in components:
        component_step = _component_number(component, "step", 0)
        if component_step > 0:
            step = component_step
            break
    if maximum < minimum:
        minimum, maximum = MIN_DIMENSION, MAX_DIMENSION
    return minimum, maximum, max(1, step)


def _is_step_compatible(
    width: Any,
    height: Any,
    minimum: int = MIN_DIMENSION,
    maximum: int = MAX_DIMENSION,
    step: int | None = None,
) -> bool:
    try:
        width_value = int(width)
        height_value = int(height)
        step_value = int(step if step is not None else _resolution_step())
    except (TypeError, ValueError):
        return False
    return (
        step_value > 0
        and minimum <= width_value <= maximum
        and minimum <= height_value <= maximum
        and width_value % step_value == 0
        and height_value % step_value == 0
    )


def _exact_preset(
    width: int,
    height: int,
    minimum: int,
    maximum: int,
) -> tuple[int, int] | None:
    """Keep approved preset dimensions exactly; the slider step is not a validator."""
    pair = _resolution_pair(width, height)
    if pair is None or not all(minimum <= value <= maximum for value in pair):
        return None
    return pair


def _rounding_choices(native_step: int) -> list[int]:
    step = max(1, int(native_step))
    choices = [
        value
        for value in SUPPORTED_RESOLUTION_STEPS
        if value >= step and value % step == 0
    ]
    if step not in choices:
        choices.insert(0, step)
    return sorted(set(choices))


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
        with HISTORY_LOCK:
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
            fd, temp_name = tempfile.mkstemp(prefix="resolution-history-", suffix=".tmp", dir=str(DATA_PATH))
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    json.dump(history[:MAX_HISTORY], handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
                os.replace(temp_name, HISTORY_PATH)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
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
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
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


def _round_dimension(
    value: float,
    rounding: int,
    minimum: int = MIN_DIMENSION,
    maximum: int = MAX_DIMENSION,
) -> int:
    rounded = int(round(value / rounding) * rounding)
    return min(maximum, max(minimum, rounded))


def _calculate_dimensions(
    width: Any,
    height: Any,
    ratio: Any,
    rounding: Any,
    minimum: int = MIN_DIMENSION,
    maximum: int = MAX_DIMENSION,
) -> tuple[int, int]:
    if not _is_dimension(int(width)) or not _is_dimension(int(height)):
        raise ValueError("Width／Heightが不正です")
    ratio_value = _parse_ratio(ratio)
    rounding_value = int(rounding)
    if rounding_value <= 0 or rounding_value > MAX_DIMENSION:
        raise ValueError("丸め幅が不正です")

    area = int(width) * int(height)
    target_width = math.sqrt(area * float(ratio_value))
    target_height = math.sqrt(area / float(ratio_value))
    return (
        _round_dimension(target_width, rounding_value, minimum, maximum),
        _round_dimension(target_height, rounding_value, minimum, maximum),
    )


def _ratio_result(
    width: Any,
    height: Any,
    ratio: Any,
    rounding: Any,
    minimum: int = MIN_DIMENSION,
    maximum: int = MAX_DIMENSION,
) -> str:
    try:
        result = _calculate_dimensions(width, height, ratio, rounding, minimum, maximum)
    except (ValueError, TypeError, ZeroDivisionError):
        return "—"
    return f"{result[0]}×{result[1]}"


def _same_resolution(width: Any, height: Any, current_width: Any, current_height: Any) -> bool:
    try:
        return int(width) == int(current_width) and int(height) == int(current_height)
    except (TypeError, ValueError):
        return False


def _preset_button_variant(
    width: Any,
    height: Any,
    current_width: Any,
    current_height: Any,
) -> str:
    if _same_resolution(width, height, current_width, current_height):
        return "primary"
    if _same_resolution(height, width, current_width, current_height):
        return "stop"
    return "secondary"


def _current_info(width: Any, height: Any) -> str:
    try:
        width_value = int(width)
        height_value = int(height)
    except (TypeError, ValueError):
        return "Current —"
    if not _is_dimension(width_value) or not _is_dimension(height_value):
        return "Current —"
    megapixels = width_value * height_value / 1_000_000
    return f"Current `{width_value}×{height_value}` · {megapixels:.2f} MP"


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
    interactive: bool | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "value": label,
        "visible": visible,
        "variant": variant,
    }
    if interactive is not None:
        kwargs["interactive"] = interactive
    return gr.update(**kwargs)


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
    native_constraints: tuple[int, int, int] | None = None,
) -> list[Any]:
    presets = _load_user_presets()
    outputs: list[Any] = [gr.update(value=f"User ({len(presets)})")]

    for index in range(MAX_USER_PRESETS):
        if index < len(presets):
            preset = presets[index]
            exact = _exact_preset(preset["width"], preset["height"], *(native_constraints or _native_constraints())[:2])
            variant = "primary" if _same_resolution(
                *(exact or (None, None)), current_width, current_height
            ) else "secondary"
            label = preset["name"]
            outputs.append(_button_update(label, variant=variant, interactive=exact is not None))
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

    def before_process(self, p, randomize_enabled=False, profile_name=None, native_constraints=None):
        if not bool(randomize_enabled):
            return
        _, profiles, _ = _load_profiles()
        values = profiles.get(str(profile_name), [])
        if _load_behavior_settings()["randomize_user_presets"]:
            values += [
                (item["width"], item["height"])
                for item in _load_user_presets()
            ]
        constraints = native_constraints or _native_constraints()
        # Use the UI's active slider constraints, even if settings were saved without a restart.
        compatible_values = list(dict.fromkeys(
            exact for width, height in values
            if (exact := _exact_preset(width, height, *constraints[:2])) is not None
        ))
        if compatible_values:
            p.width, p.height = random.choice(compatible_values)

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
        native_minimum, native_maximum, native_step = _native_constraints(
            width_component, height_component
        )

        def native_compatible(width, height):
            return _exact_preset(width, height, native_minimum, native_maximum) is not None

        def exact_preset(width, height):
            return _exact_preset(width, height, native_minimum, native_maximum)

        def refresh_user_controls(*args, **kwargs):
            return _refresh_user_controls(
                *args, **kwargs, native_constraints=(native_minimum, native_maximum, native_step)
            )

        selected_profile = _load_last_profile(tab_key, profile_names, default_profile)
        randomize_default = _load_behavior_settings()["randomize_default"]
        randomize_state = gr.State(randomize_default)
        native_constraints_state = gr.State((native_minimum, native_maximum, native_step))
        previous_resolution = gr.State(None)

        def preset_button_updates(values, current_width, current_height):
            updates = []
            for index in range(MAX_BUILTIN_PRESETS):
                if index < len(values):
                    width, height = values[index]
                    exact = exact_preset(width, height)
                    updates.append(
                        _button_update(
                            f"{width}×{height}",
                            variant=_preset_button_variant(
                                *(exact or (None, None)),
                                current_width,
                                current_height,
                            ),
                            interactive=exact is not None,
                        )
                    )
                else:
                    updates.append(
                        _button_update(
                            "",
                            visible=False,
                        )
                    )
            return updates

        def builtin_button_updates(selected, current_width, current_height):
            values = profiles.get(selected, [])
            return preset_button_updates(
                values, current_width, current_height
            )

        with gr.Accordion(
            "Resolution Presets",
            open=True,
            elem_id=root_id,
            elem_classes=["fnp__accordion"],
        ):
            with gr.Row(elem_id=preset_row_id, elem_classes=["fnp__preset_row"]):
                preset_buttons: list[Any] = []
                for index in range(MAX_BUILTIN_PRESETS):
                    initial = profiles[selected_profile][index] if index < len(profiles[selected_profile]) else None
                    exact = exact_preset(*initial) if initial else None
                    label = f"{initial[0]}×{initial[1]}" if initial else ""
                    button = gr.Button(
                        label,
                        visible=initial is not None,
                        variant=(
                            _preset_button_variant(
                                *(exact or (None, None)),
                                initial_width,
                                initial_height,
                            )
                            if initial
                            else "secondary"
                        ),
                        interactive=exact is not None,
                        elem_classes=["fnp__preset_button"],
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

            with gr.Row(elem_classes=["fnp__user_row"]):
                user_count = gr.Markdown(f"User ({len(initial_user_presets)})", elem_classes=["fnp__user_count"])
                user_buttons: list[Any] = []
                for index in range(MAX_USER_PRESETS):
                    initial_user = initial_user_presets[index] if index < len(initial_user_presets) else None
                    exact = exact_preset(initial_user["width"], initial_user["height"]) if initial_user else None
                    user_label = initial_user["name"] if initial_user else ""
                    user_buttons.append(
                        gr.Button(
                            user_label,
                            visible=initial_user is not None,
                            variant=(
                                "primary"
                                if initial_user
                                and _same_resolution(
                                    *(exact or (None, None)),
                                    initial_width,
                                    initial_height,
                                )
                                else "secondary"
                            ),
                            interactive=exact is not None,
                            elem_classes=["fnp__user_button"],
                        )
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
                        choices=_rounding_choices(native_step),
                        value=native_step,
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
            updates = []
            for index in range(MAX_USER_PRESETS):
                if index >= len(presets):
                    updates.append(_button_update("", visible=False, interactive=False))
                    continue
                preset = presets[index]
                exact = exact_preset(preset["width"], preset["height"])
                label = preset["name"]
                variant = "primary" if _same_resolution(
                    *(exact or (None, None)), current_width, current_height
                ) else "secondary"
                updates.append(_button_update(label, variant=variant, interactive=exact is not None))
            return updates

        def profile_changed(selected, current_width, current_height):
            _save_last_profile(tab_key, selected)
            return builtin_button_updates(selected, current_width, current_height)

        profile.change(
            profile_changed,
            inputs=[profile, width_component, height_component],
            outputs=preset_buttons,
            show_progress="hidden",
        )

        def dimension_changed(selected, current_width, current_height):
            return (
                builtin_button_updates(selected, current_width, current_height)
                + user_button_updates(current_width, current_height)
                + [_current_info(current_width, current_height)]
            )

        def record_dimension_release(selected, current_width, current_height):
            _record_resolution_history(tab_key, selected, current_width, current_height)

        for dimension_component in [width_component, height_component]:
            dimension_change = getattr(dimension_component, "change", None)
            if dimension_change is not None:
                dimension_change(
                    dimension_changed,
                    inputs=[profile, width_component, height_component],
                    outputs=preset_buttons + user_buttons + [current_info],
                    show_progress="hidden",
                )
            dimension_release = getattr(dimension_component, "release", None)
            if dimension_release is not None:
                dimension_release(
                    record_dimension_release,
                    inputs=[profile, width_component, height_component],
                    outputs=None,
                    show_progress="hidden",
                )

        resolution_outputs = [
            width_component,
            height_component,
            previous_resolution,
            undo_button,
        ] + preset_buttons + user_buttons + [current_info]

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

        for index, button in enumerate(preset_buttons):
            preset_index = index

            def apply_builtin_preset(selected, current_w, current_h, preset_index=preset_index):
                values = profiles.get(selected, [])
                if preset_index < len(values):
                    exact = exact_preset(*values[preset_index])
                    if exact is None:
                        return [gr.update() for _ in resolution_outputs]
                    preset_w, preset_h = exact
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
                    exact = exact_preset(presets[index]["width"], presets[index]["height"])
                    if exact is None:
                        return [gr.update() for _ in resolution_outputs]
                    return resolution_action(
                        selected,
                        *exact,
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
            exact = exact_preset(*values[0])
            if exact is None:
                return current_width, current_height, previous, gr.update(interactive=previous is not None)
            target_width, target_height = exact
            _record_resolution_history(tab_key, selected, target_width, target_height)
            return target_width, target_height, previous, gr.update(interactive=previous is not None)

        reset_button.click(
            reset_profile,
            inputs=[profile, width_component, height_component],
            outputs=[width_component, height_component, previous_resolution, undo_button],
            show_progress="hidden",
        )

        def undo_resolution(selected, current_width, current_height, previous):
            if not isinstance(previous, (list, tuple)) or len(previous) != 2:
                return current_width, current_height, None, gr.update(interactive=False)
            if native_compatible(previous[0], previous[1]):
                _record_resolution_history(tab_key, selected, previous[0], previous[1])
            return previous[0], previous[1], None, gr.update(interactive=False)

        undo_button.click(
            undo_resolution,
            inputs=[profile, width_component, height_component, previous_resolution],
            outputs=[width_component, height_component, previous_resolution, undo_button],
            show_progress="hidden",
        )

        register_click_compatible(
            copy_button,
            fn=None,
            inputs=[width_component, height_component],
            outputs=[],
            js_code="(width, height) => { navigator.clipboard?.writeText(`${width}×${height}`); }",
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
                    return refresh_user_controls(
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
                return refresh_user_controls(
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
                return refresh_user_controls(
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
                return refresh_user_controls(
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
                return refresh_user_controls(
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
                if source.stat().st_size > MAX_IMPORT_BYTES:
                    raise ValueError("JSONファイルは5 MiB以下にしてください")
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
                return refresh_user_controls(
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
                return refresh_user_controls(
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
                    return refresh_user_controls(
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
                return refresh_user_controls(
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

        def ratio_result_for_ui(width, height, ratio, precision):
            return _ratio_result(
                width,
                height,
                ratio,
                precision,
                native_minimum,
                native_maximum,
            )

        for quick_ratio, quick_button in zip(("1:1", "4:5", "3:4", "2:3", "9:16"), quick_ratio_buttons):
            quick_button.click(
                lambda current_width, current_height, current_rounding, ratio=quick_ratio: (
                    ratio,
                    ratio_result_for_ui(
                        current_width,
                        current_height,
                        ratio,
                        current_rounding,
                    ),
                ),
                inputs=[width_component, height_component, rounding],
                outputs=[aspect_ratio, result],
                show_progress="hidden",
            )

        for component in [width_component, height_component, aspect_ratio, rounding]:
            event = getattr(component, "input", None) if component is aspect_ratio else getattr(component, "change", None)
            if event is not None:
                event(
                    ratio_result_for_ui,
                    inputs=ratio_inputs,
                    outputs=[result],
                    show_progress="hidden",
                )

        def apply_ratio_values(selected, width, height, ratio, precision):
            try:
                target_width, target_height = _calculate_dimensions(
                    width,
                    height,
                    ratio,
                    precision,
                    native_minimum,
                    native_maximum,
                )
            except (ValueError, TypeError, ZeroDivisionError):
                return width, height
            if native_compatible(target_width, target_height):
                _record_resolution_history(tab_key, selected, target_width, target_height)
            return target_width, target_height

        apply_ratio.click(
            apply_ratio_values,
            inputs=[profile] + ratio_inputs,
            outputs=[width_component, height_component],
            show_progress="hidden",
        )

        return [randomize_state, profile, native_constraints_state]
