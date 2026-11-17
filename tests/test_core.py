# -*- coding: utf-8 -*-
"""win-ocr-type 核心逻辑测试（不需要 GUI、不需要真发键）

覆盖：词框分行、clean/layout 两种渲染、缩进/空格/空行重建、
重复行去重（含两栏错位）、文本清理、OCR 常见错字修正。

跑法：python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import win_ocr_type as w
    IMPORT_ERROR = None
except Exception as e:          # CI 上缺 winocr / 缺 OCR 语言包时会走到这里
    w = None
    IMPORT_ERROR = e


class NS:
    """一个能挂属性的空对象，用来伪造 winocr 的返回结构"""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def make_result(rows):
    """rows: [[(x, y, w, h, text), ...], ...] → 伪造的 winocr 结果"""
    lines = []
    for row in rows:
        words = [NS(text=t, bounding_rect=NS(x=x, y=y, width=wd, height=h))
                 for (x, y, wd, h, t) in row]
        lines.append(NS(words=words))
    return NS(text="", lines=lines)


def char_line(y, text, x0=0.0, size=20.0, gap=0.0):
    """造一行"每字等宽、字距正常"的中文词框"""
    row = []
    x = x0
    for ch in text:
        row.append((x, y, size, size, ch))
        x += size + gap
    return row


@unittest.skipUnless(w is not None, f"模块无法导入：{IMPORT_ERROR}")
class TestGroupWords(unittest.TestCase):

    def test_single_line_order(self):
        # 传入顺序是反的，靠 x 排序还原成"第一"
        r = make_result([[(40, 0, 20, 20, "一"), (0, 0, 20, 20, "第")]])
        rows = w.group_words(r)
        self.assertEqual(len(rows), 1)
        self.assertEqual("".join(v.text for v in rows[0]), "第一")

    def test_punctuation_lower_is_same_line(self):
        # 标点比汉字偏下 5px，不能被切成两行
        r = make_result([[(0, 0, 20, 20, "白"), (22, 0, 20, 20, "雪"),
                          (44, 5, 20, 20, "，")]])
        rows = w.group_words(r)
        self.assertEqual(len(rows), 1)
        self.assertEqual("".join(v.text for v in rows[0]), "白雪，")

    def test_lines_are_sorted_even_if_result_is_shuffled(self):
        r = make_result([
            [(0, 60, 20, 20, "三")],
            [(0, 0, 20, 20, "一")],
            [(0, 30, 20, 20, "二")],
        ])
        rows = w.group_words(r)
        self.assertEqual(["".join(v.text for v in row) for row in rows],
                         ["一", "二", "三"])

    def test_empty_result(self):
        self.assertEqual(w.group_words(NS(text="", lines=[])), [])


@unittest.skipUnless(w is not None, f"模块无法导入：{IMPORT_ERROR}")
class TestRenderClean(unittest.TestCase):

    def test_clean_has_no_spaces(self):
        r = make_result([char_line(0, "白雪纷纷")])
        lines, ends = w.render_rows(w.group_words(r), "clean")
        self.assertEqual(lines, ["白雪纷纷"])
        self.assertIsNotNone(ends[0])

    def test_clean_ignores_big_gaps(self):
        # 即使词间有 40px 空隙，clean 模式也不补空格
        r = make_result([[(0, 0, 20, 20, "甲"), (60, 0, 20, 20, "乙")]])
        lines, _ = w.render_rows(w.group_words(r), "clean")
        self.assertEqual(lines, ["甲乙"])


@unittest.skipUnless(w is not None, f"模块无法导入：{IMPORT_ERROR}")
class TestRenderLayout(unittest.TestCase):

    def test_normal_char_spacing_adds_no_space(self):
        # 中文正常字距（下一个字的 x = 上一个 x + 字宽）不该被认成空格
        r = make_result([char_line(0, "白雪纷纷何所似")])
        lines, _ = w.render_rows(w.group_words(r), "layout")
        self.assertEqual(lines, ["白雪纷纷何所似"])

    def test_word_gap_becomes_single_space(self):
        # 字宽 20、间隙 20 → 一个空格
        r = make_result([[(0, 0, 20, 20, "好"), (40, 0, 20, 20, "的")]])
        lines, _ = w.render_rows(w.group_words(r), "layout")
        self.assertEqual(lines, ["好 的"])

    def test_wide_gap_is_capped(self):
        # 间隙 200px（10 个字宽）最多只还原 SPACE_MAX 个空格
        r = make_result([[(0, 0, 20, 20, "甲"), (220, 0, 20, 20, "乙")]])
        lines, _ = w.render_rows(w.group_words(r), "layout")
        self.assertEqual(lines, ["甲" + " " * w.SPACE_MAX + "乙"])

    def test_indent_becomes_leading_spaces(self):
        first = char_line(0, "正文", x0=0)
        second = char_line(30, "缩进", x0=40)     # 缩进 40px = 2 字宽
        r = make_result([first, second])
        lines, _ = w.render_rows(w.group_words(r), "layout")
        self.assertEqual(lines[0], "正文")
        self.assertEqual(lines[1], "  缩进")

    def test_blank_line_for_big_row_gap(self):
        first = char_line(0, "上")
        second = char_line(100, "下")             # 行距 100px，行高 20
        r = make_result([first, second])
        lines, ends = w.render_rows(w.group_words(r), "layout")
        self.assertEqual(lines[0], "上")
        self.assertEqual(lines[-1], "下")
        self.assertGreaterEqual(lines.count(""), 1)
        self.assertEqual(len(lines), len(ends))   # 文本行与行尾坐标必须等长

    def test_ends_align_with_lines(self):
        rows = [char_line(0, "第一行"), char_line(100, "第三行")]
        lines, ends = w.render_rows(w.group_words(make_result(rows)), "layout")
        self.assertEqual(len(lines), len(ends))
        for text_line, end in zip(lines, ends):
            if text_line == "":
                self.assertIsNone(end)


@unittest.skipUnless(w is not None, f"模块无法导入：{IMPORT_ERROR}")
class TestCleanOcrText(unittest.TestCase):

    def setUp(self):
        self._layout = w.LAYOUT_MODE
        w.LAYOUT_MODE = "clean"

    def tearDown(self):
        w.LAYOUT_MODE = self._layout

    def test_removes_spaces_around_cjk_in_clean_mode(self):
        self.assertEqual(w.clean_ocr_text("白 雪 纷 纷"), "白雪纷纷")

    def test_keeps_english_spaces(self):
        self.assertEqual(w.clean_ocr_text("hello world 世界"), "hello world世界")

    def test_keeps_newlines(self):
        self.assertEqual(w.clean_ocr_text("第一行\n第二行"), "第一行\n第二行")

    def test_layout_mode_keeps_spaces(self):
        w.LAYOUT_MODE = "layout"
        self.assertEqual(w.clean_ocr_text("白 雪 纷 纷"), "白 雪 纷 纷")

    def test_fix_map_applies(self):
        self.assertEqual(w.clean_ocr_text("己经到了"), "已经到了")

    def test_strip_leading_sentence_end_punct(self):
        self.assertEqual(w.clean_ocr_text("。开头"), "开头")


@unittest.skipUnless(w is not None, f"模块无法导入：{IMPORT_ERROR}")
class TestDedupe(unittest.TestCase):

    def test_near_duplicate_shifted_by_one_char(self):
        a = "此人，咸来问讯。自云先世避秦时乱，率妻子邑人来此绝境，不复出焉；遂与"
        b = "人，咸来问讯。自云先世避秦时乱，率妻子邑人来此绝境，不复出焉；遂与"
        self.assertTrue(w._near_duplicate(a, b))

    def test_repeated_couplet_is_not_duplicate(self):
        self.assertFalse(w._near_duplicate("蒹葭苍苍，白露为霜。",
                                           "蒹葭萋萋，白露未晞。"))

    def test_unrelated_lines_not_duplicate(self):
        self.assertFalse(w._near_duplicate("第一行内容", "第二行内容"))

    def test_short_repeated_lines_are_kept(self):
        lines = ["好", "好", "好"]
        out, _ = w.dedupe_lines(lines, [None] * 3)
        self.assertEqual(out, ["好", "好", "好"])

    def test_strict_prefix_removed(self):
        lines = ["谢太傅寒雪日内集，与儿女讲论文义。", "谢太傅寒雪日内集"]
        out, _ = w.dedupe_lines(lines, [None, None])
        self.assertEqual(out, ["谢太傅寒雪日内集，与儿女讲论文义。"])


@unittest.skipUnless(w is not None, f"模块无法导入：{IMPORT_ERROR}")
class TestAnalyzeResult(unittest.TestCase):

    def test_layout_end_to_end(self):
        rows = [char_line(0, "第一段"),
                char_line(30, "第二段", x0=40)]
        text, ends = w.analyze_result(make_result(rows), mode="layout")
        self.assertEqual(text.split("\n"), ["第一段", "  第二段"])
        self.assertEqual(len(ends), 2)

    def test_clean_end_to_end(self):
        rows = [char_line(0, "第一段"), char_line(30, "第二段", x0=40)]
        text, _ = w.analyze_result(make_result(rows), mode="clean")
        self.assertEqual(text.split("\n"), ["第一段", "第二段"])

    def test_two_column_offset_duplicates_removed(self):
        # 打字软件的"原文行 / 已输入行"：已输入行从下一格开始，内容重叠
        long_a = "见渔人，乃大惊，问所从来，具答之。便要还家，设酒杀鸡作食。村中闻有"
        long_b = "渔人，乃大惊，问所从来，具答之。便要还家，设酒杀鸡作食。村中闻有此"
        rows = [char_line(0, long_a), char_line(20, long_b, x0=20)]
        text, _ = w.analyze_result(make_result(rows), mode="clean")
        self.assertEqual(text, long_a)


@unittest.skipUnless(w is not None, f"模块无法导入：{IMPORT_ERROR}")
class TestMisc(unittest.TestCase):

    def test_median(self):
        self.assertEqual(w._median([3, 1, 2]), 2)
        self.assertEqual(w._median([]), 1.0)

    def test_punct_positions(self):
        self.assertEqual(w._punct_buffer_positions("你好。\n世界，"), {2, 6})

    def test_resolve_mode_defaults_to_sendinput(self):
        self.assertEqual(w.resolve_mode(""), "sendinput")

    def test_input_struct_size_is_40(self):
        # 64 位下 INPUT 必须是 40 字节，否则 SendInput 静默失败
        self.assertEqual(w._INPUT_SIZE, 40)


if __name__ == "__main__":
    unittest.main(verbosity=2)
