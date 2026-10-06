from __future__ import annotations

import importlib.util
import json
import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


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
        self.mod.shared.opts.res_step = 16  # Saved setting is not the active slider step.
        slider = types.SimpleNamespace(minimum=64, maximum=2048, step=64)
        self.assertEqual(self.mod._native_constraints(slider, slider), (64, 2048, 64))

    def test_step_alignment_does_not_determine_preset_availability(self):
        self.assertTrue(self.mod._is_step_compatible(1024, 1344, 64, 2048, 64))
        self.assertFalse(self.mod._is_step_compatible(1136, 1424, 64, 2048, 64))
        self.assertTrue(self.mod._is_step_compatible(1136, 1424, 64, 2048, 16))
        self.assertEqual(self.mod._exact_preset(1136, 1424, 64, 2048), (1136, 1424))

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

    def test_current_info_reports_exact_dimensions_without_step_warning(self):
        info = self.mod._current_info(1136, 1424)
        self.assertIn("1136×1424", info)
        self.assertNotIn("off-step", info)


class ExactPresetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_extension_module()
        _, cls.profiles, _ = cls.mod._load_profiles()

    def test_all_profiles_preserve_original_sizes_at_every_native_step(self):
        for step in (8, 16, 32, 64, 128, 256):
            self.mod.shared.opts.res_step = step
            for name, values in self.profiles.items():
                with self.subTest(step=step, profile=name):
                    actual = [self.mod._exact_preset(w, h, 64, 2048) for w, h in values]
                    self.assertEqual(actual, values)

    def test_off_step_dimensions_are_never_rounded(self):
        for pair in ((928, 1152), (896, 1184), (832, 1248), (768, 1376), (672, 1568), (864, 1152), (720, 1280), (608, 1024)):
            with self.subTest(pair=pair):
                self.assertEqual(self.mod._exact_preset(*pair, 64, 2048), pair)
                self.assertEqual(self.mod._exact_preset(*pair[::-1], 64, 2048), pair[::-1])

    def test_native_range_limits_remain_enforced_without_clamping(self):
        for pair in ((32, 1024), (1024, 2112), (16384, 1024)):
            self.assertIsNone(self.mod._exact_preset(*pair, 64, 2048))
        self.assertEqual(self.mod._exact_preset(64, 2048, 64, 2048), (64, 2048))
        self.assertEqual(self.mod._exact_preset(992, 992, 990, 1000), (992, 992))
        self.assertIsNone(self.mod._exact_preset(1024, 1024, 1050, 1000))

    def test_invalid_dimensions_are_not_enabled(self):
        for pair in ((0, 1024), (1023, 1024), ("invalid", 1024), (None, 1024)):
            self.assertIsNone(self.mod._exact_preset(*pair, 64, 2048))

    def test_randomize_uses_exact_sizes_with_native_ui_range(self):
        self.mod.shared.opts.res_step = 16
        for step in (64, 32, 16):
            with self.subTest(step=step):
                process = types.SimpleNamespace(width=512, height=512)
                with patch.object(self.mod, "_load_behavior_settings", return_value={"randomize_user_presets": False}), patch.object(self.mod.random, "choice", side_effect=lambda choices: choices[-1]) as choose:
                    self.mod.ForgeNeoResolutionPresets().before_process(process, True, "Krea2", (64, 2048, step))
                self.assertEqual(choose.call_args.args[0], self.profiles["Krea2"])
                self.assertEqual((process.width, process.height), (720, 1280))

    def test_randomize_excludes_range_violations_but_keeps_off_step_and_custom(self):
        profiles = (["Edited"], {"Edited": [(928, 1152), (960, 1152), (32, 1024), (2048, 2048)]}, "Edited")
        process = types.SimpleNamespace(width=1024, height=1024)
        with patch.object(self.mod, "_load_profiles", return_value=profiles), patch.object(self.mod, "_load_behavior_settings", return_value={"randomize_user_presets": True}), patch.object(self.mod, "_load_user_presets", return_value=[{"name": "Custom", "width": 720, "height": 1280}]), patch.object(self.mod.random, "choice", side_effect=lambda choices: choices[0]) as choose:
            self.mod.ForgeNeoResolutionPresets().before_process(process, True, "Edited", (64, 1536, 64))
        self.assertEqual(choose.call_args.args[0], [(928, 1152), (960, 1152), (720, 1280)])

    def test_randomize_with_no_in_range_sizes_leaves_resolution_unchanged(self):
        process = types.SimpleNamespace(width=1024, height=1024)
        with patch.object(self.mod, "_load_profiles", return_value=(["Edited"], {"Edited": [(4096, 4096)]}, "Edited")), patch.object(self.mod, "_load_behavior_settings", return_value={"randomize_user_presets": False}), patch.object(self.mod.random, "choice") as choose:
            self.mod.ForgeNeoResolutionPresets().before_process(process, True, "Edited", (64, 2048, 64))
        choose.assert_not_called()
        self.assertEqual((process.width, process.height), (1024, 1024))

    def test_randomize_disabled_preserves_existing_exact_values(self):
        process = types.SimpleNamespace(width=928, height=1152)
        self.mod.ForgeNeoResolutionPresets().before_process(process, False, "Krea2", (64, 2048, 64))
        self.assertEqual((process.width, process.height), (928, 1152))


class RepositoryRegressionTests(unittest.TestCase):
    def test_preset_layout_wraps_without_fixed_height_or_portrait_grouping(self):
        css = (ROOT / "style.css").read_text(encoding="utf-8")
        for tab in ("txt2img", "img2img"):
            selector = f"#fnp__{tab}_container .fnp__preset_row"
            rules = [body for selectors, body in re.findall(r"([^{}]+)\{([^{}]+)\}", css)
                     if selector in [item.strip() for item in selectors.split(",")]]
            declarations = "\n".join(rules)
            self.assertIn("flex-wrap: wrap", declarations)
            self.assertIn("column-gap: 6px !important", declarations)
            self.assertIn("row-gap: 4px !important", declarations)
            self.assertNotIn("height:", declarations)
        for path in (
            MODULE_PATH,
            ROOT / "scripts" / "forge_neo_resolution_presets_settings.py",
            ROOT / "javascript" / "forge_neo_resolution_presets_settings.js",
            ROOT / "style.css",
        ):
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                for obsolete in ("More Portrait", "Less Portrait", "fnp__more_button", "fnp__extended_row"):
                    self.assertNotIn(obsolete, source)

    def test_no_adjustment_labels_or_warning_panel_remain(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("_profile_compatibility_html", source)
        self.assertNotIn("_effective_preset", source)
        self.assertNotIn("fnp__compatibility_notice", source)
        self.assertNotIn("MAX_PRESET_ADJUSTMENT_PERCENT", source)
        settings = (ROOT / "javascript" / "forge_neo_resolution_presets_settings.js").read_text(encoding="utf-8")
        self.assertIn("Preset dimensions are applied exactly", settings)
        self.assertNotIn("are off-step and are disabled", settings)
        self.assertNotIn("requested → applied", settings)

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
