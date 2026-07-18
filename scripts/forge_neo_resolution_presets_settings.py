from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import gradio as gr
from fastapi import Request
from starlette.responses import JSONResponse

from modules import script_callbacks, shared


BASE_PATH = Path(__file__).resolve().parents[1]
DATA_PATH = BASE_PATH / "data"
PROFILES_PATH = BASE_PATH / "profiles.json"
PROFILE_OVERRIDES_PATH = DATA_PATH / "profile_overrides.json"
PROFILE_BACKUP_PATH = DATA_PATH / "profile_backups"
BEHAVIOR_SETTINGS_PATH = DATA_PATH / "behavior_settings.json"
HISTORY_PATH = DATA_PATH / "resolution_history.json"

MIN_DIMENSION = 16
MAX_DIMENSION = 16384
MAX_PRESETS = 14
MAX_HISTORY = 12
MAX_NAME_LENGTH = 32


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return fallback


def _is_dimension(value: Any) -> bool:
    return isinstance(value, int) and MIN_DIMENSION <= value <= MAX_DIMENSION


def _normalise_document(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Profile JSONが不正です")

    profiles: list[dict[str, Any]] = []
    names: set[str] = set()
    for item in raw.get("profiles", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()[:MAX_NAME_LENGTH]
        key = name.casefold()
        if not name or key in names:
            continue
        presets: list[dict[str, int]] = []
        pairs: set[tuple[int, int]] = set()
        for preset in item.get("presets", []):
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


def _load_profiles_document() -> dict[str, Any]:
    source = PROFILE_OVERRIDES_PATH if PROFILE_OVERRIDES_PATH.exists() else PROFILES_PATH
    try:
        return _normalise_document(_read_json(source, {}))
    except ValueError:
        return _normalise_document(_read_json(PROFILES_PATH, {}))


def _write_json_atomic(path: Path, value: Any, prefix: str) -> None:
    DATA_PATH.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=str(DATA_PATH))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _backup_current_profile_config() -> str:
    PROFILE_BACKUP_PATH.mkdir(parents=True, exist_ok=True)
    source = PROFILE_OVERRIDES_PATH if PROFILE_OVERRIDES_PATH.exists() else PROFILES_PATH
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = PROFILE_BACKUP_PATH / f"profiles-{stamp}.json"
    shutil.copy2(source, destination)
    backups = sorted(PROFILE_BACKUP_PATH.glob("profiles-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[20:]:
        old.unlink(missing_ok=True)
    return destination.name


def _save_profiles_document(raw: Any) -> dict[str, Any]:
    document = _normalise_document(raw)
    _backup_current_profile_config()
    _write_json_atomic(PROFILE_OVERRIDES_PATH, document, "profile-overrides-")
    return document


def _load_behavior() -> dict[str, bool]:
    raw = _read_json(BEHAVIOR_SETTINGS_PATH, {})
    return {
        "randomize_default": bool(raw.get("randomize_default", False)) if isinstance(raw, dict) else False,
        "randomize_user_presets": bool(raw.get("randomize_user_presets", False)) if isinstance(raw, dict) else False,
    }


def _save_behavior(raw: Any) -> dict[str, bool]:
    behavior = {
        "randomize_default": bool(raw.get("randomize_default", False)) if isinstance(raw, dict) else False,
        "randomize_user_presets": bool(raw.get("randomize_user_presets", False)) if isinstance(raw, dict) else False,
    }
    _write_json_atomic(BEHAVIOR_SETTINGS_PATH, behavior, "behavior-settings-")
    return behavior


def _load_history() -> list[dict[str, Any]]:
    raw = _read_json(HISTORY_PATH, [])
    if not isinstance(raw, list):
        return []
    return [
        item
        for item in raw[:MAX_HISTORY]
        if isinstance(item, dict) and _is_dimension(item.get("width")) and _is_dimension(item.get("height"))
    ]


def _list_backups() -> list[str]:
    if not PROFILE_BACKUP_PATH.exists():
        return []
    return [item.name for item in sorted(PROFILE_BACKUP_PATH.glob("profiles-*.json"), reverse=True)]


def _state() -> dict[str, Any]:
    return {
        "profiles": _load_profiles_document(),
        "behavior": _load_behavior(),
        "history": _load_history(),
        "backups": _list_backups(),
    }


def _response(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status)


async def _request_json(request: Request) -> dict[str, Any]:
    payload = await request.json()
    return payload if isinstance(payload, dict) else {}


def _register_routes(_demo, app):
    @app.get("/fnp-resolution-presets/settings/state")
    def get_state():
        return _response({"ok": True, "state": _state()})

    @app.post("/fnp-resolution-presets/settings/profiles")
    async def save_profiles(request: Request):
        try:
            document = _save_profiles_document(await _request_json(request))
            return _response({"ok": True, "message": "Profileを保存しました。Reload UIで反映してください。", "state": _state()})
        except (OSError, ValueError, TypeError) as error:
            return _response({"ok": False, "message": f"保存できません: {error}"}, 400)

    @app.post("/fnp-resolution-presets/settings/restore-defaults")
    def restore_defaults():
        try:
            backup = _backup_current_profile_config()
            PROFILE_OVERRIDES_PATH.unlink(missing_ok=True)
            return _response({"ok": True, "message": f"標準Profileへ戻しました。Backup: {backup}", "state": _state()})
        except OSError as error:
            return _response({"ok": False, "message": f"復元できません: {error}"}, 400)

    @app.post("/fnp-resolution-presets/settings/backup")
    def create_backup():
        try:
            backup = _backup_current_profile_config()
            return _response({"ok": True, "message": f"Backupを作成しました: {backup}", "state": _state()})
        except OSError as error:
            return _response({"ok": False, "message": f"Backupを作成できません: {error}"}, 400)

    @app.post("/fnp-resolution-presets/settings/restore-backup")
    async def restore_backup(request: Request):
        try:
            payload = await _request_json(request)
            name = Path(str(payload.get("name", ""))).name
            source = PROFILE_BACKUP_PATH / name
            if not name or source.parent != PROFILE_BACKUP_PATH or not source.exists():
                raise ValueError("Backupを選択してください")
            document = _normalise_document(_read_json(source, {}))
            _save_profiles_document(document)
            return _response({"ok": True, "message": "Backupを復元しました。Reload UIで反映してください。", "state": _state()})
        except (OSError, ValueError, TypeError) as error:
            return _response({"ok": False, "message": f"復元できません: {error}"}, 400)

    @app.post("/fnp-resolution-presets/settings/behavior")
    async def save_behavior(request: Request):
        try:
            behavior = _save_behavior(await _request_json(request))
            return _response({"ok": True, "message": "Randomize設定を保存しました。Reload UIで初期状態に反映します。", "behavior": behavior})
        except (OSError, ValueError, TypeError) as error:
            return _response({"ok": False, "message": f"保存できません: {error}"}, 400)

    @app.post("/fnp-resolution-presets/settings/history/clear")
    def clear_history():
        try:
            HISTORY_PATH.unlink(missing_ok=True)
            return _response({"ok": True, "message": "履歴を削除しました。", "state": _state()})
        except OSError as error:
            return _response({"ok": False, "message": f"履歴を削除できません: {error}"}, 400)


SETTINGS_HTML = r"""
<div class="fnp-settings-app">
  <div class="fnp-settings-status" id="fnp-settings-status">読み込み中...</div>

  <details open>
    <summary>Profile Editor</summary>
    <div class="fnp-settings-toolbar">
      <label>Profile <select id="fnp-settings-profile"></select></label>
      <button data-action="add-profile">Add profile</button>
      <button data-action="duplicate-profile">Duplicate</button>
      <button data-action="delete-profile">Delete</button>
      <button data-action="set-default">Set as default</button>
    </div>
    <div class="fnp-settings-hint">上から9件がMain row、10件目以降がMore Portraitに表示されます。ドラッグで順番を変更できます。</div>
    <div id="fnp-settings-presets"></div>
    <div class="fnp-settings-actions">
      <button data-action="add-preset">Add preset</button>
      <button data-action="save-profiles" class="primary">Save changes</button>
      <button data-action="restore-defaults">Restore defaults</button>
    </div>
  </details>

  <details open>
    <summary>Backup / Restore</summary>
    <div class="fnp-settings-toolbar">
      <button data-action="backup">Create backup</button>
      <select id="fnp-settings-backup"></select>
      <button data-action="restore-backup">Restore selected</button>
    </div>
    <div class="fnp-settings-hint">Profile変更前の状態はdata/profile_backups/へ保存されます。</div>
  </details>

  <details open>
    <summary>Randomize Settings</summary>
    <label class="fnp-settings-check"><input type="checkbox" id="fnp-settings-random-default"> 起動時にRandomizeをON</label>
    <label class="fnp-settings-check"><input type="checkbox" id="fnp-settings-random-custom"> Custom Presetも抽選対象にする</label>
    <div class="fnp-settings-actions"><button data-action="save-behavior" class="primary">Save Randomize settings</button></div>
  </details>

  <details open>
    <summary>Resolution History</summary>
    <div id="fnp-settings-history"></div>
    <div class="fnp-settings-actions"><button data-action="clear-history">Clear history</button></div>
  </details>

  <div class="fnp-settings-hint">Profile変更とRandomize初期状態は、Settings上部のReload UI後に反映されます。</div>
</div>
<script>
(() => {
  const root = document.currentScript?.parentElement;
  if (!root || root.dataset.fnpReady) return;
  root.dataset.fnpReady = "1";
  const api = (path, options = {}) => fetch(`/fnp-resolution-presets/settings/${path}`, {
    headers: {"Content-Type": "application/json"}, ...options
  }).then(async response => {
    const body = await response.json();
    if (!response.ok || !body.ok) throw new Error(body.message || "Request failed");
    return body;
  });
  const status = root.querySelector("#fnp-settings-status");
  const profileSelect = root.querySelector("#fnp-settings-profile");
  const presetList = root.querySelector("#fnp-settings-presets");
  const backupSelect = root.querySelector("#fnp-settings-backup");
  const historyList = root.querySelector("#fnp-settings-history");
  let state = null;
  let profileIndex = 0;
  let dragIndex = null;

  const setStatus = (message, error = false) => {
    status.textContent = message;
    status.classList.toggle("error", error);
  };
  const escape = value => String(value).replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
  const selectedProfile = () => state.profiles.profiles[profileIndex];

  function renderProfiles() {
    profileSelect.innerHTML = state.profiles.profiles.map((profile, index) => `<option value="${index}">${escape(profile.name)}${profile.name === state.profiles.default_profile ? " (default)" : ""}</option>`).join("");
    profileSelect.value = String(profileIndex);
    const profile = selectedProfile();
    presetList.innerHTML = profile.presets.map((preset, index) => `
      <div class="fnp-settings-preset-row" draggable="true" data-index="${index}">
        <span class="fnp-settings-drag" title="Drag to reorder">↕</span>
        <span class="fnp-settings-slot">${index < 9 ? "Main" : "More"} ${index + 1}</span>
        <input type="number" min="16" max="16384" step="8" data-field="width" value="${preset.width}">
        <span>×</span>
        <input type="number" min="16" max="16384" step="8" data-field="height" value="${preset.height}">
        <button data-action="duplicate-preset" data-index="${index}">Duplicate</button>
        <button data-action="delete-preset" data-index="${index}">Delete</button>
      </div>`).join("");
  }

  function renderBackups() {
    backupSelect.innerHTML = (state.backups || []).map(name => `<option value="${escape(name)}">${escape(name)}</option>`).join("");
  }

  function renderHistory() {
    historyList.innerHTML = state.history.length ? state.history.map(item => `
      <div class="fnp-settings-history-row"><strong>${item.width}×${item.height}</strong><span>${escape(item.profile || "")} · ${escape(item.tab || "")}</span><small>${escape(item.timestamp || "")}</small></div>`).join("") : "<div class=\"fnp-settings-empty\">履歴はありません</div>";
  }

  function render() {
    renderProfiles();
    renderBackups();
    renderHistory();
    root.querySelector("#fnp-settings-random-default").checked = state.behavior.randomize_default;
    root.querySelector("#fnp-settings-random-custom").checked = state.behavior.randomize_user_presets;
  }

  async function load() {
    try {
      const response = await api("state");
      state = response.state;
      profileIndex = Math.max(0, state.profiles.profiles.findIndex(profile => profile.name === state.profiles.default_profile));
      render();
      setStatus("準備完了");
    } catch (error) { setStatus(error.message, true); }
  }

  root.addEventListener("input", event => {
    const row = event.target.closest(".fnp-settings-preset-row");
    if (!row || !event.target.dataset.field) return;
    const value = Number(event.target.value);
    selectedProfile().presets[Number(row.dataset.index)][event.target.dataset.field] = value;
  });
  profileSelect.addEventListener("change", () => { profileIndex = Number(profileSelect.value); renderProfiles(); });
  presetList.addEventListener("dragstart", event => {
    const row = event.target.closest(".fnp-settings-preset-row");
    dragIndex = row ? Number(row.dataset.index) : null;
  });
  presetList.addEventListener("dragover", event => event.preventDefault());
  presetList.addEventListener("drop", event => {
    event.preventDefault();
    const row = event.target.closest(".fnp-settings-preset-row");
    if (!row || dragIndex === null) return;
    const targetIndex = Number(row.dataset.index);
    const presets = selectedProfile().presets;
    const [moved] = presets.splice(dragIndex, 1);
    presets.splice(targetIndex, 0, moved);
    dragIndex = null;
    renderProfiles();
  });

  root.addEventListener("click", async event => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const action = button.dataset.action;
    try {
      if (action === "add-profile") {
        const name = prompt("Profile name", "New Profile");
        if (!name) return;
        state.profiles.profiles.push({name: name.trim(), presets: [{width: 1024, height: 1024}]});
        profileIndex = state.profiles.profiles.length - 1;
        renderProfiles();
      } else if (action === "duplicate-profile") {
        const source = selectedProfile();
        state.profiles.profiles.splice(profileIndex + 1, 0, {name: `${source.name} Copy`, presets: source.presets.map(preset => ({...preset}))});
        profileIndex += 1;
        renderProfiles();
      } else if (action === "delete-profile") {
        if (state.profiles.profiles.length <= 1 || !confirm("このProfileを削除しますか？")) return;
        state.profiles.profiles.splice(profileIndex, 1);
        profileIndex = Math.min(profileIndex, state.profiles.profiles.length - 1);
        renderProfiles();
      } else if (action === "set-default") {
        state.profiles.default_profile = selectedProfile().name;
        renderProfiles();
        setStatus(`Defaultを${state.profiles.default_profile}に設定しました。Save changesで保存してください。`);
      } else if (action === "add-preset") {
        if (selectedProfile().presets.length >= 14) throw new Error("1 Profileあたり14件までです");
        selectedProfile().presets.push({width: 1024, height: 1024});
        renderProfiles();
      } else if (action === "duplicate-preset") {
        if (selectedProfile().presets.length >= 14) throw new Error("1 Profileあたり14件までです");
        const index = Number(button.dataset.index);
        selectedProfile().presets.splice(index + 1, 0, {...selectedProfile().presets[index]});
        renderProfiles();
      } else if (action === "delete-preset") {
        if (selectedProfile().presets.length <= 1) throw new Error("Profileには1件以上必要です");
        selectedProfile().presets.splice(Number(button.dataset.index), 1);
        renderProfiles();
      } else if (action === "save-profiles") {
        const response = await api("profiles", {method: "POST", body: JSON.stringify(state.profiles)});
        state = response.state;
        render();
        setStatus(response.message);
      } else if (action === "restore-defaults") {
        if (!confirm("標準Profileへ戻しますか？")) return;
        const response = await api("restore-defaults", {method: "POST"});
        state = response.state;
        profileIndex = 0;
        render();
        setStatus(response.message);
      } else if (action === "backup") {
        const response = await api("backup", {method: "POST"});
        state = response.state;
        renderBackups();
        setStatus(response.message);
      } else if (action === "restore-backup") {
        if (!backupSelect.value || !confirm("選択したBackupを復元しますか？")) return;
        const response = await api("restore-backup", {method: "POST", body: JSON.stringify({name: backupSelect.value})});
        state = response.state;
        render();
        setStatus(response.message);
      } else if (action === "save-behavior") {
        const response = await api("behavior", {method: "POST", body: JSON.stringify({
          randomize_default: root.querySelector("#fnp-settings-random-default").checked,
          randomize_user_presets: root.querySelector("#fnp-settings-random-custom").checked
        })});
        state.behavior = response.behavior;
        setStatus(response.message);
      } else if (action === "clear-history") {
        if (!confirm("履歴を削除しますか？")) return;
        const response = await api("history/clear", {method: "POST"});
        state = response.state;
        renderHistory();
        setStatus(response.message);
      }
    } catch (error) { setStatus(error.message, true); }
  });
  load();
})();
</script>
"""

SETTINGS_MARKUP = r"""
<div class="fnp-settings-app">
  <div class="fnp-settings-status" id="fnp-settings-status" aria-live="polite">読み込み中...</div>

  <details open class="fnp-settings-section fnp-settings-profile-section">
    <summary>Profile Editor</summary>
    <div class="fnp-settings-definition">Profile = a set of resolution presets.</div>
    <div class="fnp-settings-toolbar fnp-settings-profile-toolbar">
      <label>Profile <select id="fnp-settings-profile" aria-label="Profile"></select></label>
      <button type="button" data-action="add-profile">New profile</button>
      <button type="button" data-action="duplicate-profile">Duplicate profile</button>
      <button type="button" data-action="delete-profile" class="danger-outline">Delete profile</button>
      <button type="button" data-action="set-default">Make default</button>
    </div>
    <div class="fnp-settings-helper">Edit Width / Height directly. Drag ↕ to reorder. Changes apply after Save changes.</div>
    <div class="fnp-settings-helper">First 9 presets appear in Main row; the rest appear in More Portrait. Alt+↑／↓ also moves a focused row.</div>
    <div class="fnp-settings-column-head" aria-hidden="true"><span>Width × Height</span><span>Actions</span></div>
    <div id="fnp-settings-presets"></div>
    <div class="fnp-settings-profile-actions">
      <button type="button" data-action="add-preset">＋ Add preset</button>
      <div class="fnp-settings-save-group">
        <button type="button" data-action="save-profiles" class="primary">Save changes</button>
        <button type="button" data-action="restore-defaults" class="warning">Restore built-in profiles</button>
      </div>
    </div>
    <div class="fnp-settings-path">Built-in: profiles.json · Edited profiles: data/profile_overrides.json · Backups: data/profile_backups/</div>
  </details>

  <details open class="fnp-settings-section">
    <summary>Backup / Restore</summary>
    <div class="fnp-settings-toolbar fnp-settings-backup-row">
      <button type="button" data-action="backup">Create backup</button>
      <select id="fnp-settings-backup" aria-label="Profile backup"></select>
      <button type="button" data-action="restore-backup" class="warning">Restore selected</button>
    </div>
    <div class="fnp-settings-helper">Save changes automatically creates a backup before writing the edited Profile.</div>
  </details>

  <details open class="fnp-settings-section">
    <summary>Randomize Settings</summary>
    <label class="fnp-settings-check"><input type="checkbox" id="fnp-settings-random-default"> Start Randomize ON</label>
    <label class="fnp-settings-check"><input type="checkbox" id="fnp-settings-random-custom"> Include custom presets</label>
    <div class="fnp-settings-actions"><button type="button" data-action="save-behavior" class="primary">Save Randomize settings</button></div>
  </details>

  <details open class="fnp-settings-section">
    <summary>Resolution History</summary>
    <div id="fnp-settings-history"></div>
    <div class="fnp-settings-actions"><button type="button" data-action="clear-history" class="danger-outline">Clear history</button></div>
  </details>

  <div class="fnp-settings-dialog" id="fnp-settings-profile-dialog" role="dialog" aria-modal="true" aria-labelledby="fnp-settings-profile-dialog-title" hidden>
    <div class="fnp-settings-dialog-panel">
      <h3 id="fnp-settings-profile-dialog-title">New profile</h3>
      <label>Profile name <input id="fnp-settings-profile-name" type="text" maxlength="32" autocomplete="off" placeholder="e.g. SDXL Custom"></label>
      <div class="fnp-settings-dialog-error" id="fnp-settings-profile-dialog-error" role="alert"></div>
      <div class="fnp-settings-dialog-actions">
        <button type="button" data-action="cancel-profile-dialog">Cancel</button>
        <button type="button" data-action="create-profile" class="primary">Create profile</button>
      </div>
    </div>
  </div>

  <div class="fnp-settings-path">Profile changes and Randomize defaults take effect after Reload UI.</div>
</div>
"""


def _settings_component(**kwargs):
    kwargs.pop("label", None)
    kwargs.pop("value", None)
    kwargs.pop("elem_id", None)
    return gr.HTML(
        SETTINGS_MARKUP,
        elem_id="fnp_settings_editor",
        **kwargs,
    )


def on_ui_settings():
    option = shared.OptionInfo(
        SETTINGS_MARKUP,
        "",
        component=_settings_component,
        section=("fnp_resolution_presets", "Resolution Presets"),
        category_id="extensions",
    )
    option.do_not_save = True
    shared.opts.add_option("fnp_resolution_presets_editor", option)


script_callbacks.on_ui_settings(on_ui_settings)
script_callbacks.on_app_started(_register_routes)
