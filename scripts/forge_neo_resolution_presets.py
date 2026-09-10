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
