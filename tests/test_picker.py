import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
from app import explorer_select_command
from picker import FileScanner, RandomPicker, normalize_extension


class PickerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / "a").mkdir(); (self.root / "b").mkdir()
        for name in ("one.pdf", "two.jpg", "answer.png"): (self.root / "a" / name).write_text("x")
        (self.root / "b" / "three.pdf").write_text("x")
        self.paths = [str(p) for p in self.root.rglob("*") if p.is_file()]

    def tearDown(self): self.temp.cleanup()
    def test_extension_normalization(self): self.assertEqual(normalize_extension(" .CBZ "), ".cbz")
    def test_scanner_filters_scope_and_exclusions(self):
        scan = FileScanner().scan(str(self.root), {".pdf", ".jpg", ".png"}, set(), set(), ["answer"], {"a": True, "b": False})
        self.assertEqual({Path(x).name for x in scan}, {"one.pdf", "two.jpg"})
    def test_recent_candidates_are_equal_pool(self):
        p = RandomPicker(); p.set_pool(self.paths)
        candidates = p.candidates([self.paths[0]], 1)
        self.assertEqual(set(candidates), set(self.paths[1:]))
    def test_recent_larger_than_pool_relaxes(self):
        p = RandomPicker(); p.set_pool(self.paths)
        self.assertEqual(set(p.candidates(self.paths, 100)), set(self.paths))
    def test_shuffle_has_no_repeat_per_round(self):
        p = RandomPicker(); p.set_pool(self.paths)
        draws = [p.choose("shuffle", [], 0) for _ in self.paths]
        self.assertEqual(set(draws), set(self.paths))
    def test_manual_exclusion(self):
        scan = FileScanner().scan(str(self.root), {".pdf"}, set(), {self.paths[0]}, [], {})
        self.assertNotIn(self.paths[0], scan)

    def test_config_save_and_load(self):
        target = self.root / "settings.json"
        with patch.object(config, "config_path", return_value=target):
            data = config.load_config(); data["root"] = "C:\\资料"; data["history"] = ["C:\\资料\\一.pdf"]
            config.save_config(data)
            restored = config.load_config()
        self.assertEqual(restored["root"], "C:\\资料")
        self.assertEqual(restored["history"], ["C:\\资料\\一.pdf"])

    def test_explorer_select_keeps_switch_and_unicode_path_separate(self):
        path = "D:\\Study\\Course A\\Kapitel, Eins\\页面 17.png"
        self.assertEqual(explorer_select_command(path), ["explorer.exe", "/select,", path])


if __name__ == "__main__": unittest.main()
