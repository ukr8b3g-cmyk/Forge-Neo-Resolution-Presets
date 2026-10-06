"""Exercise UI construction and callback wiring without a Forge/Gradio install."""
from __future__ import annotations

import unittest
import types
from unittest.mock import patch

from test_resolution_helpers import load_extension_module


class Component:
    context_stack = []

    def __init__(self, kind, value=None, **kwargs):
        self.kind = kind
        self.value = value
        self.visible = True
        self.interactive = True
        self.elem_classes = []
        self.events = {}
        self.children = []
        self.parent = self.context_stack[-1] if self.context_stack else None
        if self.parent is not None:
            self.parent.children.append(self)
        self.__dict__.update(kwargs)

    def __enter__(self):
        self.context_stack.append(self)
        return self

    def __exit__(self, *args):
        self.context_stack.pop()
        return False

    def is_visible(self):
        return self.visible and (self.parent is None or self.parent.is_visible())

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
        Component.context_stack.clear()
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

    def build_ui(self, is_img2img=False, step=64, maximum=2048, selected_profile="Krea2"):
        self.components.clear()
        self.mod.shared.opts.res_step = 16
        script = self.mod.ForgeNeoResolutionPresets()
        self.width = Component("Slider", 1024, minimum=64, maximum=maximum, step=step)
        self.height = Component("Slider", 1024, minimum=64, maximum=maximum, step=step)
        tab = "img2img" if is_img2img else "txt2img"
        script.after_component(self.width, elem_id=f"{tab}_width")
        script.after_component(self.height, elem_id=f"{tab}_height")
        self.script = script
        with patch.object(self.mod, "_load_last_profile", return_value=selected_profile):
            self.script_args = script.ui(is_img2img)
        self.profile = self.by_class("fnp__profile")[0]

    def by_class(self, name):
        return [component for component in self.components if name in component.elem_classes]

    def assert_unified_preset_row(self, selected):
        rows = self.by_class("fnp__preset_row")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        buttons = self.by_class("fnp__preset_button")
        self.assertEqual(len(buttons), self.mod.MAX_BUILTIN_PRESETS)
        self.assertEqual(row.children, buttons)
        self.assertTrue(all(button.parent is row for button in buttons))
        visible = [button for button in buttons if button.is_visible()]
        self.assertEqual([button.value for button in visible], [f"{w}×{h}" for w, h in self.profiles[selected]])
        self.assertFalse(self.by_class("fnp__more_button"))
        self.assertFalse(self.by_class("fnp__extended_row"))
        toolbar = self.by_class("fnp__profile_group")[0]
        self.assertIs(toolbar.parent, row.parent)
        self.assertGreater(row.parent.children.index(toolbar), row.parent.children.index(row))

    def test_all_profiles_start_fully_visible_in_one_row_on_both_tabs(self):
        for tab in (False, True):
            for selected in self.profiles:
                with self.subTest(img2img=tab, profile=selected):
                    self.build_ui(tab, selected_profile=selected)
                    self.assert_unified_preset_row(selected)

    def test_profile_switches_keep_all_fourteen_slots_in_continuous_order(self):
        self.profiles["Custom14"] = [(512 + 8 * index, 1024) for index in range(14)]
        for tab in (False, True):
            self.build_ui(tab, selected_profile="Custom14")
            for selected in ("Custom14", "Compatible", *self.profiles, "Custom14", "Compatible"):
                with self.subTest(img2img=tab, profile=selected):
                    self.profile.value = selected
                    self.profile.trigger("change")
                    self.assert_unified_preset_row(selected)
                    self.width.trigger("change")
                    self.height.trigger("change")
                    self.assert_unified_preset_row(selected)
                    self.assertEqual((self.width.value, self.height.value), (1024, 1024))

    def test_former_extra_slots_apply_toggle_highlight_and_undo_on_both_tabs(self):
        self.profiles["Custom14"] = [(512 + 8 * index, 1024) for index in range(14)]
        for tab in (False, True):
            for selected in ("Krea2", "Anima", "Custom14"):
                self.build_ui(tab, selected_profile=selected)
                for index in range(9, len(self.profiles[selected])):
                    with self.subTest(img2img=tab, profile=selected, index=index):
                        button = self.by_class("fnp__preset_button")[index]
                        width, height = self.profiles[selected][index]
                        self.assertTrue(button.is_visible())
                        button.trigger("click")
                        self.assertEqual((self.width.value, self.height.value), (width, height))
                        self.assertEqual(button.variant, "primary")
                        button.trigger("click")
                        self.assertEqual((self.width.value, self.height.value), (height, width))
                        self.assertEqual(button.variant, "stop")
                        self.by_class("fnp__undo_button")[0].trigger("click")
                        self.width.trigger("change")
                        self.assertEqual((self.width.value, self.height.value), (width, height))
                        self.assertEqual(button.variant, "primary")
                        self.assert_unified_preset_row(selected)

    def test_both_tabs_enable_all_krea2_sizes_without_changing_labels_or_step(self):
        for tab in (False, True):
            for step in (64, 32, 16):
                with self.subTest(img2img=tab, step=step):
                    self.build_ui(tab, step)
                    buttons = [button for button in self.by_class("fnp__preset_button") if button.visible]
                    self.assertEqual(len(buttons), 11)
                    self.assertTrue(all(button.interactive for button in buttons))
                    self.assertEqual([button.value for button in buttons], [f"{w}×{h}" for w, h in self.profiles["Krea2"]])
                    self.assertEqual((self.width.step, self.height.step), (step, step))
                    self.assertEqual(self.mod.shared.opts.res_step, 16)
                    self.assertFalse(self.by_class("fnp__compatibility_notice"))
                    self.assertFalse([component for component in self.components if component.kind == "HTML"])

    def test_profile_changes_preserve_exact_labels_without_changing_resolution(self):
        for tab in (False, True):
            with self.subTest(img2img=tab):
                self.build_ui(tab)
                for selected in ("Compatible", "Anima", "Krea2", "Compatible"):
                    self.profile.value = selected
                    self.profile.trigger("change")
                    buttons = [button for button in self.by_class("fnp__preset_button") if button.visible]
                    self.assertEqual([button.value for button in buttons], [f"{w}×{h}" for w, h in self.profiles[selected]])
                    self.assertTrue(all(button.interactive for button in buttons))
                    self.assertEqual((self.width.value, self.height.value), (1024, 1024))

    def test_range_limits_disable_only_out_of_range_buttons(self):
        self.build_ui(step=64, maximum=1536)
        buttons = [button for button in self.by_class("fnp__preset_button") if button.visible]
        self.assertEqual([button.value for button in buttons if not button.interactive], ["2048×2048", "672×1568"])
        self.assertTrue(next(button for button in buttons if button.value == "928×1152").interactive)

    def test_exact_selection_orientation_change_and_undo_round_trip(self):
        for tab in (False, True):
            with self.subTest(img2img=tab):
                self.build_ui(tab)
                button = next(button for button in self.by_class("fnp__preset_button") if button.value == "928×1152")
                button.trigger("click")
                self.assertEqual((self.width.value, self.height.value), (928, 1152))
                self.assertEqual(button.variant, "primary")
                self.assertIn("928×1152", self.by_class("fnp__current_info")[0].value)
                self.width.trigger("change")
                self.height.trigger("change")
                self.assertEqual((self.width.value, self.height.value), (928, 1152))
                button.trigger("click")
                self.assertEqual((self.width.value, self.height.value), (1152, 928))
                self.assertEqual(button.variant, "stop")
                self.by_class("fnp__undo_button")[0].trigger("click")
                self.assertEqual((self.width.value, self.height.value), (928, 1152))
                # Native Forge's swap callback is also an exact (height, width) return.
                self.width.value, self.height.value = self.height.value, self.width.value
                self.width.trigger("change")
                self.assertEqual((self.width.value, self.height.value), (1152, 928))
                self.assertEqual(button.variant, "stop")

    def test_randomize_receives_active_slider_constraints_from_ui(self):
        self.build_ui()
        self.assertEqual(len(self.script_args), 3)
        self.assertEqual(self.script_args[2].value, (64, 2048, 64))
        self.script_args[0].value = True
        process = types.SimpleNamespace(width=512, height=512)
        with patch.object(self.mod.random, "choice", side_effect=lambda values: values[-1]):
            self.script.before_process(process, *(component.value for component in self.script_args))
        self.assertEqual((process.width, process.height), (720, 1280))

    def test_user_preset_click_and_management_refresh_keep_exact_values(self):
        custom = [{"name": "Portrait", "width": 720, "height": 1280}]
        with patch.object(self.mod, "_load_user_presets", return_value=custom):
            self.build_ui()
            button = self.by_class("fnp__user_button")[0]
            self.assertEqual(button.value, "Portrait")
            self.assertTrue(button.interactive)
            button.trigger("click")
            self.assertEqual((self.width.value, self.height.value), (720, 1280))
            self.assertEqual(button.variant, "primary")
            self.width.trigger("change")
            self.assertEqual(button.value, "Portrait")
            # Management refreshes must preserve the name and exact dimensions.
            updates = self.mod._refresh_user_controls(None, [], [], [], [], current_width=720, current_height=1280, native_constraints=(64, 2048, 64))
            self.assertEqual(updates[1]["value"], button.value)
            self.assertTrue(updates[1]["interactive"])
            self.assertEqual(updates[1]["variant"], "primary")

    def test_reset_keeps_exact_first_preset_and_out_of_range_click_does_nothing(self):
        self.profiles["Krea2"] = [(928, 1152), (4096, 4096)]
        self.build_ui()
        self.by_class("fnp__reset_button")[0].trigger("click")
        self.assertEqual((self.width.value, self.height.value), (928, 1152))
        blocked = self.by_class("fnp__preset_button")[1]
        self.assertFalse(blocked.interactive)
        blocked.trigger("click")
        self.assertEqual((self.width.value, self.height.value), (928, 1152))


if __name__ == "__main__":
    unittest.main()
