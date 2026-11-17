# -*- coding: utf-8 -*-
r"""OCR 精度基准：拿你自己的截图跑分。

图片放在一个目录里（默认 bench_images/），每张图配一个同名 .txt，
内容是这图上"应该识别出来"的文字。脚本会：
  1. 按与主程序完全相同的预处理识别
  2. 用 clean / layout 两种模式各渲染一遍
  3. 和 .txt 里的期望文本算相似度（ratio）与逐位正确率（acc）
  4. 打印每张图的明细和平均分

用法：
    python bench_ocr.py                       # 用 bench_images/
    python bench_ocr.py --images D:\shots     # 用别的目录
    python bench_ocr.py --mode layout         # 只测 layout 模式
    python bench_ocr.py --crop 0,0,900,500    # 每张图只取这一块（x,y,w,h）

目录里没有 .txt 的图片会被跳过（没有期望文本就没法算分）。
"""
import argparse
import asyncio
import difflib
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import win_ocr_type as w

from PIL import Image, ImageOps, ImageStat
import winocr


def load_pairs(images_dir):
    pairs = []
    for path in sorted(glob.glob(os.path.join(images_dir, "*.png"))
                       + glob.glob(os.path.join(images_dir, "*.jpg"))):
        base, _ = os.path.splitext(path)
        txt = base + ".txt"
        if not os.path.exists(txt):
            print(f"[跳过] {os.path.basename(path)}：没有同名 .txt 期望文本")
            continue
        with open(txt, encoding="utf-8") as f:
            expected = f.read()
        pairs.append((path, expected))
    return pairs


def recognize(img, crop=None):
    if crop:
        x, y, cw, ch = crop
        img = img.crop((x, y, x + cw, y + ch))
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


def normalize(text):
    return "".join(text.split())


def score(got, expected):
    g, e = normalize(got), normalize(expected)
    if not g or not e:
        return 0.0, 0.0
    ratio = difflib.SequenceMatcher(None, g, e).ratio()
    acc = sum(1 for a, b in zip(g, e) if a == b) / max(len(g), len(e))
    return ratio, acc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", default="bench_images",
                    help="截图目录（默认 bench_images/）")
    ap.add_argument("--mode", default="both",
                    choices=["clean", "layout", "both"])
    ap.add_argument("--crop", default="",
                    help="每张图只取一块：x,y,w,h")
    args = ap.parse_args()

    if not os.path.isdir(args.images):
        print(f"目录不存在：{args.images}")
        print("先建一个 bench_images/ ，放 png 和同名 txt（期望文本）。")
        return 1

    pairs = load_pairs(args.images)
    if not pairs:
        print("没有可用的样本（图片 + 同名 .txt）。")
        return 1

    crop = None
    if args.crop:
        crop = tuple(int(v) for v in args.crop.split(","))

    modes = ["clean", "layout"] if args.mode == "both" else [args.mode]
    totals = {m: [0.0, 0.0] for m in modes}

    for path, expected in pairs:
        img = Image.open(path).convert("RGB")
        try:
            result = recognize(img, crop)
        except Exception as e:
            print(f"[失败] {os.path.basename(path)}：{e}")
            continue
        print(f"--- {os.path.basename(path)} ---")
        for mode in modes:
            got, _ = w.analyze_result(result, mode=mode)
            got = w.clean_ocr_text(got)
            ratio, acc = score(got, expected)
            totals[mode][0] += ratio
            totals[mode][1] += acc
            print(f"  {mode:7s} ratio={ratio:.3f} acc={acc:.3f}")
            if ratio < 0.95:
                g, e = normalize(got), normalize(expected)
                sm = difflib.SequenceMatcher(None, g, e)
                for tag, i1, i2, j1, j2 in sm.get_opcodes():
                    if tag != "equal":
                        print(f"      [{tag}] got={g[i1:i2]!r} exp={e[j1:j2]!r}")

    n = len(pairs)
    print("=" * 50)
    for mode in modes:
        r, a = totals[mode]
        print(f"平均 {mode:7s} ratio={r / n:.3f} acc={a / n:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
