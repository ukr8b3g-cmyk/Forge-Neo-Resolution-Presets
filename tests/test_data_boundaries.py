from __future__ import annotations
import json
import fnp_resolution_data
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch
import test_settings_save as fixtures
from test_settings_save import document
from test_resolution_helpers import load_extension_module

class DataBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SettingsSaveTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.settings = self.fixture.mod
        self.gen = load_extension_module()
        for key in ('PROFILES_PATH', 'PROFILE_OVERRIDES_PATH', 'HISTORY_PATH', 'DATA_PATH'):
            setattr(self.gen, key, getattr(self.settings, key))

    def test_loaders_use_identical_recovery_and_limits_without_rewriting(self):
        valid = document('Mixed')
        valid['profiles'][0]['presets'] = [{'width': 512+i*8, 'height': 512} for i in range(16)]
        fifteen = json.loads(json.dumps(valid))
        fifteen['profiles'][0]['presets'] = fifteen['profiles'][0]['presets'][:15]
        for value in ([], {}, {'profiles': None}, {'profiles': [{'name': 'A', 'presets': None}]},
                      document('Test', 'test'), document('Strasse', 'Straße'), fifteen, valid):
            with self.subTest(value=value):
                path = self.gen.PROFILE_OVERRIDES_PATH
                original = json.dumps(value).encode()
                path.write_bytes(original)
                expected = self.settings._load_profiles_document()
                names, profiles, default = self.gen._load_profiles()
                self.assertEqual(names, [p['name'] for p in expected['profiles']])
                self.assertEqual(default, expected['default_profile'])
                self.assertEqual(profiles, {p['name']: [(v['width'],v['height']) for v in p['presets']] for p in expected['profiles']})
                self.assertEqual(path.read_bytes(), original)

    def test_history_clear_and_record_use_same_lock(self):
        # A competing clear at the record commit boundary must see the lock held.
        gen = self.gen
        original_replace = gen.os.replace
        def commit(src, dst):
            acquired = gen.HISTORY_LOCK.acquire(blocking=False)
            if acquired:
                gen.HISTORY_LOCK.release()
            self.assertFalse(acquired)
            return original_replace(src, dst)
        with patch.object(gen.os, 'replace', side_effect=commit):
            gen._record_resolution_history('txt2img', 'Original', 1024, 1024)
        # clear after record removes both old and new entries.
        status, _ = self.fixture.routes['history/clear']()
        self.assertEqual(status, 200)
        self.assertFalse(gen.HISTORY_PATH.exists())
        # clear before record permits only the new entry, never the old 512.
        gen._record_resolution_history('txt2img', 'Original', 1280, 1280)
        self.assertEqual([v['width'] for v in json.loads(gen.HISTORY_PATH.read_text())], [1280])
        # Assert the clear route acquires the very same lock as the writer.
        original_unlink = type(gen.HISTORY_PATH).unlink
        def unlink(path, *args, **kwargs):
            if path == gen.HISTORY_PATH:
                acquired = gen.HISTORY_LOCK.acquire(blocking=False)
                if acquired:
                    gen.HISTORY_LOCK.release()
                self.assertFalse(acquired)
            return original_unlink(path, *args, **kwargs)
        with patch.object(type(gen.HISTORY_PATH), 'unlink', unlink):
            self.fixture.routes['history/clear']()

    def test_record_pending_clear_waits_then_removes_previous_history(self):
        gen = self.gen
        entered, release, clear_started, cleared = (threading.Event() for _ in range(4))
        original_replace = gen.os.replace
        def commit(src, dst):
            entered.set()
            if not release.wait(3):
                raise AssertionError('writer was not released')
            return original_replace(src, dst)
        def clear():
            clear_started.set()
            result = self.fixture.routes['history/clear']()
            cleared.set()
            return result
        with ThreadPoolExecutor(max_workers=2) as pool:
            with patch.object(gen.os, 'replace', side_effect=commit):
                writer = pool.submit(gen._record_resolution_history, 'txt2img', 'Original', 1024, 1024)
                try:
                    self.assertTrue(entered.wait(3))
                    clearing = pool.submit(clear)
                    self.assertTrue(clear_started.wait(3))
                    self.assertFalse(cleared.wait(0.05))
                finally:
                    release.set()
                writer.result(timeout=3)
                self.assertEqual(clearing.result(timeout=3)[0], 200)
        self.assertFalse(gen.HISTORY_PATH.exists())
