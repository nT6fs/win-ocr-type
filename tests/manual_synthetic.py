# -*- coding: utf-8 -*-
"""手工验收：用合成图检查 layout 模式能否还原缩进 / 空行 / 英文词间空格。

为什么是"手工跑"而不是进 unittest：
  这个脚本要真调 Windows OCR，识别结果随系统 OCR 语言包和版本波动，
  放进 CI 会变成一会儿过一会儿不过。所以它归在手工验收里，
  跑一次看输出对不对就行。

用法：python tests/manual_synthetic.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import win_ocr_type as w

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageStat
import winocr

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\arial.ttf",
]
SIZE = 32
LINE_STEP = 56

# (文本, 缩进空格数)；None 表示空一行
LINES = [
    ("第一段第一行正文文字", 0),
    ("第二行有缩进四个空格", 4),
    ("hello world mixed 混排", 0),
    None,
    ("最后一行没有缩进", 0),
]


def get_font():
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, SIZE), path
            except Exception:
                continue
    raise SystemExit("找不到可用的字体，手工验收跳过。")


def build_image():
    font, _ = get_font()
    width = 900
    height = 60 + len(LINES) * LINE_STEP
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    y = 20
    for item in LINES:
        if item is None:
            y += LINE_STEP
            continue
        text, indent = item
        draw.text((20 + indent * SIZE, y), text, fill="black", font=font)
        y += LINE_STEP
    return img


def recognize(img):
    gray = ImageOps.grayscale(img)
    mean = ImageStat.Stat(gray).mean[0]
    if w.AUTO_INVERT and mean < w.INVERT_THRESHOLD:
        gray = ImageOps.invert(gray)
    img = ImageOps.autocontrast(gray)
    if w.OCR_UPSCALE > 1:
        img = img.resize((img.width * w.OCR_UPSCALE, img.height * w.OCR_UPSCALE),
                         Image.LANCZOS)
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(winocr.recognize_pil(img, w.OCR_LANG))
    finally:
        loop.close()


def main():
    img = build_image()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "synthetic_layout.png")
    img.save(out)
    result = recognize(img)

    print(f"合成图：{out}")
    print("=" * 60)
    for mode in ("clean", "layout"):
        text, ends = w.analyze_result(result, mode=mode)
        print(f"--- {mode} ---")
        for line in text.split("\n"):
            print(repr(line))
        print(f"（行尾坐标 {len(ends)} 个）")
        print()

    print("期望：")
    for item in LINES:
        if item is None:
            print(repr(""))
        else:
            text, indent = item
            print(repr(" " * indent + text))
    print()
    print("人工对照要点：")
    print("  1. 第二行开头应有 4 个空格")
    print("  2. 第 3 行与最后一行之间应有一个空行")
    print("  3. 英文单词之间应保留单个空格")
    print("  4. clean 模式应完全没有空格和空行")
    print("注意：英文/混排部分是否认得准取决于系统 OCR 引擎，"
          "本脚本验的是版面重建，不是识别准确率。")


if __name__ == "__main__":
    main()
