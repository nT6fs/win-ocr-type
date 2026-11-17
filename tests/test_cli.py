# -*- coding: utf-8 -*-
"""命令行参数与配置覆盖的测试（不启动 GUI、不发按键）"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import win_ocr_type as w
    IMPORT_ERROR = None
except Exception as e:
    w = None
    IMPORT_ERROR = e


SNAPSHOT_ATTRS = ("LAYOUT_MODE", "CONFIRM_MODE", "INPUT_MODE", "OCR_LANG",
                  "TYPE_INTERVAL", "AUTO_INVERT", "LOG_LEVEL", "DRY_RUN")


@unittest.skipUnless(w is not None, f"模块无法导入：{IMPORT_ERROR}")
class TestCli(unittest.TestCase):

    def setUp(self):
        self.saved = {k: getattr(w, k) for k in SNAPSHOT_ATTRS}

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(w, k, v)

    def parse(self, argv):
        return w.build_arg_parser().parse_args(argv)

    def test_defaults(self):
        args = self.parse([])
        self.assertFalse(args.dry_run)
        self.assertFalse(args.selftest)
        self.assertFalse(args.list_langs)
        self.assertIsNone(args.mode)
        self.assertIsNone(args.confirm)
        self.assertIsNone(args.interval)

    def test_version_exits_zero(self):
        with self.assertRaises(SystemExit) as cm:
            self.parse(["--version"])
        self.assertEqual(cm.exception.code, 0)

    def test_invalid_choice_rejected(self):
        with self.assertRaises(SystemExit):
            self.parse(["--mode", "nonsense"])

    def test_overrides_applied(self):
        w.apply_overrides(self.parse(
            ["--mode", "layout", "--confirm", "off", "--backend", "unicode",
             "--lang", "en-US", "--interval", "0.1", "--no-invert",
             "--log-level", "DEBUG", "--dry-run"]))
        self.assertEqual(w.LAYOUT_MODE, "layout")
        self.assertEqual(w.CONFIRM_MODE, "off")
        self.assertEqual(w.INPUT_MODE, "unicode")
        self.assertEqual(w.OCR_LANG, "en-US")
        self.assertEqual(w.TYPE_INTERVAL, 0.1)
        self.assertFalse(w.AUTO_INVERT)
        self.assertEqual(w.LOG_LEVEL, "DEBUG")
        self.assertTrue(w.DRY_RUN)

    def test_empty_args_change_nothing(self):
        before = {k: getattr(w, k) for k in SNAPSHOT_ATTRS}
        w.apply_overrides(self.parse([]))
        for k, v in before.items():
            self.assertEqual(getattr(w, k), v, k)

    def test_negative_interval_rejected(self):
        with self.assertRaises(SystemExit):
            w.apply_overrides(self.parse(["--interval", "-1"]))

    def test_interval_is_read_at_call_time(self):
        """--interval 必须能改变实际使用的间隔：默认参数不能绑定旧值"""
        import inspect
        sig = inspect.signature(w._type_stream)
        self.assertIsNone(sig.parameters["interval"].default)
        for fn in (w.type_text_sendinput, w.type_text_unicode):
            self.assertIsNone(inspect.signature(fn).parameters["interval"].default)

    def test_version_attribute_present(self):
        self.assertRegex(w.__version__, r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main(verbosity=2)
