# win-ocr-type

**截屏 → OCR → 自动打字。** Windows 里按一次热键框选屏幕上的文字，识别出来后按你指定的节奏逐字敲进当前窗口——不走剪贴板，不碰输入法状态，连打字软件那种"按格子计分"的界面也能正确输入。

```
按 F9 → 拖拽框选 → 看清/改错字 → Ctrl+Enter → 自动逐字输入
```

适合练打字（照着原文打）、批量录入屏幕上无法复制的文字、把截图内容搬进 Word / 记事本 / 代码编辑器。

---

## 目录

- [为什么不用"截图 + 粘贴"](#为什么不用截图--粘贴)
- [特性](#特性)
- [安装](#安装)
- [快速开始](#快速开始)
- [热键](#热键)
- [两种输入后端](#两种输入后端)
- [配置：按场景选模式](#配置按场景选模式)
- [空格与换行：clean 还是 layout](#空格与换行clean-还是-layout)
- [在打字软件里用](#在打字软件里用)
- [自检](#自检)
- [精度基准](#精度基准)
- [已知限制](#已知限制)
- [开发](#开发)
- [许可证](#许可证)

---

## 为什么不用"截图 + 粘贴"

因为很多场景不接受粘贴：

- **打字练习软件**（如金山打字通）按格子计分，粘贴等于作弊，`Ctrl+V` 直接无效；
- 剪贴板是全局共享的，覆盖掉用户原本的内容；
- 部分程序（游戏、远程桌面）拦截粘贴。

所以这里的输入全程靠模拟键盘事件：ASCII 走虚拟键码，中文走 Unicode 注入，每个键都拆成"按下 / 抬起"两次发送。

## 特性

- **不碰剪贴板**。输入路径只有 `SendInput`，剪贴板只在 `--selftest` 回读校验时用一下并恢复原值。
- **可编辑确认窗**。识别完先给你看，错字、多框进来的行、OCR 拆坏的字，改完再敲。不想每次确认可以把 `CONFIRM_MODE` 改成 `off`。
- **版面重建**（`LAYOUT_MODE="layout"`）。按每个字的像素框还原词间空格、行首缩进、空行——保真模式；默认的 `clean` 模式则把它们全部收掉，因为打字软件里多一个空格就整行错位。
- **重复行自动跳过**。框选时把"我已经打过的那行"框进来是常态，工具能识别"原文行 / 已输入行"这种错位重叠并跳过。
- **输入中断保护**。打字过程中前台窗口被切走，会先尝试拉回来，拉不回来就安全中止，不会一路盲打进别的窗口。
- **暗色主题自适应**。选区平均亮度过低时先反色再识别（深色 IDE / 深色微信）。
- **多显示器**。截图与框选覆盖整个虚拟桌面，副屏在左边或上边也能框；失败自动退回主屏。
- **日志**。控制台 + 滚动日志文件，关掉命令行也能查"这次识别了多少字、为什么中止"。

## 安装

要求 Windows 10 / 11、Python 3.8+。

```bat
pip install -r requirements.txt
```

依赖说明：

| 包 | 用途 |
| --- | --- |
| `pillow` | 截屏、图像预处理 |
| `pynput` | 全局热键监听 |
| `winocr` | 调 Windows 系统自带的 OCR 引擎（`Windows.Media.Ocr`） |

> `winocr` 用的是系统 OCR，所以识别语言取决于 Windows 已装的语言包。
> 中文系统默认有 `zh-Hans-CN`；要不是中文系统，装一下"中文（简体）"的
> 可选语言功能，或在 `OCR_LANG` 里改成你系统的语言标签。

## 快速开始

```bat
python win_ocr_type.py
```

也可以直接双击 `run.bat`。

启动后：把光标放进目标输入框 → 按 **F9** → 拖拽框选屏幕上的文字 → 松手 → 在确认窗里按 **Ctrl+Enter**。

## 热键

| 键 | 作用 |
| --- | --- |
| `F9` | 截图识别 |
| `F10` | 切换输入后端（sendinput / unicode） |
| `F11` | 重新挂载键盘监听（某些软件会抢先吞掉按键） |
| `F12` | 暂停 / 继续输入（打字过程中随时生效） |
| `F8` | 退出 |
| `Esc` | 取消框选 / 取消确认窗 |
| `Ctrl+Enter` | 确认窗里确认输入 |

热键可以在配置区改（`HOTKEY_KEY` 等）。

## 两种输入后端

| 后端 | 做法 | 适合 |
| --- | --- | --- |
| `sendinput`（默认） | ASCII 发虚拟键码，中文发 Unicode 注入 | 绝大多数程序；能触发真实按键事件，打字软件认 |
| `unicode` | 全部字符走 Unicode 注入，不经过键盘布局和输入法 | 目标程序忽略虚拟键码时；需要输入 emoji 时 |

`INPUT_MODE = "auto"` 时默认用 `sendinput`，但可以按窗口标题规则强制切换：

```python
APP_RULES = [
    ("某软件标题里的关键字", "unicode"),
]
```

## 配置：按场景选模式

配置都在文件顶部的"配置区"，改完保存重开即可。最常动的三个：

```python
CONFIRM_MODE = "always"   # always=每次确认  auto=只在可疑时确认  off=直接输入
LAYOUT_MODE  = "clean"    # clean=紧凑（打字软件）  layout=保真（空格/缩进/空行）
NEWLINE_AS_ENTER = False  # 识别到的换行要不要发回车
```

推荐组合：

| 场景 | `LAYOUT_MODE` | `NEWLINE_AS_ENTER` |
| --- | --- | --- |
| 打字练习软件 | `clean` | `False`（回车=提交，别发） |
| 记事本 / Word / 浏览器 | `layout` | `True` |
| 代码编辑器 | `layout` | `True` |

其他常用的：

```python
TYPE_INTERVAL     # 每字间隔（秒）。0.35 ≈ 每分钟 150 字，越小越快
OCR_UPSCALE       # OCR 前放大倍数，默认 2
AUTO_INVERT       # 暗底自动反色
FOCUS_GUARD       # 输入中断保护
```

## 空格与换行：clean 还是 layout

这两兄弟是同一个问题的两面——OCR 拿到的是**每个字的像素框**，而"空格"和"换行"并不存在于识别结果里，只能从坐标反推。

**`clean`（默认）**：接词，不补空格，不插空行。空行和空格信息被丢弃。

**`layout`**：按坐标重建。

- **词间空格**：相邻两个字的水平间隙超过约半个字宽 → 补一个空格（最多 4 个）。
  中文标点单独处理 —— OCR 给的标点框往往只有墨迹那么宽（"、"可能只有 4px），
  用框宽量必然偏大，所以标点一律按"占一整格"来量。
- **行首缩进**：行首 x 相对正文行首的偏移 → 前导空格（最多 12 个）。
- **空行**：行距超过约 1.6 倍行高 → 插入空行（最多连续 3 个，向下取整，宁可少插）。

`layout` 模式下 `clean_ocr_text()` 不会再去删空格——否则刚重建的版面会被自己抹掉。

实测（合成图验证）：4 空格缩进、1 个空行、英文词间空格都能还原；
中文正文切换 `layout` 与 `clean` 的输出完全相同（正常排版本来就没有多余间隙）。

## 在打字软件里用

几个已经踩过的坑：

1. **空格会占格子。** 打字软件一行固定 N 格，多一个空格就整行错位，所以默认 `clean`。
2. **回车等于提交。** 所以 `NEWLINE_AS_ENTER = False`。
3. **F9 没反应？** 目标软件若以管理员身份运行，本工具也要以管理员身份运行。
4. **按键被吞？** 按 `F11` 重新挂载监听（有些软件会抢先注册全局钩子）。
5. **"标点后吞字"** 是这类软件的常见行为，工具里用"空格+退格"的隐形缓冲绕过去，不需要你处理。

## 自检

```bat
python win_ocr_type.py --selftest
```

它会打开记事本，用两种后端各输入一段中英混排文本，再 `Ctrl+A / Ctrl+C` 回读比对，最后关闭窗口并把剪贴板恢复原样。

要求：**正常桌面环境**、记事本能弹出。在沙箱或受限会话里记事本可能起不来，脚本会报错退出。

## 精度基准

想量化识别准确率，就用自己的截图做基准：

```
bench_images/
├── shot1.png          # 截图
├── shot1.txt          # 这图上应该识别出的文字
├── shot2.png
└── shot2.txt
```

```bat
python bench_ocr.py                    :: 默认读 bench_images/
python bench_ocr.py --images D:\shots  :: 换目录
python bench_ocr.py --mode layout      :: 只测某个模式
python bench_ocr.py --crop 0,0,900,500 :: 每张图只取一块
```

输出每张图的 `ratio`（整体相似度）和 `acc`（逐位正确率），以及平均分。
`acc` 对错一个字很敏感（后面全部错位），看整体趋势时优先看 `ratio`。

> 仓库里不带截图样本 —— 截图容易含个人内容。请自带样本。

## 已知限制

- **仅 Windows**，且依赖系统 OCR 引擎（`Windows.Media.Ocr`）。
- **多显示器分支没有充分实测**：本机是单屏，跨屏框选只做了逻辑验证和失败回退，没在真实双屏上跑过。
- **`--selftest` 需要真实桌面**，CI 里跑不了。
- OCR 本身仍有极限错误：生僻字被拆成部件（"鬓" → "艹乒彡"）、行尾标点漏识别。这类后处理补不回来，所以有确认窗。
- 需要管理员权限的目标程序，本工具也得提权运行。

## 开发

```bat
python -m unittest discover -s tests -v     :: 单元测试（不需要 GUI）
python tests\manual_synthetic.py            :: 手工验收：合成图验版面重建
```

单元测试覆盖词框分行、clean/layout 渲染、缩进/空格/空行重建、重复行去重、
文本清理、`INPUT` 结构尺寸（必须是 40 字节，否则 `SendInput` 静默失败）。

`manual_synthetic.py` 会调真实 OCR，识别结果随系统语言包波动，所以故意不放进
unittest，留作手工验收。

## 许可证

MIT，见 [LICENSE](LICENSE)。

---

## English

Brief English README: [README.en.md](README.en.md)

`win-ocr-type` is a Windows tool that captures a screen region, runs it through the
system OCR engine, and types the recognized text into the focused window by
simulating individual key events — no clipboard involved. Press `F9`, drag a
rectangle, review the editable preview, press `Ctrl+Enter`.
