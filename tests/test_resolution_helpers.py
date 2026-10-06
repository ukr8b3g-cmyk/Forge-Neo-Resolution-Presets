from __future__ import annotations

import importlib.util
import json
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


class ProfileCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_extension_module()
        _, cls.profiles, _ = cls.mod._load_profiles()

    def effective(self, pair, step=64, minimum=64, maximum=2048):
        return self.mod._effective_preset(*pair, minimum, maximum, step)

    def notice(self, values, step=64, minimum=64, maximum=2048, name="Krea2"):
        return self.mod._profile_compatibility_html(name, values, minimum, maximum, step)

    def test_krea2_all_enabled_at_64_32_16_with_expected_adjustment_counts(self):
        values = self.profiles["Krea2"]
        for step, adjusted in ((64, 7), (32, 1), (16, 0)):
            with self.subTest(step=step):
                effective = [self.effective(pair, step) for pair in values]
                self.assertNotIn(None, effective)
                self.assertEqual(sum(a != b for a, b in zip(values, effective)), adjusted)
                self.assertTrue(all(self.mod._is_step_compatible(*pair, 64, 2048, step) for pair in effective))
                notice = self.notice(values, step)
                if adjusted:
                    self.assertIn(f"{adjusted} of 11 presets adjusted", notice)
                    self.assertIn(f"Active Resolution Step: {step}", notice)
                    self.assertIn("Settings → System → Resolution Step", notice)
                    self.assertIn("set it to 16 → Apply settings → fully restart the WebUI", notice)
                    self.assertIn("Reload UI alone does not update", notice)
                    self.assertEqual(notice.count("<li>"), adjusted)
                else:
                    self.assertEqual(notice, "")

    def test_nearest_rounding_and_ties_upward(self):
        self.assertEqual(self.effective((720, 1280)), (704, 1280))
        self.assertEqual(self.effective((720, 1280), 32), (736, 1280))
        self.assertEqual(self.effective((928, 1152)), (960, 1152))
        self.assertEqual(self.effective((896, 1184)), (896, 1216))
        self.assertEqual(self.effective((1024, 1536)), (1024, 1536))

    def test_all_shipped_profiles_available_at_64_and_exact_at_16(self):
        for name, values in self.profiles.items():
            with self.subTest(profile=name):
                self.assertTrue(all(self.effective(pair) is not None for pair in values))
                self.assertEqual(self.notice(values, 16, name=name), "")

    def test_details_include_collapsed_more_portrait(self):
        for name in ("Anima", "SDXL", "Flux"):
            values = self.profiles[name]
            self.assertIn(f"4 of {len(values)} presets adjusted", self.notice(values, name=name))
        self.assertIn("720×1280 → 704×1280", self.notice(self.profiles["Krea2"]))

    def test_out_of_range_requests_are_not_clamped_into_range(self):
        for pair in ((32, 1024), (1024, 2112), (1040, 1024)):
            self.assertIsNone(self.effective(pair, maximum=1024))
        notice = self.notice([(1024, 1024), (2048, 2048)], maximum=1536)
        self.assertIn("1 unavailable", notice)
        self.assertIn("1 outside the active Width/Height range 64–1536", notice)
        self.assertIn("Changing Resolution Step will not fix out-of-range sizes", notice)
        self.assertNotIn("set it to 16", notice)

    def test_range_edges_choose_nearest_valid_grid_only_within_cap(self):
        self.assertEqual(self.effective((64, 2048)), (64, 2048))
        self.assertIsNone(self.effective((992, 1024), maximum=1020))
        self.assertEqual(self.effective((992, 992), maximum=1000), (960, 960))
        self.assertEqual(self.effective((992, 992), minimum=990), (1024, 1024))
        self.assertIsNone(self.effective((1000, 1000), minimum=990, maximum=1010))
        self.assertIsNone(self.effective((64, 1024), 256))

    def test_five_percent_cap_is_inclusive_and_applies_per_dimension(self):
        # Arbitrary native steps are supported; 608 is exactly 5% below 640.
        self.assertEqual(self.effective((640, 640), 608), (608, 608))
        self.assertIsNone(self.effective((648, 640), 608))
        self.assertIsNone(self.effective((640, 648), 608))
        notice = self.notice([(608, 1024)])
        self.assertIn("no in-range Step 64 size within 5% per dimension", notice)
        self.assertIn("1 unavailable", notice)

    def test_rotation_uses_the_same_effective_size(self):
        for pair in self.profiles["Krea2"]:
            effective = self.effective(pair)
            self.assertEqual(self.effective(pair[::-1]), effective[::-1])
            self.assertEqual(self.mod._preset_button_variant(*effective, *effective), "primary")
            if effective[0] != effective[1]:
                self.assertEqual(self.mod._preset_button_variant(*effective, *effective[::-1]), "stop")

    def test_edited_profile_recommends_8_when_16_is_insufficient(self):
        notice = self.notice([(1000, 1000)], name="Edited")
        self.assertIn("set it to 8", notice)
        self.assertEqual(self.notice([(1000, 1000)], 8), "")

    def test_details_are_accessible_and_profile_name_is_escaped(self):
        notice = self.notice([(720, 1280)], name='<script>alert("profile")</script>')
        self.assertIn('role="status" aria-live="polite"', notice)
        self.assertIn("<details><summary>Preset adjustment / unavailable details</summary>", notice)
        self.assertIn("720×1280 → 704×1280", notice)
        self.assertNotIn("<script>", notice)
        self.assertIn("&lt;script&gt;", notice)
        self.assertEqual(self.notice([]), "")

    def test_randomize_uses_same_effective_sizes_and_active_ui_constraints(self):
        self.mod.shared.opts.res_step = 16  # Saved setting may not be active yet.
        for step in (64, 32, 16):
            with self.subTest(step=step):
                process = types.SimpleNamespace(width=512, height=512)
                with patch.object(self.mod, "_load_behavior_settings", return_value={"randomize_user_presets": False}), patch.object(self.mod.random, "choice", side_effect=lambda choices: choices[-1]) as choose:
                    self.mod.ForgeNeoResolutionPresets().before_process(process, True, "Krea2", (64, 2048, step))
                candidates = choose.call_args.args[0]
                self.assertEqual(candidates, [self.effective(pair, step) for pair in self.profiles["Krea2"]])
                self.assertIn((process.width, process.height), candidates)

    def test_randomize_excludes_unsupported_and_deduplicates_adjusted_sizes(self):
        profiles = (["Edited"], {"Edited": [(928, 1152), (960, 1152), (32, 1024), (608, 1024)]}, "Edited")
        process = types.SimpleNamespace(width=1024, height=1024)
        with patch.object(self.mod, "_load_profiles", return_value=profiles), patch.object(self.mod, "_load_behavior_settings", return_value={"randomize_user_presets": True}), patch.object(self.mod, "_load_user_presets", return_value=[{"name": "Custom", "width": 720, "height": 1280}]), patch.object(self.mod.random, "choice", side_effect=lambda choices: choices[0]) as choose:
            self.mod.ForgeNeoResolutionPresets().before_process(process, True, "Edited", (64, 2048, 64))
        self.assertEqual(choose.call_args.args[0], [(960, 1152), (704, 1280)])

    def test_randomize_with_no_compatible_sizes_leaves_resolution_unchanged(self):
        process = types.SimpleNamespace(width=1024, height=1024)
        with patch.object(self.mod, "_load_profiles", return_value=(["Edited"], {"Edited": [(64, 1280)]}, "Edited")), patch.object(self.mod, "_load_behavior_settings", return_value={"randomize_user_presets": False}), patch.object(self.mod.random, "choice") as choose:
            self.mod.ForgeNeoResolutionPresets().before_process(process, True, "Edited", (64, 2048, 256))
        choose.assert_not_called()
        self.assertEqual((process.width, process.height), (1024, 1024))


class RepositoryRegressionTests(unittest.TestCase):
    def test_settings_distinguish_configured_step_from_active_sliders(self):
        source = (ROOT / "javascript" / "forge_neo_resolution_presets_settings.js").read_text(encoding="utf-8")
        self.assertIn("Configured Resolution Step:", source)
        self.assertIn("requested → applied sizes (up to 5% per dimension)", source)
        self.assertNotIn("are off-step and are disabled", source)

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
