"""Shiguang desktop shell. UI stays local; only public media requests leave the app."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

from engine import DownloadManager, ROOT, VERSION, locate_ffmpeg
from preview import PreviewManager

APP_TITLE = "wu138di X GIF下载器 v1.0"


def config_directory():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local"))) / "ShiguangDownloader"


def default_download_directory():
    if os.name == "nt":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
            with key:
                value, _ = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")
            return Path(os.path.expandvars(value)) / "wu138di X GIF下载器"
        except OSError:
            pass
    return Path.home() / "Downloads" / "wu138di X GIF下载器"


class API:
    def __init__(self, directory=None, persist=True):
        self._window = None
        self._persist = persist
        self._settings = {"directory": str(directory or default_download_directory()), "gif": True, "all_media": False}
        self._config = config_directory() / "settings.json"
        if persist:
            try:
                saved = json.loads(self._config.read_text(encoding="utf-8"))
                if isinstance(saved.get("directory"), str):
                    self._settings["directory"] = saved["directory"]
                for flag in ("gif", "all_media"):
                    if isinstance(saved.get(flag), bool):
                        self._settings[flag] = saved[flag]
            except (OSError, ValueError, TypeError, AttributeError):
                pass
        self._manager = DownloadManager(self._settings["directory"])
        self._preview = PreviewManager()

    def _save(self):
        if not self._persist:
            return
        try:
            self._config.parent.mkdir(parents=True, exist_ok=True)
            temp = self._config.with_suffix(".tmp")
            temp.write_text(json.dumps(self._settings, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self._config)
        except OSError:
            pass

    def get_state(self):
        state = self._manager.snapshot()
        state["preferences"] = dict(self._settings)
        state["preview"] = self._preview.snapshot()
        return state

    def preview_post(self, url, all_media=False):
        if not isinstance(url, str) or len(url) > 4096:
            return {"ok": False}
        return self._preview.start(url, bool(all_media))

    def start_download(self, url, gif=True, all_media=False):
        if not isinstance(url, str) or len(url) > 4096:
            return {"ok": False, "message": "帖子网址过长，请仅粘贴帖子链接。"}
        result = self._manager.start(url, bool(gif), bool(all_media))
        if result["ok"]:
            self._preview.start(url, bool(all_media))
            self._settings.update(gif=bool(gif), all_media=bool(all_media))
            self._save()
        return result

    def cancel_download(self):
        return self._manager.cancel()

    def choose_directory(self):
        import webview
        if self._manager.thread and self._manager.thread.is_alive():
            return {"ok": False, "message": "请在当前下载完成后更换位置。"}
        selected = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if selected:
            self._settings["directory"] = str(Path(selected[0]).resolve())
            self._manager.update(directory=self._settings["directory"], job_directory="")
            self._save()
        return {"ok": True, "directory": self._settings["directory"]}

    def open_directory(self):
        state = self._manager.snapshot()
        directory = Path(state["job_directory"] or state["directory"])
        directory.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(directory))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(directory)])
        else:
            subprocess.Popen(["xdg-open", str(directory)])
        return {"ok": True}

    def minimize(self):
        self._window.minimize()

    def toggle_maximize(self):
        if getattr(self, "_maximized", False):
            self._window.restore()
        else:
            self._window.maximize()
        self._maximized = not getattr(self, "_maximized", False)

    def close_window(self):
        self._manager.cancel()
        self._preview.close()
        self._window.destroy()


def self_test(args):
    api = API(args.output or (Path.cwd() / "self-test-downloads"), persist=False)
    started = api.start_download(args.url, not args.no_gif, args.all_media)
    if started["ok"]:
        api._manager.thread.join(timeout=180)
        if api._manager.thread.is_alive():
            api._manager.cancel()
            api._manager.thread.join(timeout=30)
    result = api.get_state()
    result["packaged"] = bool(getattr(sys, "frozen", False))
    result["ffmpeg_bundled"] = (ROOT / "assets/ffmpeg.exe").is_file()
    result["background_bundled"] = (ROOT / "ui/background.png").is_file()
    result["ffmpeg"] = locate_ffmpeg()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if sys.stdout:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["phase"] == "done" else 1


def main():
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--url", default="https://x.com/798145343h/status/2114550605356122308/photo/2")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--no-gif", action="store_true")
    parser.add_argument("--all-media", action="store_true")
    parser.add_argument("--test-ui", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.self_test:
        return self_test(args)
    import webview
    api = API(args.output, persist=not args.test_ui)
    webview.settings["ALLOW_DOWNLOADS"] = False
    webview.settings["ALLOW_FILE_URLS"] = False
    window = webview.create_window(
        APP_TITLE, str(ROOT / "ui/index.html"), js_api=api,
        width=1180, height=800, min_size=(900, 680),
        frameless=True, easy_drag=False, shadow=True,
        background_color="#F5F2FB", text_select=True,
    )
    api._window = window
    def closing():
        api._manager.cancel()
        api._preview.close()
        if api._manager.thread and api._manager.thread.is_alive():
            api._manager.thread.join(timeout=2)
    window.events.closing += closing
    if args.test_ui and args.report:
        def loaded():
            try:
                info = window.evaluate_js("({title:document.title, width:innerWidth, height:innerHeight, background:getComputedStyle(document.body).backgroundImage, ready:!!window.pywebview})")
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                args.report.write_text(traceback.format_exc(), encoding="utf-8")
        window.events.loaded += loaded
    webview.start(gui="edgechromium", debug=False, private_mode=True,
                  storage_path=str(config_directory() / "WebView2"), icon=str(ROOT / "assets/app.ico"))
    return 0


if __name__ == "__main__":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.exit(main())
    except Exception:
        details = traceback.format_exc()
        log = config_directory() / "startup-error.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(details, encoding="utf-8")
        if sys.stderr:
            print(details, file=sys.stderr)
        if getattr(sys, "frozen", False) and os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, "启动未成功。请确认已安装 Microsoft Edge WebView2。\n诊断文件：" + str(log), APP_TITLE, 0x10)
        sys.exit(1)


