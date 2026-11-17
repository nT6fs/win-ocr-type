# -*- coding: utf-8 -*-
"""
Win11 截图 OCR 自动输入工具 v5
================================
目标：在不同软件(打字软件 / 记事本 / Word / 微信 / QQ / 浏览器 / IDE 等)里
把 OCR 识别到的文字"自动、正确地"输入进去。

v5 相对 v4 的变化
-----------------
1) 识别后默认先弹"可编辑确认窗"：看清、改错字、再按 Ctrl+Enter 输入（Esc 取消）。
   这是为了在复杂情况下（识别错字、框多了、行合并异常）也能正确输出。
   不想每次确认就把 CONFIRM_MODE 改成 "off"，只想在可疑时确认就改成 "auto"。
2) 输入过程中守护目标窗口：前台一旦不是目标窗口，先尝试拉回前台；
   超过 FOCUS_GUARD_WAIT 秒拉不回来就安全中止，不会一路盲打进别的窗口。
3) 多显示器支持：截图与框选覆盖整个虚拟屏幕（副屏在左/上也能框）；
   失败自动退回主屏模式，不影响使用。
4) 日志：同时写控制台和脚本目录下的 win_ocr_type.log（滚动保留），
   关掉命令行后仍能查"这次识别了多少字、用了哪个后端、为什么中止"。
5) 加退出热键 F8；重复启动会被拦下（命名互斥体）。
6) 代码层：合并两份几乎相同的输入循环（再也不会出现"改了一处忘另一处"）、
   修 send_combo 的抬起顺序、修 INPUT 结构成员类型、像素扫描改为 getextrema 提速、
   删掉重复定义的 dedupe_similar_lines，把未调用的实验函数挪到文件末尾备用区。

保持不变的（v4 调出来的打字行为，一个参数都没动）
-----------------------------------------------
- 默认后端 sendinput（逐字模拟按键）；仅当文本含英文字符时才把目标窗口输入法切英文
- 按键按下/抬起分离发送；标点走"假字+退格"缓冲；换行不发回车（打字软件里回车=提交）
- OCR 预处理仍是 灰度+自动对比度+放大 2 倍（7 张真实截图基准里平均准确率最高）

两种输入后端，运行时可随时用 F10 切换：
  sendinput —— 逐字模拟按键：ASCII 用虚拟键码、中文用 Unicode 注入（默认）
  unicode   —— 全部字符走 Unicode 注入：不走输入法，支持 emoji 代理对

用法
----
  python win_ocr_type_v5.py            正常使用：目标输入框内按 F9 -> 框选 -> 松手
                                       确认窗里 Ctrl+Enter 输入 / Esc 取消
  python win_ocr_type_v5.py --selftest 自检：记事本输入回读校验

热键
----
  F9  截图识别      F10 切换后端      F11 重新挂载键盘监听
  F12 暂停/继续输入  F8  退出

若在某个软件（如金山打字通）里 F9 无反应：
  1) 该软件若以管理员身份运行，本工具也要以管理员身份运行
  2) 按 F11 重新挂载键盘监听（部分软件会抢先吞掉按键），再回目标软件按 F9
"""

import os
import re
import sys
import time
import queue
import ctypes
import asyncio
import difflib
import logging
import threading
import subprocess
from ctypes import wintypes
from logging.handlers import RotatingFileHandler

if sys.platform != "win32":
    # 用 ImportError 而不是 sys.exit()：这样 import 本模块的测试/工具能捕获到，
    # 在非 Windows 上自动 skip，而不是整个进程静默退出。
    raise ImportError("win_ocr_type 仅支持 Windows。")

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import tkinter as tk
from PIL import ImageGrab, ImageTk, Image, ImageOps, ImageStat
from pynput import keyboard
import winocr


# ==================== 配置区 ====================
HOTKEY_KEY        = keyboard.Key.f9    # 触发热键
TOGGLE_KEY        = keyboard.Key.f10   # 切换输入后端的热键
REHOOK_KEY        = keyboard.Key.f11   # 重新挂载键盘监听（F9 在目标软件里失效时用）
PAUSE_KEY         = keyboard.Key.f12   # 暂停/继续输入（随时生效）
QUIT_KEY          = keyboard.Key.f8    # 退出程序
OCR_LANG          = "zh-Hans-CN"
CLEAN_OCR_TEXT    = True               # 清理 OCR 空格：打字软件格子排版常被识别出字间空格
TYPE_INTERVAL     = 0.35               # 每字间隔（秒），整体约每分钟 150 字
KEY_DOWN_UP_DELAY = 0.02               # 按键按下→抬起间隔（秒），打字软件/游戏常需要
PUNCT_EXTRA_DELAY = 0.05               # 标点后额外等待（秒）
PUNCT_BUFFER      = "space"            # 标点后隐形缓冲："space"=空格+退格 / "off"=关闭
LINE_END_WAIT     = 0.20               # 行尾标点后的等待（秒）
STRIP_LEADING_PUNCT = True             # 去掉识别结果开头的多余标点（框选多框进去的句号等）
OCR_UPSCALE       = 2                  # OCR 前放大倍数，提高小标点识别率
DEDUPE_SIMILAR_LINES = True            # 去掉与上一行重复的行（框进"已输入行"时自动跳过）
DEDUPE_MIN_LEN    = 4                  # 短于这个字数的行不参与"重复行"判断，防止误删短行
DEDUPE_NEAR_DUPLICATE = True           # 去掉与上一行"错位重叠"的行（打字软件原文/已输入两栏错一格）
DEDUPE_RATIO      = 0.85               # 上面那条的重叠比例阈值：连续相同部分要占到这一行的 85%
OCR_FIX_MAP = {                        # OCR 常见混淆字自动修正（成对整词替换，别写单字）
    "己去": "已去", "己经": "已经", "己有": "已有", "己在": "已在",
    "己到": "已到", "己是": "已是", "己于": "已于", "己被": "已被",
    "自已": "自己",
}
TYPED_ROW_OFFSET  = 42                 # 输入行相对原文行的垂直偏移（像素）
LINE_END_VERIFY   = False              # 行尾标点校验补打（坐标假设不通用，默认关闭）
LINE_END_RETRY    = 2                  # 补打最多次数
NEWLINE_AS_ENTER  = False              # 打字软件里回车=提交，识别结果中的换行直接跳过
AUTO_START_DELAY  = 1.0
RESTORE_FOCUS     = True
ASCII_AS_VK       = True               # ASCII 用虚拟键码模拟；False 则全走 Unicode 注入
SWITCH_IME_FOR_SENDINPUT = True        # 文本含英文字符时，打字前把目标窗口输入法切到英文

# ---- 版面模式：识别结果里要不要保留空格 / 缩进 / 空行 ----
#   "clean"  —— 紧凑（默认）。接词不加空格，最省事，也是打字软件里唯一能用的模式：
#               打字软件按格子排版，多一个空格就占掉一格、整行错位。
#   "layout" —— 保真。按每个字的像素框重建版面：词间横向间隙还原成空格，
#               行首缩进还原成前导空格，行距过大处插空行。
#               适合往记事本 / Word / 代码编辑器 / 浏览器里输。
# 注意：layout 模式下想要换行也生效，还得把 NEWLINE_AS_ENTER 设成 True，
#       否则空格发了、换行没发，结果是"一整行带空格"。
LAYOUT_MODE       = "clean"

# 版面重建的度量（都相对"一个字的宽度"，中文里字宽≈字高，所以拿中位字高当单位）
SPACE_MIN_RATIO   = 0.45               # 词间间隙超过 0.45 个字宽 → 算一个空格
SPACE_MAX         = 4                  # 单个间隙最多还原成几个空格
INDENT_MIN_RATIO  = 0.60               # 行首离最左边超过 0.6 字宽 → 算缩进
INDENT_MAX        = 12                 # 缩进最多还原成几个空格
BLANK_LINE_RATIO  = 1.60               # 行距超过 1.6 倍行高 → 插一个空行
BLANK_LINE_MAX    = 3                  # 一处最多插几个空行

# ---- 暗色背景自动反色 ----
# 微信/IDE 深色主题下是浅字深底，winocr 对这种图的识别率明显更差。
# 打开后：选区平均亮度低于阈值就先反色再识别。白底文档的平均亮度在 200 以上，
# 不会误触发；模糊的中间灰（如 150 左右）也不会。
AUTO_INVERT       = True
INVERT_THRESHOLD  = 90

# 识别后是否先让你看一眼：
#   "always" —— 每次识别完都弹可编辑确认窗（默认，最稳）
#   "auto"   —— 只在结果可疑时弹（疑似错字/极短/含怪字符）
#   "off"    —— 不弹，识别完直接输入（等同 v4 的行为）
CONFIRM_MODE      = "always"

# 输入过程中守护目标窗口（v5 新增）：前台不是目标窗口时先尝试拉回，
# 拉不回来就暂停；超过这个秒数仍失败则安全中止。
FOCUS_GUARD       = True
FOCUS_GUARD_WAIT  = 10.0

# 多显示器：截图与框选覆盖整个虚拟屏幕。单屏机器上也安全。
MULTI_MONITOR     = True

# 日志
LOG_FILE          = "win_ocr_type.log"
LOG_DIR           = ""                 # 空 = 脚本所在目录
LOG_LEVEL         = "INFO"
LOG_MAX_BYTES     = 1024 * 1024
LOG_BACKUPS       = 3

# 输入后端：auto(默认 sendinput，可按窗口标题规则自动选) / sendinput / unicode
INPUT_MODE = "auto"

# 只有 INPUT_MODE=auto 时生效：目标窗口标题包含左侧子串时，强制用右侧后端
APP_RULES = [
    # ("某打字软件", "unicode"),   # 例：某软件忽略虚拟键码时改用 Unicode 注入
]
# ===============================================


_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
log = logging.getLogger("winocr")


def setup_logging():
    """控制台 + 滚动日志文件。控制台编码不可写时降级，不让日志本身崩掉。"""
    if getattr(log, "_winocr_ready", False):
        return
    log.setLevel(getattr(logging, str(LOG_LEVEL).upper(), logging.INFO))
    log.propagate = False
    fmt = logging.Formatter("[%(asctime)s] %(message)s", "%H:%M:%S")

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except Exception:
            pass
    if sys.stdout is not None:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        log.addHandler(sh)

    log_dir = LOG_DIR or _SCRIPT_DIR
    path = os.path.join(log_dir, LOG_FILE)
    try:
        fh = RotatingFileHandler(path, maxBytes=LOG_MAX_BYTES,
                                 backupCount=LOG_BACKUPS, encoding="utf-8",
                                 errors="backslashreplace")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s"))
        log.addHandler(fh)
        log._winocr_log_path = path
    except Exception as e:
        log.warning("日志文件不可写（%s），本次只输出到控制台。", e)
        log._winocr_log_path = None
    log._winocr_ready = True


user32   = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

INPUT_KEYBOARD    = 1
KEYEVENTF_KEYUP   = 0x0002
KEYEVENTF_UNICODE = 0x0004
SW_RESTORE        = 9

VK_SHIFT   = 0x10
VK_CONTROL = 0x11
VK_MENU    = 0x12
VK_RETURN  = 0x0D
VK_TAB     = 0x09
VK_BACK    = 0x08
VK_SPACE   = 0x20
VK_A       = 0x41
VK_C       = 0x43

CF_UNICODETEXT      = 13
WM_INPUTLANGCHANGEREQUEST = 0x0050
WM_CLOSE            = 0x0010

SM_XVIRTUALSCREEN  = 76
SM_YVIRTUALSCREEN  = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

BACKENDS = ("sendinput", "unicode")

kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalLock.restype  = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
user32.GetClipboardData.restype = ctypes.c_void_p
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
user32.GetKeyboardLayout.restype = ctypes.c_void_p
user32.GetWindowThreadProcessId.restype = wintypes.DWORD


# ==================== 完整 INPUT 结构 ====================
# 注意 dwExtraInfo 必须是 ULONG_PTR 宽度（这里用 LONG_PTR wintypes.LPARAM 表达），
# 用 POINTER(...) 只是碰巧在 64 位下同为 8 字节，语义不对。
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.LPARAM),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.LPARAM),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTunion(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]


_INPUT_SIZE = ctypes.sizeof(INPUT)


def _send_inputs(inputs):
    return user32.SendInput(len(inputs), ctypes.byref(inputs),
                            ctypes.sizeof(INPUT))


# ==================== 底层按键 ====================
def _vk_event(vk, up=False):
    """发送单个虚拟键按下/抬起事件"""
    inputs = (INPUT * 1)()
    inputs[0].type = INPUT_KEYBOARD
    inputs[0].u.ki.wVk = vk
    inputs[0].u.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
    _send_inputs(inputs)


def _unicode_event(code, up=False):
    """发送单个 Unicode 字符按下/抬起事件"""
    inputs = (INPUT * 1)()
    inputs[0].type = INPUT_KEYBOARD
    inputs[0].u.ki.wVk = 0
    inputs[0].u.ki.wScan = code
    inputs[0].u.ki.dwFlags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)
    _send_inputs(inputs)


def send_combo(vks):
    """一次按下/抬起一串组合键，如 Ctrl+A、Ctrl+C（自检回读用）。
    按下按给定顺序，抬起按相反顺序——Ctrl+V 这类组合键对释放顺序敏感。"""
    n = len(vks)
    inputs = (INPUT * (n * 2))()
    for i, vk in enumerate(vks):
        inputs[i].type = INPUT_KEYBOARD
        inputs[i].u.ki.wVk = vk
        inputs[i].u.ki.dwFlags = 0
    for i, vk in enumerate(reversed(vks)):
        inputs[n + i].type = INPUT_KEYBOARD
        inputs[n + i].u.ki.wVk = vk
        inputs[n + i].u.ki.dwFlags = KEYEVENTF_KEYUP
    _send_inputs(inputs)


def send_vk(vk, shift=False):
    """按下与抬起分离发送，间隔 KEY_DOWN_UP_DELAY 秒"""
    if shift:
        _vk_event(VK_SHIFT, False)
    _vk_event(vk, False)
    if KEY_DOWN_UP_DELAY > 0:
        time.sleep(KEY_DOWN_UP_DELAY)
    _vk_event(vk, True)
    if shift:
        _vk_event(VK_SHIFT, True)


def send_unicode_char(ch):
    """Unicode 注入一个字符（按下/抬起分离）；大于 0xFFFF 的字符按代理对发送"""
    code = ord(ch)
    if code <= 0xFFFF:
        _unicode_event(code, False)
        if KEY_DOWN_UP_DELAY > 0:
            time.sleep(KEY_DOWN_UP_DELAY)
        _unicode_event(code, True)
        return
    code -= 0x10000
    hi = 0xD800 + (code >> 10)
    lo = 0xDC00 + (code & 0x3FF)
    _unicode_event(hi, False)
    if KEY_DOWN_UP_DELAY > 0:
        time.sleep(KEY_DOWN_UP_DELAY)
    _unicode_event(lo, False)
    if KEY_DOWN_UP_DELAY > 0:
        time.sleep(KEY_DOWN_UP_DELAY)
    _unicode_event(lo, True)
    if KEY_DOWN_UP_DELAY > 0:
        time.sleep(KEY_DOWN_UP_DELAY)
    _unicode_event(hi, True)


def release_modifiers():
    for vk in (VK_SHIFT, VK_CONTROL, VK_MENU):
        _vk_event(vk, True)


def _buffer_after_punct():
    """标点后隐形缓冲：输入一个空格再退格删除。
    部分打字软件会把"标点后紧跟的汉字"吞掉并显示成标点，
    中间隔一个非汉字字符即可避免；空格+退格不留下任何可见痕迹。"""
    _unicode_event(0x20, False)
    time.sleep(0.03)
    _unicode_event(0x20, True)
    time.sleep(0.03)
    _vk_event(VK_BACK, False)
    time.sleep(0.03)
    _vk_event(VK_BACK, True)


def _buffer_dummy_char():
    """行尾标点后的缓冲：发一个普通汉字（触发换行并吸收吞字），再退格删掉。
    打字软件的换行只由"普通汉字"触发，空格不会；此处的字无论显示成什么
    都会被退格清理，不会留下痕迹。"""
    _unicode_event(0x7684, False)      # '的'
    time.sleep(0.05)
    _unicode_event(0x7684, True)
    time.sleep(0.10)
    _vk_event(VK_BACK, False)
    time.sleep(0.05)
    _vk_event(VK_BACK, True)


def _buffer_pre_punct():
    """行尾标点前的缓冲：先在行尾格放一个普通汉字触发正确位置的换行，
    再退格删掉。普通汉字在行尾会立即触发换行（标点不会，会晚一格）。"""
    _unicode_event(0x7684, False)      # '的'
    time.sleep(0.05)
    _unicode_event(0x7684, True)
    time.sleep(0.08)
    _vk_event(VK_BACK, False)
    time.sleep(0.05)
    _vk_event(VK_BACK, True)
    time.sleep(0.08)


def _cell_has_glyph(x, y, w, h):
    """检查屏幕指定区域是否有字形（存在深色像素）。
    检查失败返回 True（宁可不补打，避免误伤）。
    用 getextrema 代替逐像素双层循环：大选区下差几个数量级。"""
    try:
        img = ImageGrab.grab(bbox=(int(x), int(y), int(x + w), int(y + h)),
                             all_screens=MULTI_MONITOR)
        lo, _hi = img.convert("L").getextrema()
        return lo < 120
    except Exception:
        return True


def _verify_lineend_punct(ch, cell):
    """校验行尾标点是否输入成功；失败则补打标点+假字+退格"""
    x, y, w, h = cell
    for attempt in range(LINE_END_RETRY):
        if _cell_has_glyph(x, y, w, h):
            return
        log.info("  行尾标点 %r 校验未通过，补打第 %d 次", ch, attempt + 1)
        _unicode_event(ord(ch), False)
        time.sleep(0.05)
        _unicode_event(ord(ch), True)
        time.sleep(0.2)
        _buffer_dummy_char()
        time.sleep(0.3)


def _punct_buffer_positions(text):
    """返回"行尾标点"的位置集合。
    打字软件按内容换行，每行宽度不一定相同；
    任何 OCR 行末尾的标点都按行尾标点处理。"""
    lines = text.split("\n")
    if not lines:
        return set()
    out = set()
    pos = 0
    for ln in lines:
        if ln and ln[-1] in _PUNCT_CHARS:
            out.add(pos + len(ln) - 1)
        pos += len(ln) + 1
    return out


# ---------- 键码表 ----------
VK_MAP = {
    '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34,
    '5': 0x35, '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
    'a': 0x41, 'b': 0x42, 'c': 0x43, 'd': 0x44, 'e': 0x45,
    'f': 0x46, 'g': 0x47, 'h': 0x48, 'i': 0x49, 'j': 0x4A,
    'k': 0x4B, 'l': 0x4C, 'm': 0x4D, 'n': 0x4E, 'o': 0x4F,
    'p': 0x50, 'q': 0x51, 'r': 0x52, 's': 0x53, 't': 0x54,
    'u': 0x55, 'v': 0x56, 'w': 0x57, 'x': 0x58, 'y': 0x59,
    'z': 0x5A, ' ': 0x20,
    '-': 0xBD, '=': 0xBB, '[': 0xDB, ']': 0xDD, '\\': 0xDC,
    ';': 0xBA, "'": 0xDE, ',': 0xBC, '.': 0x0E, '/': 0xBF, '`': 0xC0,
}
SHIFT_MAP = {
    '!': '1', '@': '2', '#': '3', '$': '4', '%': '5',
    '^': '6', '&': '7', '*': '8', '(': '9', ')': '0',
    '_': '-', '+': '=', '{': '[', '}': ']', '|': '\\',
    ':': ';', '"': "'", '<': ',', '>': '.', '?': '/',
    '~': '`',
}


def send_char(ch):
    if ASCII_AS_VK and ch.isascii():
        low = ch.lower()
        if low in VK_MAP:
            send_vk(VK_MAP[low], shift=ch.isupper())
            return
        if ch in SHIFT_MAP:
            send_vk(VK_MAP[SHIFT_MAP[ch]], shift=True)
            return
    send_unicode_char(ch)


# ==================== 剪贴板（仅用于自检回读校验，不参与输入） ====================
def set_clipboard_text(text, retries=20, delay=0.05):
    text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    opened = False
    for _ in range(retries):
        if user32.OpenClipboard(None):
            opened = True
            break
        time.sleep(delay)
    if not opened:
        return False
    try:
        if not user32.EmptyClipboard():
            return False
        buf = text.encode("utf-16-le") + b"\x00\x00"
        hmem = kernel32.GlobalAlloc(0x0042, len(buf))
        if not hmem:
            return False
        p = kernel32.GlobalLock(hmem)
        if not p:
            kernel32.GlobalFree(hmem)
            return False
        ctypes.memmove(p, buf, len(buf))
        kernel32.GlobalUnlock(hmem)
        if not user32.SetClipboardData(CF_UNICODETEXT, hmem):
            kernel32.GlobalFree(hmem)
            return False
        return True
    finally:
        user32.CloseClipboard()


def get_clipboard_text():
    """读取剪贴板文本；剪贴板里不是文本(如图片/文件)时返回 None"""
    if not user32.OpenClipboard(None):
        return None
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = kernel32.GlobalLock(h)
        if not p:
            return None
        try:
            return ctypes.wstring_at(p)
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


# ==================== OCR 文本清理 ====================
_CJK_CLASS = r'\u2000-\u206f\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff' \
             r'\uf900-\ufaff\uff00-\uffef'


def clean_ocr_text(text):
    """清理 OCR 空白：删除任何与中文/全角/引号等标点相邻的空格，
    但保留换行（换行用来判断打字软件的行尾位置）。
    打字软件按格子排版，OCR 常把格子间隙识别成空格；
    引号“”等标点旁边的空格同样要清掉，否则会变成打字软件里的空格单元格，
    导致一行没打完就提前换行。英文单词之间的空格保留。

    LAYOUT_MODE="layout" 时不动空格——那些空格是按字框坐标重建出来的真实版面，
    删掉就等于把保真模式的意义抹掉了。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if CLEAN_OCR_TEXT and LAYOUT_MODE != "layout":
        text = re.sub(r'(?<=[' + _CJK_CLASS + r'])[ \t\u3000\f]+|' +
                      r'[ \t\u3000\f]+(?=[' + _CJK_CLASS + r'])', '', text)
    if STRIP_LEADING_PUNCT:
        # 只去掉句末类标点（框选多框进去的上句句号/右引号等），
        # 保留 ，；：“ 等句首标点——文章分两段框选时它们是正文的一部分
        text = text.lstrip("。！？…”’ \t\n")
    for wrong, right in OCR_FIX_MAP.items():
        text = text.replace(wrong, right)
    return text


# ==================== 版面重建 ====================
class Word:
    """OCR 识别出的一个词（中文一般就是一个字），带它在放大图上的像素框"""
    __slots__ = ("x", "y", "w", "h", "text")

    def __init__(self, x, y, w, h, text):
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.text = text

    def __repr__(self):
        return f"Word({self.x:.0f},{self.y:.0f} {self.text!r})"


def _median(values, default=1.0):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return default
    return vals[len(vals) // 2] or default


def group_words(result):
    """把 winocr 的词框整理成按阅读顺序排好的行列表。
    winocr 返回的行顺序偶尔会乱（看错行），分行不靠它自己给的 lines，
    而是按坐标重排：只要与当前行的任一单词垂直有重叠就算同一行
    （标点比汉字偏下，纯按 y 递增切行会把一行切成两行）。
    返回 [[Word, ...], ...]；识别不到任何带坐标的词时返回 [[]]。"""
    items = []
    for line in result.lines:
        for wd in line.words:
            r = getattr(wd, "bounding_rect", None)
            if r is None:
                continue
            items.append(Word(float(r.x), float(r.y),
                              float(r.width), float(r.height), wd.text))
    if not items:
        return []
    items.sort(key=lambda v: (v.y, v.x))

    med_h = _median([v.h for v in items])
    tol = max(4.0, med_h * 0.5)

    rows = []
    cur = []
    for v in items:
        if not cur:
            cur.append(v)
            continue
        cy = v.y + v.h / 2.0
        same = False
        for o in cur:
            if v.y < o.y + o.h and v.y + v.h > o.y:      # 垂直重叠 → 同一行
                same = True
                break
            if abs(cy - (o.y + o.h / 2.0)) <= tol:        # 中心很近 → 同一行
                same = True
                break
        if same:
            cur.append(v)
        else:
            rows.append(cur)
            cur = [v]
    if cur:
        rows.append(cur)

    for row in rows:
        row.sort(key=lambda v: v.x)      # 行内按 x 排序还原阅读顺序
    return rows


def _gap_spaces(prev, cur, unit):
    """两个相邻词之间应该还原几个空格。
    两种量法：
      - 普通词用"前词右边缘到后词左边缘"的框间隙；
      - 只要有一侧是中文标点，就按"标点占一整格"来量（下一词 x - 标点 x - 字宽）。
    原因：OCR 给的标点框往往只有墨迹那么宽（"、"可能只有 4px），
    拿框宽量会把正常的中文排版判成大空隙，插出一堆假空格。
    两个标点相邻（如"：“"）永远不插空格。"""
    if prev.text in _PUNCT_CHARS and cur.text in _PUNCT_CHARS:
        return 0
    if prev.text in _PUNCT_CHARS or cur.text in _PUNCT_CHARS:
        gap = cur.x - prev.x - unit
    else:
        gap = cur.x - (prev.x + prev.w)
    if gap <= unit * SPACE_MIN_RATIO:
        return 0
    return min(SPACE_MAX, max(1, int(round(gap / unit))))


def render_rows(rows, mode):
    """把行列表渲染成文本行。
    mode="clean"  —— 直接接词，不加任何空格（打字软件用：空格会占格子）
    mode="layout" —— 按字框坐标重建版面：词语之间的横向间隙还原成空格，
                     行首缩进还原成前导空格，行距过大处插入空行
    返回 (行文本列表, 每行的行尾 Word（空行为 None）)，两个列表等长。"""
    if not rows:
        return [], []
    if mode != "layout":
        return (["".join(v.text for v in row) for row in rows],
                [row[-1] if row else None for row in rows])

    all_words = [v for row in rows for v in row]
    # 中文一个字的宽度约等于字高；用它当"一个空格"的度量
    unit = max(1.0, _median([v.h for v in all_words]))
    # 缩进基准用"所有行首 x 里最小的那个"：正文行的行首就是基准，
    # 缩进行的行首会被算成正的 indent。全篇都缩进时基准即缩进行首，结果是不缩进
    # （没有正文行作对照，这时本来也判断不出"缩进"）。
    # 行首是标点时它的 x 可能比正文略左几个像素，但远小于 INDENT_MIN_RATIO，
    # 不会把正文误判成有缩进。
    left_edge = min(row[0].x for row in rows if row)
    line_h = _median([_median([v.h for v in row]) for row in rows])

    lines = []
    out_ends = []
    prev_bottom = None
    for row in rows:
        if not row:
            continue
        # --- 行距过大 → 插入空行（最多 3 行，免得一个噪声框撑出一屏空行）---
        # 用向下取整：OCR 的字框高度通常比实际行距略大，round() 会多插空行。
        if prev_bottom is not None:
            gap = min(v.y for v in row) - prev_bottom
            if gap > line_h * BLANK_LINE_RATIO:
                blanks = min(BLANK_LINE_MAX,
                             max(1, int(gap / max(1.0, line_h)) - 1))
                lines.extend([""] * blanks)
                out_ends.extend([None] * blanks)
        # --- 行首缩进 ---
        indent_px = row[0].x - left_edge
        indent = 0
        if indent_px > unit * INDENT_MIN_RATIO:
            indent = min(INDENT_MAX, int(round(indent_px / unit)))
        buf = [" " * indent] if indent else []
        # --- 词语之间的间隙 ---
        for i, v in enumerate(row):
            if i:
                spaces = _gap_spaces(row[i - 1], v, unit)
                if spaces:
                    buf.append(" " * spaces)
            buf.append(v.text)
        lines.append("".join(buf))
        out_ends.append(row[-1])
        prev_bottom = max(v.y + v.h for v in row)
    return lines, out_ends


def analyze_result(result, mode=None):
    """整理识别结果：分行 → 按模式渲染 → 去重。
    返回 (文本, 每行行尾坐标列表)。"""
    mode = mode or LAYOUT_MODE
    rows = group_words(result)
    if not rows:
        return result.text, []
    lines, ends = render_rows(rows, mode)
    lines, ends = dedupe_lines(lines, ends)
    return "\n".join(lines), ends


def reorder_result(result):
    """兼容旧调用：只要文本与行尾坐标（等同 clean 渲染，不做去重）。"""
    rows = group_words(result)
    if not rows:
        return result.text, []
    lines, ends = render_rows(rows, "clean")
    return "\n".join(lines), ends



def _near_duplicate(prev, cur):
    """判断 cur 是不是 prev 的"错位副本"。
    打字软件里"原文行"和"已输入行"上下相邻，已输入行往往从下一格开始，
    于是两行高度重叠、只在首尾差一两个字。这种行敲进去就是重复内容，
    但用"严格前缀"判断抓不到，所以再看最长连续相同段占多长。
    阈值保守（85%），诗词叠句那种"蒹葭苍苍/蒹葭萋萋"不会被误判。"""
    if not prev or not cur:
        return False
    la, lb = len(prev), len(cur)
    mx = max(la, lb)
    if abs(la - lb) > max(4, int(mx * 0.35)):     # 长度差太多，不可能是同一行的副本
        return False
    m = difflib.SequenceMatcher(None, prev, cur).find_longest_match(0, la, 0, lb)
    return m.size >= max(6, int(mx * DEDUPE_RATIO))


def dedupe_lines(lines, ends):
    """去掉与上一行内容重复的行（框进"已输入行"时自动跳过），同步维护行尾坐标。
    两种重复都处理：完全前缀重复，以及两栏错位重叠。"""
    if not DEDUPE_SIMILAR_LINES:
        return lines, ends
    out = []
    out_ends = []
    for i, ln in enumerate(lines):
        norm = ln.replace(" ", "")
        prev = out[-1].replace(" ", "") if out else ""
        if norm and prev:
            if len(norm) >= DEDUPE_MIN_LEN and len(norm) <= len(prev) and \
                    prev.startswith(norm[:6]):
                log.debug("跳过重复行: %r", ln)
                continue
            if DEDUPE_NEAR_DUPLICATE and _near_duplicate(prev, norm):
                log.debug("跳过错位重复行: %r", ln)
                continue
        out.append(ln)
        out_ends.append(ends[i] if i < len(ends) else None)
    return out, out_ends


_PUNCT_CHARS = set("，。；：？！、“”‘’（）《》〈〉—…·")

# 暂停/继续控制：set = 运行中，clear = 已暂停（跨线程安全）
_PAUSE_LOCK = threading.Event()
_PAUSE_LOCK.set()


def _wait_if_paused():
    """暂停时阻塞等待，按 F12 恢复后继续"""
    if _PAUSE_LOCK.is_set():
        return
    log.info("  输入已暂停（按 F12 继续）...")
    _PAUSE_LOCK.wait()
    log.info("  继续输入。")


class InputAborted(Exception):
    """输入过程中检测到异常，安全中止"""


def _ensure_target_foreground(hwnd, typed):
    """目标窗口不在前台时先尝试拉回；拉不回来就等，等超时抛 InputAborted。
    宁可停下让用户处理，也不要把文字盲打进别的窗口。"""
    if not FOCUS_GUARD or not hwnd:
        return
    if get_foreground_window() == hwnd:
        return
    log.warning("前台窗口已不是目标窗口，暂停输入（已输入 %d 字）", typed)
    deadline = time.monotonic() + max(0.0, FOCUS_GUARD_WAIT)
    while True:
        if force_foreground(hwnd):
            log.info("已恢复目标窗口，继续输入。")
            return
        if time.monotonic() >= deadline:
            raise InputAborted(
                f"目标窗口 {FOCUS_GUARD_WAIT:.0f} 秒内没能回到前台，已安全中止")
        time.sleep(0.25)


# ==================== 输入后端 ====================
def _type_stream(text, send_one, hwnd=None, end_cells=None,
                 interval=TYPE_INTERVAL):
    """两种后端共用的逐字输入循环；send_one 决定单个字符怎么发。
    返回实际发送的字符数（含换行/制表符），用于日志与中止提示。"""
    text = text.replace("\r\n", "\n")
    full_end = _punct_buffer_positions(text)
    typed = 0
    k = 0
    for i, ch in enumerate(text):
        _wait_if_paused()
        _ensure_target_foreground(hwnd, typed)
        if ch == "\n":
            k += 1
            if NEWLINE_AS_ENTER:
                send_vk(VK_RETURN)
                typed += 1
            if interval > 0:
                time.sleep(interval)
            continue
        if ch == "\t":
            send_vk(VK_TAB)
            typed += 1
            if interval > 0:
                time.sleep(interval)
            continue
        if ch in _PUNCT_CHARS and i in full_end:
            # 标点统一处理：前置假字触发换行→退格→标点→后置假字吸收吞字→退格
            if PUNCT_BUFFER == "space":
                _buffer_pre_punct()
            send_one(ch)
            typed += 1
            if interval > 0:
                time.sleep(interval)
            if LINE_END_WAIT > 0:
                time.sleep(LINE_END_WAIT)
            if PUNCT_BUFFER == "space":
                _buffer_dummy_char()
            if LINE_END_VERIFY and end_cells and k < len(end_cells) \
                    and end_cells[k]:
                _verify_lineend_punct(ch, end_cells[k])
            continue
        send_one(ch)
        typed += 1
        if interval > 0:
            time.sleep(interval)
        if ch in _PUNCT_CHARS:
            if PUNCT_EXTRA_DELAY > 0:
                time.sleep(PUNCT_EXTRA_DELAY)
            if PUNCT_BUFFER == "space":
                _buffer_after_punct()
    return typed


def type_text_sendinput(text, hwnd=None, end_cells=None, interval=TYPE_INTERVAL):
    """后端 1：逐字模拟按键。仅当文本含英文字符时切换输入法，纯中文不切换"""
    release_modifiers()
    orig = None
    has_ascii = any(ch.isascii() and ch not in "\r\n\t" for ch in text)
    if SWITCH_IME_FOR_SENDINPUT and has_ascii and hwnd:
        tid = user32.GetWindowThreadProcessId(hwnd, None)
        if tid:
            orig = user32.GetKeyboardLayout(tid)
            en = user32.LoadKeyboardLayoutW("00000409", 0x0001)
            if en:
                user32.SendMessageW(hwnd, WM_INPUTLANGCHANGEREQUEST, 0, en)
                time.sleep(0.35)
    try:
        return _type_stream(text, send_char, hwnd=hwnd, end_cells=end_cells,
                            interval=interval)
    finally:
        if orig and hwnd:
            user32.SendMessageW(hwnd, WM_INPUTLANGCHANGEREQUEST, 0, int(orig))


def type_text_unicode(text, hwnd=None, end_cells=None, interval=TYPE_INTERVAL):
    """后端 2：全部字符走 Unicode 注入，不走输入法"""
    release_modifiers()
    return _type_stream(text, send_unicode_char, hwnd=hwnd, end_cells=end_cells,
                        interval=interval)


def input_text(text, mode, hwnd=None, end_cells=None):
    if mode == "sendinput":
        return type_text_sendinput(text, hwnd=hwnd, end_cells=end_cells)
    if mode == "unicode":
        return type_text_unicode(text, hwnd=hwnd, end_cells=end_cells)
    raise ValueError(f"未知输入后端: {mode}")


def resolve_mode(title):
    mode = INPUT_MODE
    if mode == "auto":
        mode = "sendinput"
        if title:
            for sub, m in APP_RULES:
                if sub.lower() in title.lower():
                    mode = m
                    break
    if mode not in BACKENDS:
        mode = "sendinput"
    return mode


def looks_suspicious(text):
    """CONFIRM_MODE="auto" 时的粗筛：出现这些情况就建议看一眼再输入。
    只挑"几乎肯定是识别问题"的特征，不追求全，追求不误报太多。"""
    if not text:
        return False
    if len(text.strip()) <= 2:
        return True
    if "\n\n" in text:
        return True
    for _wrong in OCR_FIX_MAP:
        if _wrong in text:
            return True
    # 控制字符 / 私用区 / 代理项残片，基本可以断定是识别错误
    if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\u200b-\u200f\ue000-\uf8ff\ud800-\udfff]', text):
        return True
    return False


# ==================== 窗口 / 焦点 ====================
def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return True


def get_foreground_window():
    return user32.GetForegroundWindow()


def get_window_title(hwnd):
    if not hwnd:
        return ""
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def virtual_screen_rect():
    """整个虚拟桌面（含所有显示器）的屏幕矩形。单屏时等于主屏。"""
    gsm = user32.GetSystemMetrics
    return (gsm(SM_XVIRTUALSCREEN), gsm(SM_YVIRTUALSCREEN),
            gsm(SM_CXVIRTUALSCREEN), gsm(SM_CYVIRTUALSCREEN))


def force_foreground(hwnd):
    if not hwnd:
        return False
    try:
        if user32.GetForegroundWindow() == hwnd:
            return True

        current_thread = kernel32.GetCurrentThreadId()
        fg = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)

        attached = []
        if fg_thread and fg_thread != current_thread and \
                user32.AttachThreadInput(current_thread, fg_thread, True):
            attached.append(fg_thread)
        if target_thread and target_thread != current_thread and \
                user32.AttachThreadInput(current_thread, target_thread, True):
            attached.append(target_thread)

        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.BringWindowToTop(hwnd)
        ok = bool(user32.SetForegroundWindow(hwnd))
        if not ok:
            # Alt 技巧：发送一次 Alt 按键，解除系统对 SetForegroundWindow 的限制
            send_vk(VK_MENU)
            time.sleep(0.05)
            ok = bool(user32.SetForegroundWindow(hwnd))
        try:
            user32.SetFocus(hwnd)
        except Exception:
            pass

        for t in attached:
            user32.AttachThreadInput(current_thread, t, False)
        return user32.GetForegroundWindow() == hwnd
    except Exception as e:
        log.warning("force_foreground 失败: %s", e)
        return False


# ==================== 主程序 ====================
class WinOCRType:

    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("win_ocr_type v5")
        self.q = queue.Queue()
        self._busy = False
        self._busy_lock = threading.Lock()
        self.listener = None
        self.last_hwnd = None
        self.last_title = ""
        self.override_mode = None

    # ---------- 状态 ----------
    def current_mode(self):
        if self.override_mode:
            return self.override_mode
        return resolve_mode(self.last_title)

    def _try_begin_busy(self):
        with self._busy_lock:
            if self._busy:
                return False
            self._busy = True
            return True

    def _end_busy(self):
        with self._busy_lock:
            self._busy = False

    # ---------- 键盘监听 ----------
    def start_listener(self):
        def _on_press(key):
            try:
                if key == HOTKEY_KEY:
                    self.on_hotkey()
                elif key == TOGGLE_KEY:
                    self.on_toggle()
                elif key == REHOOK_KEY:
                    self.on_rehook()
                elif key == PAUSE_KEY:
                    self.on_pause()
                elif key == QUIT_KEY:
                    self.on_quit()
            except Exception as e:
                log.debug("热键处理异常: %s", e)

        self.listener = keyboard.Listener(on_press=_on_press)
        self.listener.daemon = True
        self.listener.start()

    def run(self):
        self.start_listener()

        log.info("=" * 60)
        log.info("Win11 截图 OCR 自动输入工具 v5")
        log.info("sizeof(INPUT) = %d  (应为 40)", _INPUT_SIZE)
        log.info("热键：%s 触发 | %s 切换后端 | %s 重挂监听 | %s 暂停/继续 | %s 退出",
                 HOTKEY_KEY, TOGGLE_KEY, REHOOK_KEY, PAUSE_KEY, QUIT_KEY)
        log.info("后端：sendinput=逐字模拟(默认) / unicode=Unicode注入")
        log.info("版面：%s（clean=紧凑 / layout=保真空格缩进空行）", LAYOUT_MODE)
        log.info("确认：%s（always=每次确认 / auto=可疑时确认 / off=直接输入）",
                 CONFIRM_MODE)
        log.info("用法：在目标输入框里按 F9 -> 框选文字 -> 松手")
        if LAYOUT_MODE == "layout" and not NEWLINE_AS_ENTER:
            log.warning("提示：LAYOUT_MODE=layout 但 NEWLINE_AS_ENTER=False，")
            log.warning("      换行不会被输入，结果会是一整行带空格。想保留换行请把")
            log.warning("      NEWLINE_AS_ENTER 改成 True（在打字软件里别这么做）。")
        if getattr(log, "_winocr_log_path", None):
            log.info("日志文件：%s", log._winocr_log_path)
        log.info("=" * 60)
        if not is_admin():
            log.warning("提示：本工具当前不是管理员运行。若目标软件以管理员身份运行，")
            log.warning("      F9 会失效且输入不进字，请用管理员身份运行本工具。")

        self.root.after(50, self.poll)
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            pass
        finally:
            if self.listener:
                try:
                    self.listener.stop()
                except Exception:
                    pass
            try:
                self.root.destroy()
            except Exception:
                pass
            log.info("已退出。")

    def on_hotkey(self):
        if not self._try_begin_busy():
            log.debug("上一轮还没结束，忽略本次热键")
            return
        self.last_hwnd = get_foreground_window()
        self.last_title = get_window_title(self.last_hwnd)
        log.info("热键触发，目标窗口: [%s]", self.last_title)
        self.q.put(True)

    def on_toggle(self):
        idx = (BACKENDS.index(self.current_mode()) + 1) % len(BACKENDS)
        self.override_mode = BACKENDS[idx]
        log.info("输入后端已切换为: %s", self.override_mode)

    def on_rehook(self):
        """重新挂载键盘监听：某些软件会抢先吞掉按键，重挂后我们的监听排到最前"""
        self.q.put(("rehook",))

    def on_pause(self):
        """暂停/继续输入（F12），打字过程中随时生效"""
        if _PAUSE_LOCK.is_set():
            _PAUSE_LOCK.clear()
            log.info("已暂停输入（按 F12 继续）。")
        else:
            _PAUSE_LOCK.set()
            log.info("已恢复输入。")

    def on_quit(self):
        log.info("收到退出热键。")
        self.q.put(("quit",))

    def do_rehook(self):
        try:
            if self.listener:
                self.listener.stop()
        except Exception:
            pass
        self.start_listener()
        log.info("键盘监听已重新挂载。现在切回目标软件按 F9 试试。")

    def poll(self):
        try:
            item = self.q.get_nowait()
            if item == ("rehook",):
                self.do_rehook()
            elif item == ("quit",):
                self.root.quit()
            else:
                self.flow()
        except queue.Empty:
            pass
        self.root.after(50, self.poll)

    # ---------- 主流程 ----------
    def flow(self):
        t0 = time.perf_counter()
        try:
            release_modifiers()
            time.sleep(0.15)

            full, rect = self.grab_screen()
            box = self.select_region(full, rect)
            if not box:
                log.info("已取消。")
                return

            img = full.crop(box)
            if img.width < 3 or img.height < 3:
                log.info("选区太小。")
                return

            log.info("识别中... (%dx%d)", img.width, img.height)
            text, end_cells = self.ocr(img, origin=(box[0] + rect[0],
                                                    box[1] + rect[1]))
            if not text:
                log.info("未识别到文字。")
                return
            text = clean_ocr_text(text).strip("\n")
            if not text.strip():
                log.info("清理后没有可输入的文字。")
                return
            log.info("识别完成，用时 %.2f 秒", time.perf_counter() - t0)
            log.info("识别结果：")
            log.info("-" * 55)
            for line in text.split("\n"):
                log.info("%s", line if line else " ")
            log.info("-" * 55)

            mode = resolve_mode(self.last_title)

            if CONFIRM_MODE == "always" or \
                    (CONFIRM_MODE == "auto" and looks_suspicious(text)):
                info = (f"后端 {mode} | 版面 {LAYOUT_MODE} | "
                        f"{len(text.splitlines())} 行 | {len(text)} 字 | "
                        f"目标 [{self.last_title}]")
                original = text
                edited = self.confirm_text(text, info)
                if edited is None:
                    log.info("已取消本次输入。")
                    return
                edited = edited.replace("\r\n", "\n")
                if edited.strip() != original.strip():
                    end_cells = []      # 改过字就和原坐标对不上了，关掉行尾校验
                text = edited
                if not text.strip():
                    log.info("文本被改空了，取消输入。")
                    return

            log.info("输入后端: %s  ->  目标窗口: [%s]", mode, self.last_title)

            if RESTORE_FOCUS and self.last_hwnd:
                log.info("恢复焦点...")
                ok = force_foreground(self.last_hwnd)
                time.sleep(0.5)
                if not ok:
                    log.warning("警告: 未能确认目标窗口在前台，已取消本次输入。")
                    log.warning("      请手动点击目标输入框后重按热键。")
                    return

            time.sleep(AUTO_START_DELAY)
            log.info("开始输入...")
            typed = input_text(text, mode, hwnd=self.last_hwnd,
                               end_cells=end_cells)
            log.info("已输入完成：%d 字，总用时 %.2f 秒",
                     typed or 0, time.perf_counter() - t0)
        except InputAborted as e:
            log.warning("输入中止：%s", e)
        except Exception as e:
            log.exception("出错：%s", e)
        finally:
            self._end_busy()

    # ---------- 抓屏 ----------
    def _screen_target(self):
        """这次框选要覆盖哪块屏：多屏可用就覆盖整个虚拟桌面，否则主屏。
        返回 (x, y, w, h, 是否多屏)。"""
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        if MULTI_MONITOR:
            vx, vy, vw, vh = virtual_screen_rect()
            if vw > 0 and vh > 0 and (vw, vh) != (sw, sh):
                return vx, vy, vw, vh, True
        return 0, 0, sw, sh, False

    def grab_screen(self):
        """抓取截图，返回 (图像, 屏幕矩形 (x,y,w,h,是否多屏))。
        关键：先定矩形再按矩形抓，保证"图"和"遮罩窗口"是同一块区域；
        多屏抓取失败就退回主屏并重新抓主屏图，不会出现尺寸错配。"""
        x, y, w, h, multi = self._screen_target()
        if multi:
            try:
                img = ImageGrab.grab(bbox=(x, y, x + w, y + h),
                                     all_screens=True)
                if img.size == (w, h):
                    log.info("截图：多屏模式 %dx%d @ (%d,%d)", w, h, x, y)
                    return img, (x, y, w, h, True)
                log.warning("多屏截图尺寸不符（期望 %dx%d，实际 %s），退回主屏。",
                            w, h, img.size)
            except Exception as e:
                log.warning("多屏截图失败（%s），退回主屏。", e)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        return ImageGrab.grab(), (0, 0, sw, sh, False)

    # ---------- 框选 ----------
    def select_region(self, full, rect):
        """在 full 截图上框选，返回 full 图坐标系下的 (l,t,r,b)；取消返回 None。
        rect = (x, y, w, h, 是否多屏)，就是 grab_screen 抓图时用的那块屏幕。"""
        result = {"box": None}
        ox, oy, ow, oh, multi = rect

        top = tk.Toplevel(self.root)
        top.attributes("-topmost", True)
        if multi:
            top.overrideredirect(True)
            top.geometry(f"{ow}x{oh}+{ox:+d}+{oy:+d}")
            win_w, win_h = ow, oh
        else:
            top.attributes("-fullscreen", True)
            win_w = self.root.winfo_screenwidth()
            win_h = self.root.winfo_screenheight()
        top.configure(cursor="crosshair")
        top.focus_force()

        if (full.width, full.height) != (win_w, win_h):
            disp = full.resize((win_w, win_h), Image.LANCZOS)
        else:
            disp = full

        tkimg = ImageTk.PhotoImage(disp)
        canvas = tk.Canvas(top, width=win_w, height=win_h,
                           highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        canvas.create_image(0, 0, anchor="nw", image=tkimg)
        canvas.image = tkimg

        canvas.create_text(
            win_w // 2, 40,
            text=f"拖拽鼠标框选要识别的文字，Esc 取消 | 输入后端: {self.current_mode()}",
            fill="#ff3b30",
            font=("Microsoft YaHei", 16, "bold"),
        )

        state = {"sx": 0, "sy": 0, "rid": None}

        def on_press(e):
            state["sx"], state["sy"] = e.x, e.y
            if state["rid"]:
                canvas.delete(state["rid"])
                state["rid"] = None

        def on_drag(e):
            x1, y1 = state["sx"], state["sy"]
            x2, y2 = e.x, e.y
            if state["rid"]:
                canvas.delete(state["rid"])
            state["rid"] = canvas.create_rectangle(
                x1, y1, x2, y2, outline="#ff3b30", width=2)

        def on_release(e):
            x1, y1 = state["sx"], state["sy"]
            x2, y2 = e.x, e.y
            left, top_ = min(x1, x2), min(y1, y2)
            right, bottom = max(x1, x2), max(y1, y2)

            if right - left < 3 or bottom - top_ < 3:
                result["box"] = None
            else:
                # 窗口坐标 → full 图坐标
                rx = full.width / max(1, win_w)
                ry = full.height / max(1, win_h)
                result["box"] = (
                    int(left * rx), int(top_ * ry),
                    int(right * rx), int(bottom * ry),
                )
            top.destroy()

        def cancel(_=None):
            result["box"] = None
            top.destroy()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        top.bind("<Escape>", cancel)
        top.protocol("WM_DELETE_WINDOW", cancel)

        top.update_idletasks()
        top.lift()
        top.focus_force()

        self.root.wait_window(top)
        return result["box"]

    # ---------- 确认窗 ----------
    def confirm_text(self, text, info):
        """可编辑确认窗：看清、改错字，Ctrl+Enter 返回文本，Esc 返回 None。"""
        result = {"text": None}
        top = tk.Toplevel(self.root)
        top.title("确认识别结果 - win_ocr_type v5")
        top.attributes("-topmost", True)
        top.configure(bg="#1e1e1e")
        top.minsize(560, 260)

        tk.Label(top, text=info, bg="#1e1e1e", fg="#cccccc", anchor="w",
                 justify="left", font=("Microsoft YaHei", 10)).pack(
            fill="x", padx=10, pady=(8, 4))

        wrap = tk.Frame(top, bg="#1e1e1e")
        wrap.pack(fill="both", expand=True, padx=10)
        box = tk.Text(wrap, wrap="word", undo=True, bg="#252526", fg="#eeeeee",
                      insertbackground="#eeeeee", selectbackground="#0e639c",
                      relief="flat", font=("Microsoft YaHei", 13),
                      padx=10, pady=8, spacing1=2, spacing3=2)
        sb = tk.Scrollbar(wrap, command=box.yview)
        box.configure(yscrollcommand=sb.set)
        box.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        box.insert("1.0", text)

        bar = tk.Frame(top, bg="#1e1e1e")
        bar.pack(fill="x", padx=10, pady=8)
        tk.Label(bar, text="Ctrl+Enter 输入    Esc 取消    可直接改错字",
                 bg="#1e1e1e", fg="#8a8a8a",
                 font=("Microsoft YaHei", 10)).pack(side="left")

        def ok(_=None):
            result["text"] = box.get("1.0", "end-1c")
            top.destroy()

        def cancel(_=None):
            result["text"] = None
            top.destroy()

        tk.Button(bar, text="输入 (Ctrl+Enter)", command=ok, width=16,
                  bg="#0e639c", fg="white", relief="flat",
                  activebackground="#1177bb",
                  activeforeground="white").pack(side="right", padx=(8, 0))
        tk.Button(bar, text="取消 (Esc)", command=cancel, width=12,
                  bg="#3a3d41", fg="white", relief="flat",
                  activebackground="#4a4d51",
                  activeforeground="white").pack(side="right")

        top.bind("<Escape>", cancel)
        top.bind("<Control-Return>", ok)
        top.protocol("WM_DELETE_WINDOW", cancel)

        top.update_idletasks()
        w = max(top.winfo_reqwidth(), 620)
        h = max(top.winfo_reqheight(), 340)
        sw = top.winfo_screenwidth()
        sh = top.winfo_screenheight()
        top.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2 - 60)}")
        top.lift()
        top.focus_force()
        box.focus_set()
        box.mark_set("insert", "end-1c")

        self.root.wait_window(top)
        return result["text"]

    # ---------- OCR ----------
    def ocr(self, img, origin=(0, 0)):
        gray = ImageOps.grayscale(img)
        if AUTO_INVERT:
            mean = ImageStat.Stat(gray).mean[0]
            if mean < INVERT_THRESHOLD:
                # 深色主题下是浅字深底，winocr 对这类图识别率明显更差
                log.info("选区偏暗（平均亮度 %.0f < %d），先反色再识别",
                         mean, INVERT_THRESHOLD)
                gray = ImageOps.invert(gray)
        # 灰度 + 自动对比度 + 放大：实测字准确率最高（7 张真实截图基准测试）
        img = ImageOps.autocontrast(gray)
        if OCR_UPSCALE > 1:
            img = img.resize((img.width * OCR_UPSCALE, img.height * OCR_UPSCALE),
                             Image.LANCZOS)
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                winocr.recognize_pil(img, OCR_LANG)
            )
        finally:
            loop.close()
        # 分行 → 按 LAYOUT_MODE 渲染（clean/layout）→ 去重，一次做齐
        text, ends = analyze_result(result)
        end_cells = []
        s = float(OCR_UPSCALE)
        for e in ends:
            if e is None:
                end_cells.append(None)
                continue
            end_cells.append((e.x / s + origin[0],
                              e.y / s + origin[1] + TYPED_ROW_OFFSET,
                              e.w / s, e.h / s))
        # 只去首尾空行：layout 模式下首行的缩进空格不能被 strip 掉
        return text.strip("\n"), end_cells

    # ---------- 自检 ----------
    def selftest(self):
        return selftest()


# ==================== 自检：记事本输入回读校验 ====================
def _enum_windows():
    wins = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            wins.append(int(hwnd))
        return True

    user32.EnumWindows(_cb, 0)
    return wins


def _class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def enum_notepad_windows():
    return [h for h in _enum_windows()
            if _class_name(h).lower() == "notepad"]


def wait_new_notepad(before, timeout=12.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        cur = [h for h in enum_notepad_windows() if h not in before]
        if cur:
            return cur[0]
        time.sleep(0.25)
    return None


def select_all_copy_read():
    send_combo([VK_CONTROL, VK_A])
    time.sleep(0.15)
    send_combo([VK_CONTROL, VK_C])
    time.sleep(0.35)
    return get_clipboard_text() or ""


def clear_editor():
    send_combo([VK_CONTROL, VK_A])
    time.sleep(0.1)
    send_vk(VK_BACK)
    time.sleep(0.1)


def normalize(s):
    return (s or "").replace("\r\n", "\n").rstrip("\n")


def selftest():
    log.info("=" * 60)
    log.info("自检开始：将打开记事本，用每种后端输入一遍并回读校验")
    log.info("=" * 60)
    backup = get_clipboard_text()
    new_hwnd = None
    try:
        before = set(enum_notepad_windows())
        subprocess.Popen(["notepad.exe"],
                         stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        new_hwnd = wait_new_notepad(before, timeout=12)
        if not new_hwnd:
            log.error("未检测到记事本窗口，自检中止。")
            log.error("提示：若在受限/沙箱环境内运行，Windows 打包版记事本可能无法弹出；")
            log.error("      请在正常桌面环境直接运行本脚本 --selftest 即可。")
            return False
        log.info("记事本窗口: [%s] hwnd=%#x", get_window_title(new_hwnd), new_hwnd)

        if not force_foreground(new_hwnd):
            log.error("无法将记事本置为前台窗口，为避免误输入到其他窗口，自检中止。")
            return False
        time.sleep(0.8)

        sample = "Hello 你好，自动输入 OK! 123\n第二行 line2"
        expected = normalize(sample.replace("\n", "")) if not NEWLINE_AS_ENTER \
            else normalize(sample)
        all_ok = True
        for mode in BACKENDS:
            clear_editor()
            log.info("--- 后端 [%s] 输入中... ---", mode)
            input_text(sample, mode, hwnd=new_hwnd)
            time.sleep(0.6)
            got = select_all_copy_read()
            ok = normalize(got) == expected
            log.info("[%s] %s", mode, "通过" if ok else "失败")
            if not ok:
                log.error("  期望: %r", expected)
                log.error("  实际: %r", normalize(got))
            all_ok = all_ok and ok

        clear_editor()
        log.info("-" * 60)
        log.info("自检结果: %s", "全部通过" if all_ok else "存在失败")
        return all_ok
    finally:
        if new_hwnd:
            user32.PostMessageW(new_hwnd, WM_CLOSE, 0, 0)
        if backup is not None:
            set_clipboard_text(backup)
            log.info("原剪贴板已恢复。")


# ==================== 实验 / 备用方案（当前主流程未调用） ====================
# 下面这些是 v4 里为"打字软件不吃 Unicode 注入、只认真实按键"准备的备选路径。
# 实测当前流程（假字缓冲）已经够用，所以没有接进主循环；留着是因为换软件时
# 可能又要用，删了就得重新推一遍。
_PUNCT_VK_MAP = {
    "。": (0xBE, False),   # '.' 键
    "，": (0xBC, False),   # ',' 键
    "；": (0xBA, False),   # ';' 键
    "：": (0xBA, True),    # Shift+';'
    "？": (0xBF, True),    # Shift+'/'
    "！": (0x31, True),    # Shift+'1'
    "、": (0xDC, False),   # '\' 键
    "（": (0x39, True),    # Shift+'9'
    "）": (0x30, True),    # Shift+'0'
    "“": (0xDE, True),     # Shift+'
    "”": (0xDE, True),     # Shift+'（输入法自动配对）
}


def _buffer_vk_after_lineend():
    """满行行尾标点后的缓冲：真实按键（带虚拟键码）的空格+退格。
    打字软件只对"真实按键"（wVk≠0）触发换行，Unicode 注入（wVk=0）不触发；
    真实空格触发换行后，真实退格把空格删掉，不留下痕迹。"""
    _vk_event(VK_SPACE, False)
    time.sleep(0.05)
    _vk_event(VK_SPACE, True)
    time.sleep(0.05)
    _vk_event(VK_BACK, False)
    time.sleep(0.05)
    _vk_event(VK_BACK, True)


def _force_ime_chinese(hwnd):
    """强制目标窗口输入法切到中文模式，返回切换后是否处于中文模式；
    拿不到输入上下文返回 None。"""
    try:
        imm32 = ctypes.windll.imm32
        imm32.ImmGetContext.restype = ctypes.c_void_p
        imm32.ImmGetContext.argtypes = [wintypes.HWND]
        imm32.ImmSetConversionStatus.argtypes = [
            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
        imm32.ImmGetConversionStatus.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
        ]
        imm32.ImmReleaseContext.argtypes = [wintypes.HWND, ctypes.c_void_p]
        himc = imm32.ImmGetContext(hwnd)
        if not himc:
            return None
        try:
            # NATIVE(0x0001)|FULLSHAPE(0x0008) = 中文模式全角
            imm32.ImmSetConversionStatus(himc, 0x0001 | 0x0008, 0)
            time.sleep(0.1)
            conv = wintypes.DWORD()
            sent = wintypes.DWORD()
            imm32.ImmGetConversionStatus(himc, ctypes.byref(conv),
                                         ctypes.byref(sent))
            return bool(conv.value & 0x0001)
        finally:
            imm32.ImmReleaseContext(hwnd, himc)
    except Exception:
        return None


def _send_punct_vk(ch):
    """通过 keybd_event 真实按键+中文输入法发送标点；不支持的字返回 False。
    用 keybd_event 而不是 SendInput：低层键盘钩子里不会标记为"注入"，
    打字软件才会当作真实输入处理。"""
    vk, shift = _PUNCT_VK_MAP.get(ch, (None, None))
    if vk is None:
        return False
    if shift:
        user32.keybd_event(VK_SHIFT, 0, 0, 0)
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.06)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    if shift:
        user32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0)
    return True


# ==================== 单实例 ====================
_MUTEX_HANDLE = None


def single_instance(name="win_ocr_type_v5_singleton"):
    """命名互斥体：同一时间只允许一个实例（否则两个监听会双触发）。
    进程退出时互斥体自动释放，不会残留。"""
    global _MUTEX_HANDLE
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL,
                                     wintypes.LPCWSTR]
        k32.CreateMutexW.restype = wintypes.HANDLE
        h = k32.CreateMutexW(None, False, name)
        if not h:
            return True
        if ctypes.get_last_error() == 183:      # ERROR_ALREADY_EXISTS
            return False
        _MUTEX_HANDLE = h
        return True
    except Exception:
        return True


def main():
    setup_logging()
    if not single_instance():
        log.warning("已经有一个 %s 在运行了，这次不再启动。", os.path.basename(__file__))
        log.warning("（如果确认没在运行，可能是别的目录里也开着同一份脚本）")
        return 2
    WinOCRType().run()
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        setup_logging()
        sys.exit(0 if selftest() else 1)
    if "-h" in sys.argv or "--help" in sys.argv:
        print(__doc__)
        sys.exit(0)
    sys.exit(main())
