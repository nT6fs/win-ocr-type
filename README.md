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
- [命令行参数](#命令行参数)
- [两种输入后端](#两种输入后端)
- [配置：按场景选模式](#配置按场景选模式)
- [空格与换行：clean 还是 layout](#空格与换行clean-还是-layout)
- [在打字软件里用](#在打字软件里用)
- [自检](#自检)
- [精度基准](#精度基准)
- [已知限制](#已知限制)
- [开发](#开发)
- [关于作者与来源](#关于作者与来源)
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

## 命令行参数

不想改文件也能临时换模式——**命令行优先级高于文件顶部的配置区**：

```bat
python win_ocr_type.py --mode layout --confirm off
```

| 参数 | 作用 |
| --- | --- |
| `--mode clean` / `layout` | 覆盖 `LAYOUT_MODE` |
| `--confirm always` / `auto` / `off` | 覆盖 `CONFIRM_MODE` |
| `--backend sendinput` / `unicode` | 覆盖 `INPUT_MODE` |
| `--lang TAG` | 覆盖 `OCR_LANG` |
| `--interval 秒` | 覆盖 `TYPE_INTERVAL` |
| `--no-invert` | 关闭暗色背景自动反色 |
| `--log-level LEVEL` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `--dry-run` | 只识别并显示结果，**不往任何窗口输入** |
| `--list-langs` | 列出系统装了的 OCR 语言包后退出 |
| `--selftest` | 打开记事本自检输入 |
| `--version` | 显示版本号 |

几个常用组合：

```bat
:: 想知道这块区域能不能认出来，但不输入
python win_ocr_type.py --dry-run

:: 往记事本/编辑器里输，保留空格和换行
python win_ocr_type.py --mode layout

:: 打得太慢，加快一倍
python win_ocr_type.py --interval 0.18

:: 看系统有哪些 OCR 语言（没有语言包时识别会直接报错）
python win_ocr_type.py --list-langs
```

也可以安装成一个命令（可选）：

```bat
pip install .
win-ocr-type --mode layout
```

安装后配置文件仍在源码里（`win_ocr_type.py` 顶部的配置区），改完重新运行即可。

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

## 关于作者与来源

**这个项目的代码是 AI 写的，没有人类作者署名。** 具体经过：

- **v4 —— 起点。** 一个单文件脚本，由 **ChatGPT** 起草：截屏 → OCR → 模拟按键
  输入，并针对打字软件的"格子计分"做了大量绕行（标点后吞字用空格+退格缓冲、
  回车不发、输入法切换时机等）。
- **v5 —— 重构与加固。** 由 **DeepSeek Harness 会话中的 agent（DeepSeek 模型）**
  完成：合并重复的输入循环、修 `SendInput` 结构体成员类型、加可编辑确认窗、
  输入中断保护、多显示器、滚动日志、单实例，并补上"两栏错位重复行"的去重。
- **v6 / 0.1.0 —— 版面保真与工程化。** 同样由上述 agent 完成：按字框坐标重建
  空格 / 缩进 / 空行、中文标点的特殊量法、暗底反色，以及仓库结构、单元测试、
  CI、基准工具和本文档。

打字节奏、缓冲时长这类参数不是凭空猜的，是在真实打字软件里反复调试确定的；
但这些参数的**取值**是调出来的，**代码**是 AI 产出的。

因此：

- [LICENSE](LICENSE) 里的版权人写的是 `win-ocr-type contributors`，是一个
  占位名，**不指向任何具体个人**。如果你 fork 或以自己的名义再分发，可以把它
  换成你自己的名字。
- AI 生成内容的版权归属在不同司法辖区规定不同、且尚在变化。如果要在商业场景
  使用，或需要明确的权利归属，请自行确认你所在地的规定。
- 提交（commit）记录里的作者名同样是占位值，可在你的 fork 里用
  `git commit --amend --reset-author` 替换。

## 许可证

MIT，见 [LICENSE](LICENSE)。

---

## English

Brief English README: [README.en.md](README.en.md)

`win-ocr-type` is a Windows tool that captures a screen region, runs it through the
system OCR engine, and types the recognized text into the focused window by
simulating individual key events — no clipboard involved. Press `F9`, drag a
rectangle, review the editable preview, press `Ctrl+Enter`.
