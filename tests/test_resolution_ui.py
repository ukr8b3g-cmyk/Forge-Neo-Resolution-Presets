"""Exercise UI construction and callback wiring without a Forge/Gradio install."""
from __future__ import annotations

import unittest
import types
from unittest.mock import patch

from test_resolution_helpers import load_extension_module


class Component:
    def __init__(self, kind, value=None, **kwargs):
        self.kind = kind
        self.value = value
        self.visible = True
        self.interactive = True
        self.elem_classes = []
        self.events = {}
        self.__dict__.update(kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def click(self, fn=None, **kwargs):
        self.events.setdefault("click", []).append((fn, kwargs))

    def change(self, fn=None, **kwargs):
        self.events.setdefault("change", []).append((fn, kwargs))

    def input(self, fn=None, **kwargs):
        self.events.setdefault("input", []).append((fn, kwargs))

    def release(self, fn=None, **kwargs):
        self.events.setdefault("release", []).append((fn, kwargs))

    def trigger(self, event):
        for fn, kwargs in self.events[event]:
            result = fn(*(component.value for component in kwargs.get("inputs", [])))
            outputs = kwargs.get("outputs", [])
            if len(outputs) == 1:
                result = [result]
            if len(result) != len(outputs):
                raise AssertionError("Callback output count does not match component wiring")
            for component, value in zip(outputs, result):
                if isinstance(value, dict):
                    component.__dict__.update(value)
                else:
                    component.value = value


class ResolutionUITests(unittest.TestCase):
    def setUp(self):
        self.mod = load_extension_module()
        self.components = []
        for name in ("Accordion", "Button", "Column", "Dropdown", "File", "HTML", "Markdown", "Row", "State", "Textbox", "UploadButton"):
            def factory(*args, kind=name, **kwargs):
                component = Component(kind, *args, **kwargs)
                self.components.append(component)
                return component
            setattr(self.mod.gr, name, factory)
        _, self.profiles, _ = self.mod._load_profiles()
        self.profiles["Compatible"] = [(1024, 1024)]
        for target, value in (
            ("_load_profiles", (list(self.profiles), self.profiles, "Krea2")),
            ("_load_last_profile", "Krea2"),
            ("_load_user_presets", []),
            ("_load_behavior_settings", {"randomize_default": False, "randomize_user_presets": False}),
            ("_save_last_profile", None),
            ("_record_resolution_history", None),
        ):
            patcher = patch.object(self.mod, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def build_ui(self, is_img2img=False, step=64, maximum=2048):
        self.components.clear()
        self.mod.shared.opts.res_step = 16
        script = self.mod.ForgeNeoResolutionPresets()
        self.width = Component("Slider", 1024, minimum=64, maximum=maximum, step=step)
        self.height = Component("Slider", 1024, minimum=64, maximum=maximum, step=step)
        tab = "img2img" if is_img2img else "txt2img"
        script.after_component(self.width, elem_id=f"{tab}_width")
        script.after_component(self.height, elem_id=f"{tab}_height")
        self.script = script
        self.script_args = script.ui(is_img2img)
        self.profile = self.by_class("fnp__profile")[0]
        self.notice = self.by_class("fnp__compatibility_notice")[0]

    def by_class(self, name):
        return [component for component in self.components if name in component.elem_classes]

    def test_both_tabs_show_native_step_and_enable_all_krea2_sizes(self):
        for tab in (False, True):
            for step, adjusted in ((64, 7), (32, 1), (16, 0)):
                with self.subTest(img2img=tab, step=step):
                    self.build_ui(tab, step)
                    buttons = [button for button in self.by_class("fnp__preset_button") if button.visible]
                    self.assertEqual(len(buttons), 11)
                    self.assertEqual(sum(button.interactive for button in buttons), 11)
                    self.assertEqual(self.notice.visible, adjusted != 0)
                    if adjusted:
                        self.assertIn(f"Active Resolution Step: {step}", self.notice.value)
                        self.assertEqual(self.notice.value.count("<li>"), adjusted)

    def test_profile_changes_update_and_clear_notice_without_changing_resolution(self):
        for tab in (False, True):
            with self.subTest(img2img=tab):
                self.build_ui(tab)
                for selected, count in (("Compatible", 0), ("Anima", 4), ("Krea2", 7), ("Compatible", 0)):
                    self.profile.value = selected
                    self.profile.trigger("change")
                    self.assertEqual(self.notice.visible, count != 0)
                    self.assertEqual(self.notice.value.count("<li>"), count)
                    if count:
                        self.assertIn(f"{selected}: {count} of", self.notice.value)
                    else:
                        self.assertEqual(self.notice.value, "")
                    self.assertEqual((self.width.value, self.height.value), (1024, 1024))

    def test_range_notice_matches_disabled_buttons_even_at_step_16(self):
        self.build_ui(step=16, maximum=1536)
        buttons = [button for button in self.by_class("fnp__preset_button") if button.visible]
        self.assertEqual(sum(not button.interactive for button in buttons), 2)
        self.assertIn("2 unavailable", self.notice.value)
        self.assertIn("2 outside the active Width/Height range 64–1536", self.notice.value)
        self.assertNotIn("off-step", self.notice.value)

    def test_adjusted_orientation_and_dimension_changes_preserve_notice(self):
        self.build_ui()
        notice = self.notice.value
        button = next(button for button in self.by_class("fnp__preset_button") if button.value == "928×1152 → 960×1152")
        button.trigger("click")
        self.assertEqual((self.width.value, self.height.value), (960, 1152))
        self.assertEqual(button.variant, "primary")
        self.assertIn("960×1152", self.by_class("fnp__current_info")[0].value)
        button.trigger("click")
        self.assertEqual((self.width.value, self.height.value), (1152, 960))
        self.assertEqual(button.variant, "stop")
        button.trigger("click")
        self.assertEqual((self.width.value, self.height.value), (960, 1152))
        self.width.trigger("change")
        self.assertEqual(self.notice.value, notice)
        self.assertTrue(self.notice.visible)
        self.assertEqual(sum(button.visible and not button.interactive for button in self.by_class("fnp__preset_button")), 0)

    def test_randomize_receives_active_slider_constraints_from_ui(self):
        self.build_ui()
        self.assertEqual(len(self.script_args), 3)
        self.assertEqual(self.script_args[2].value, (64, 2048, 64))
        self.script_args[0].value = True
        process = types.SimpleNamespace(width=512, height=512)
        with patch.object(self.mod.random, "choice", side_effect=lambda values: values[-1]):
            self.script.before_process(process, *(component.value for component in self.script_args))
        self.assertEqual((process.width, process.height), (704, 1280))

    def test_user_preset_initial_click_and_refresh_use_active_adjustment(self):
        custom = [{"name": "Portrait", "width": 720, "height": 1280}]
        with patch.object(self.mod, "_load_user_presets", return_value=custom):
            self.build_ui()
            button = self.by_class("fnp__user_button")[0]
            self.assertEqual(button.value, "Portrait (720×1280 → 704×1280)")
            self.assertTrue(button.interactive)
            button.trigger("click")
            self.assertEqual((self.width.value, self.height.value), (704, 1280))
            self.assertEqual(button.variant, "primary")
            self.width.trigger("change")
            self.assertEqual(button.value, "Portrait (720×1280 → 704×1280)")
            # Management refreshes must not revert to the saved-but-inactive Step 16.
            updates = self.mod._refresh_user_controls(None, [], [], [], [], current_width=704, current_height=1280, native_constraints=(64, 2048, 64))
            self.assertEqual(updates[1]["value"], button.value)
            self.assertTrue(updates[1]["interactive"])
            self.assertEqual(updates[1]["variant"], "primary")

    def test_reset_uses_adjusted_first_preset_and_unsupported_click_does_nothing(self):
        self.profiles["Krea2"] = [(928, 1152), (608, 1024)]
        self.build_ui()
        self.by_class("fnp__reset_button")[0].trigger("click")
        self.assertEqual((self.width.value, self.height.value), (960, 1152))
        blocked = self.by_class("fnp__preset_button")[1]
        self.assertFalse(blocked.interactive)
        blocked.trigger("click")
        self.assertEqual((self.width.value, self.height.value), (960, 1152))


if __name__ == "__main__":
    unittest.main()
