# 基准样本放这里
#
# 每张截图配一个同名 .txt，内容是"这张图上应该识别出来的文字"：
#
#   bench_images/
#   ├── shot1.png
#   ├── shot1.txt
#   ├── shot2.png
#   └── shot2.txt
#
# 然后运行：
#
#   python bench_ocr.py
#
# 注意：截图容易含个人内容，本目录下的图片已在 .gitignore 里排除，
# 不会被提交。.txt 里的期望文本同样建议先确认不含隐私。
