"""Settings save/restore handlers with real temporary-file persistence.

Forge, Gradio and HTTP response construction are stubbed; normalization,
backups, atomic writes and route bodies are the unmodified product functions.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def document(*names):
    return {"default_profile": names[0], "profiles": [
        {"name": name, "presets": [{"width": 1024, "height": 1024}]} for name in names
    ]}


class SettingsSaveTests(unittest.TestCase):
    def setUp(self):
        modules = types.ModuleType("modules")
        modules.shared = types.SimpleNamespace(opts=types.SimpleNamespace(res_step=8))
        modules.script_callbacks = types.SimpleNamespace(
            on_ui_settings=lambda f: None, on_app_started=lambda f: None)
        fastapi = types.ModuleType("fastapi")
        fastapi.Request = object
        responses = types.ModuleType("starlette.responses")
        responses.JSONResponse = lambda payload, status_code=200: (status_code, payload)
        stubs = {"modules": modules, "gradio": types.ModuleType("gradio"),
                 "fastapi": fastapi, "starlette.responses": responses}
        with patch.dict(sys.modules, stubs):
            spec = importlib.util.spec_from_file_location(
                "fnp_settings_test", ROOT / "scripts/forge_neo_resolution_presets_settings.py")
            self.mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.mod)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.mod.DATA_PATH = self.root / "data"
        self.mod.PROFILES_PATH = self.root / "profiles.json"
        self.mod.PROFILE_OVERRIDES_PATH = self.mod.DATA_PATH / "profile_overrides.json"
        self.mod.PROFILE_BACKUP_PATH = self.mod.DATA_PATH / "profile_backups"
        self.mod.BEHAVIOR_SETTINGS_PATH = self.mod.DATA_PATH / "behavior_settings.json"
        self.mod.HISTORY_PATH = self.mod.DATA_PATH / "resolution_history.json"
        self.mod.DATA_PATH.mkdir()
        self.original = document("Original")
        self.mod.PROFILES_PATH.write_text(json.dumps(self.original), encoding="utf-8")
        self.mod.PROFILE_OVERRIDES_PATH.write_text(json.dumps(self.original), encoding="utf-8")
        self.mod.BEHAVIOR_SETTINGS_PATH.write_text('{"randomize_default":true}', encoding="utf-8")
        self.mod.HISTORY_PATH.write_text('[{"width":512,"height":512}]', encoding="utf-8")
        self.routes = {}

        def route(path):
            def register(fn):
                self.routes[path.rsplit("/settings/", 1)[-1]] = fn
                return fn
            return register

        self.mod._register_routes(None, types.SimpleNamespace(get=route, post=route))

    def call(self, route, payload):
        async def request_json():
            return payload
        return asyncio.run(self.routes[route](types.SimpleNamespace(json=request_json)))

    def files(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in self.root.rglob("*") if p.is_file()}

    def test_unicode_collision_rejects_entire_save_before_backup_or_write(self):
        for names in [("Strasse", "Straße"), ("SS", "ß"), ("Σ", "ς"), ("Test", "test")]:
            with self.subTest(names=names):
                before = self.files()
                status, body = self.call("profiles", document(*names))
                self.assertEqual(status, 400)
                self.assertFalse(body["ok"])
                self.assertIn("重複", body["message"])
                self.assertEqual(self.files(), before)

    def test_valid_unicode_profiles_roundtrip_with_existing_data_protected(self):
        before = self.files()
        payload = document("日本語", "😀" * 32, "Straße")
        status, body = self.call("profiles", payload)
        self.assertEqual(status, 200)
        self.assertEqual(body["state"]["profiles"], payload)
        self.assertEqual(json.loads(self.mod.PROFILE_OVERRIDES_PATH.read_text(encoding="utf-8")), payload)
        backups = list(self.mod.PROFILE_BACKUP_PATH.glob("*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), before["data/profile_overrides.json"])
        for name in ["profiles.json", "data/behavior_settings.json", "data/resolution_history.json"]:
            self.assertEqual(self.files()[name], before[name])

    def test_long_names_rejected_without_truncation_or_partial_write(self):
        for name in ["A" * 33, "😀" * 33, "Original" + " " * 25 + "other"]:
            with self.subTest(name=name):
                before = self.files()
                status, body = self.call("profiles", document("Good", name))
                self.assertEqual(status, 400)
                self.assertIn("32", body["message"])
                self.assertEqual(self.files(), before)

    def test_colliding_backup_rejected_without_modifying_any_file(self):
        self.mod.PROFILE_BACKUP_PATH.mkdir()
        backup = self.mod.PROFILE_BACKUP_PATH / "profiles-unicode.json"
        backup.write_text(json.dumps(document("Strasse", "Straße")), encoding="utf-8")
        before = self.files()
        status, body = self.call("restore-backup", {"name": backup.name})
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertEqual(self.files(), before)

    def test_shipped_profiles_keep_all_fifteen_moss_presets(self):
        payload = json.loads((ROOT / "profiles.json").read_text(encoding="utf-8"))
        status, body = self.call("profiles", payload)
        self.assertEqual(status, 200)
        self.assertEqual(body["state"]["profiles"], payload)
        self.assertEqual(len(payload["profiles"][-1]["presets"]), 15)

    def test_io_failure_keeps_original_file_and_removes_temporary_file(self):
        before = self.files()
        with patch.object(self.mod.os, "replace", side_effect=OSError("simulated write failure")):
            status, body = self.call("profiles", document("New"))
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        for name, value in before.items():
            self.assertEqual(self.files()[name], value)
        self.assertFalse(list(self.mod.DATA_PATH.glob("*.tmp")))
        self.assertEqual(len(list(self.mod.PROFILE_BACKUP_PATH.glob("*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
