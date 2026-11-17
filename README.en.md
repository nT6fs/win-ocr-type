# win-ocr-type

Screen capture → OCR → auto-type, for Windows.

Press `F9`, drag a rectangle on screen, review the editable preview, press
`Ctrl+Enter`. The recognized text is typed into the focused window key by key.

**No clipboard is used for input.** ASCII characters are sent as virtual key
codes, CJK characters as Unicode injection, and every key is sent as a separate
key-down / key-up pair. This is what makes it work in typing-tutor software that
scores per grid cell and ignores `Ctrl+V`.

## Features

- Editable confirmation window before typing — fix OCR errors first.
- Layout reconstruction (`LAYOUT_MODE="layout"`): rebuilds inter-word spaces,
  leading indentation and blank lines from the per-character bounding boxes.
  The default `clean` mode drops them, because one extra space shifts a whole
  line in grid-based typing software.
- Skips duplicated lines — the "already typed" row that often gets captured
  together with the source text in two-column typing UIs.
- Focus guard: if the target window loses foreground during typing, it tries to
  restore it and otherwise aborts safely instead of typing into the wrong window.
- Auto-invert for dark themes.
- Multi-monitor: capture and selection cover the whole virtual desktop, with
  fallback to the primary monitor.
- Rolling log file.

## Install

Windows 10/11, Python 3.8+.

```bat
pip install -r requirements.txt
```

`winocr` wraps the built-in `Windows.Media.Ocr` engine, so recognition depends on
the language packs installed in Windows. On a Chinese system `zh-Hans-CN` is
available by default; otherwise install the optional "Chinese (Simplified)"
language feature and/or change `OCR_LANG`.

## Run

```bat
python win_ocr_type.py
```

| Key | Action |
| --- | --- |
| `F9` | capture region + OCR |
| `F10` | toggle input backend |
| `F11` | re-hook the keyboard listener |
| `F12` | pause / resume typing |
| `F8` | quit |
| `Esc` | cancel |
| `Ctrl+Enter` | confirm the preview |

## Configuration

All settings live in the "配置区" block at the top of `win_ocr_type.py`.

| Scenario | `LAYOUT_MODE` | `NEWLINE_AS_ENTER` |
| --- | --- | --- |
| Typing tutor software | `clean` | `False` (Enter submits) |
| Notepad / Word / browser | `layout` | `True` |
| Code editor | `layout` | `True` |

## Self test

```bat
python win_ocr_type.py --selftest
```

Opens Notepad, types a sample with both backends, reads the content back via
`Ctrl+A`/`Ctrl+C` and compares it. Requires a real desktop session.

## Accuracy benchmark

Put screenshots plus a same-named `.txt` with the expected text into
`bench_images/`, then:

```bat
python bench_ocr.py
```

## Limitations

- Windows only; depends on the system OCR engine.
- The multi-monitor path is logically verified but not tested on real dual
  screens by the author.
- Some OCR errors are inherent (rare characters split into components, missing
  trailing punctuation) — that is why the confirmation window exists.

## License

MIT.
