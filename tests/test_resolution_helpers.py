from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "forge_neo_resolution_presets.py"


def load_extension_module():
    fake_gradio = types.ModuleType("gradio")
    fake_gradio.update = lambda **kwargs: kwargs
    sys.modules["gradio"] = fake_gradio

    modules_package = types.ModuleType("modules")
    modules_package.__path__ = []

    scripts_module = types.ModuleType("modules.scripts")

    class Script:
        pass

    scripts_module.Script = Script
    scripts_module.AlwaysVisible = object()
    scripts_module.basedir = lambda: str(ROOT)

    shared_module = types.ModuleType("modules.shared")
    shared_module.opts = types.SimpleNamespace(res_step=64)

    modules_package.scripts = scripts_module
    modules_package.shared = shared_module
    sys.modules["modules"] = modules_package
    sys.modules["modules.scripts"] = scripts_module
    sys.modules["modules.shared"] = shared_module

    spec = importlib.util.spec_from_file_location("fnp_resolution_presets_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ResolutionHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_extension_module()

    def test_resolution_step_reads_host_setting(self):
        self.mod.shared.opts.res_step = 64
        self.assertEqual(self.mod._resolution_step(), 64)
        self.mod.shared.opts.res_step = 16
        self.assertEqual(self.mod._resolution_step(), 16)

    def test_native_constraints_prefer_component_values(self):
        slider = types.SimpleNamespace(minimum=64, maximum=2048, step=64)
        self.assertEqual(self.mod._native_constraints(slider, slider), (64, 2048, 64))

    def test_step_compatibility_blocks_off_step_presets(self):
        self.assertTrue(self.mod._is_step_compatible(1024, 1344, 64, 2048, 64))
        self.assertFalse(self.mod._is_step_compatible(1136, 1424, 64, 2048, 64))
        self.assertTrue(self.mod._is_step_compatible(1136, 1424, 64, 2048, 16))

    def test_rounding_choices_follow_native_step(self):
        self.assertEqual(self.mod._rounding_choices(64), [64, 128, 256])
        self.assertEqual(self.mod._rounding_choices(16), [16, 32, 64, 128, 256])

    def test_ratio_result_is_clamped_and_aligned(self):
        width, height = self.mod._calculate_dimensions(2048, 2048, "16:9", 64, 64, 2048)
        self.assertGreaterEqual(width, 64)
        self.assertGreaterEqual(height, 64)
        self.assertLessEqual(width, 2048)
        self.assertLessEqual(height, 2048)
        self.assertEqual(width % 64, 0)
        self.assertEqual(height % 64, 0)

    def test_current_info_reports_off_step(self):
        info = self.mod._current_info(1136, 1424, 64)
        self.assertIn("Step 64 off-step", info)


class RepositoryRegressionTests(unittest.TestCase):
    def test_settings_inline_legacy_block_is_removed(self):
        source = (ROOT / "scripts" / "forge_neo_resolution_presets_settings.py").read_text(encoding="utf-8")
        self.assertNotIn('SETTINGS_HTML = r"""', source)
        self.assertIn('"resolution_step": _resolution_step()', source)

    def test_all_shipped_presets_work_at_step_16(self):
        data = json.loads((ROOT / "profiles.json").read_text(encoding="utf-8"))
        pairs = [
            (preset["width"], preset["height"])
            for profile in data["profiles"]
            for preset in profile["presets"]
        ]
        self.assertTrue(all(width % 16 == 0 and height % 16 == 0 for width, height in pairs))
        self.assertTrue(any(width % 64 != 0 or height % 64 != 0 for width, height in pairs))


if __name__ == "__main__":
    unittest.main()
