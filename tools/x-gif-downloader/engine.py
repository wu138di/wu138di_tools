"""Public X media resolver and cancellable, original-quality downloader."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

VERSION = "1.0.0"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://x.com/"}
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
HIDDEN_PROCESS = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


class Cancelled(Exception):
    pass


def check_cancel(cancel):
    if cancel.is_set():
        raise Cancelled("已取消；已完成的文件会保留。")


def parse_link(text):
    match = re.search(r"https?://[^\s<>\"\u3000]+", str(text))
    if not match:
        raise ValueError("请先粘贴 X / Twitter 帖子网址。")
    parsed = urlparse(match.group(0).rstrip(".,，。)）"))
    if parsed.scheme != "https" or parsed.hostname not in {
        "x.com", "www.x.com", "mobile.x.com", "twitter.com",
        "www.twitter.com", "mobile.twitter.com", "m.twitter.com",
    }:
        raise ValueError("请输入 x.com 或 twitter.com 的 HTTPS 帖子网址。")
    match = re.fullmatch(r"/(?:[^/]+|i/web)/status/(\d+)(?:/(?:photo|video)/(\d+))?/?", parsed.path)
    if not match:
        raise ValueError("这不是帖子链接。示例：x.com/用户名/status/帖子编号")
    index = int(match.group(2)) if match.group(2) else None
    if index is not None and index < 1:
        raise ValueError("媒体序号应从 1 开始。")
    return match.group(1), index


def request_json(url, cancel):
    check_cancel(cancel)
    with urlopen(Request(url, headers=HEADERS), timeout=20) as response:
        data = response.read(5 * 1024 * 1024 + 1)
    check_cancel(cancel)
    if len(data) > 5 * 1024 * 1024:
        raise ValueError("媒体信息响应超出预期大小。")
    return json.loads(data)


def media_host(url, photo=False):
    parsed = urlparse(url)
    expected = "pbs.twimg.com" if photo else "video.twimg.com"
    if parsed.scheme != "https" or parsed.hostname != expected:
        raise ValueError("媒体服务器地址校验失败。")
    return url


def original_photo(url):
    parsed = urlparse(media_host(url, photo=True))
    query = parse_qs(parsed.query)
    extension = Path(parsed.path).suffix.lower().lstrip(".")
    fmt = (query.get("format") or [extension or "jpg"])[0]
    if fmt not in {"jpg", "jpeg", "png", "webp"}:
        fmt = "jpg"
    stem = re.sub(r"\.(jpg|jpeg|png|webp)$", "", parsed.path, flags=re.I)
    return urlunparse(("https", "pbs.twimg.com", stem, "", urlencode({"format": fmt, "name": "orig"}), "")), fmt


def normalize_media(items):
    result = []
    for i, raw in enumerate(items, 1):
        kind = raw.get("type")
        info = raw.get("original_info", {})
        width, height = info.get("width", raw.get("width", 0)), info.get("height", raw.get("height", 0))
        if kind == "photo":
            url, ext = original_photo(raw.get("media_url_https") or raw.get("url", ""))
        elif kind in {"video", "animated_gif", "gif"}:
            variants = raw.get("video_info", {}).get("variants", []) or raw.get("variants", []) or raw.get("formats", [])
            variants = [v for v in variants if v.get("content_type") == "video/mp4" or v.get("container") == "mp4"]
            if variants:
                best = max(variants, key=lambda v: v.get("bitrate") or 0)
                url = best["url"]
            elif raw.get("format") == "video/mp4":
                url = raw["url"]
            else:
                raise ValueError("第 %d 项视频暂未返回可下载的 MP4。" % i)
            url, ext = media_host(url), "mp4"
            kind = "gif" if kind in {"animated_gif", "gif"} else "video"
        else:
            raise ValueError("第 %d 项媒体类型暂未支持。" % i)
        thumbnail = raw.get("media_url_https") or raw.get("thumbnail_url") or (url if kind == "photo" else "")
        thumb_parts = urlparse(thumbnail)
        if thumb_parts.scheme != "https" or thumb_parts.hostname != "pbs.twimg.com":
            thumbnail = ""
        result.append({"index": i, "kind": kind, "url": url, "ext": ext, "thumbnail": thumbnail,
                       "width": width, "height": height,
                       "name": "第 %d 项 · %s" % (i, {"photo": "图片", "video": "视频", "gif": "动图"}[kind]),
                       "status": "等待下载", "progress": 0, "bytes": 0, "files": []})
    return result


def resolve(tweet_id, cancel, note=lambda value: None):
    urls = [
        ("X", "https://cdn.syndication.twimg.com/tweet-result?" + urlencode({"id": tweet_id, "lang": "zh", "token": "0"})),
        ("FxTwitter", "https://api.fxtwitter.com/status/" + tweet_id),
    ]
    errors = []
    for provider, url in urls:
        check_cancel(cancel)
        try:
            note("正在读取帖子媒体…" if provider == "X" else "正在尝试备用公开接口…")
            data = request_json(url, cancel)
            if provider == "X":
                items = data.get("mediaDetails", [])
                user = data.get("user", {})
                author = user.get("name") or user.get("screen_name", "")
                text = data.get("text", "")
            else:
                tweet = data.get("tweet") or {}
                items = (tweet.get("media") or {}).get("all", [])
                author = (tweet.get("author") or {}).get("name", "")
                text = tweet.get("text", "")
            if not items:
                raise ValueError("未找到公开媒体")
            media = normalize_media(items)
            return {"id": tweet_id, "author": author, "text": text, "provider": provider, "items": media}
        except Cancelled:
            raise
        except Exception as error:
            errors.append("%s: %s" % (provider, type(error).__name__))
    raise RuntimeError("暂未获取到媒体。请检查网络和链接，并确认帖子公开且未删除。稍后可重试。" + " [" + "; ".join(errors) + "]")


def reserve_destination(directory, stem, extension):
    """Create an empty placeholder atomically; never replace an existing user file."""
    for number in range(10000):
        suffix = "" if not number else "_%d" % (number + 1)
        path = directory / (stem + suffix + "." + extension)
        try:
            with path.open("xb"):
                pass
            return path
        except FileExistsError:
            continue
    raise RuntimeError("同名文件过多，请更换保存文件夹。")


def validate_media(path, kind):
    with path.open("rb") as handle:
        header = handle.read(64)
    if kind in {"gif", "video"}:
        valid = b"ftyp" in header
    else:
        valid = header.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")) or (header[:4] == b"RIFF" and header[8:12] == b"WEBP")
    if not valid:
        raise ValueError("下载响应不是预期的媒体文件，请重试。")


def download_file(item, destination, cancel, progress):
    partial = destination.with_suffix(destination.suffix + ".part")
    complete = False
    try:
        for attempt in range(3):
            check_cancel(cancel)
            try:
                digest, count, last = hashlib.sha256(), 0, 0
                with urlopen(Request(item["url"], headers=HEADERS), timeout=20) as response:
                    length = int(response.headers.get("Content-Length") or 0)
                    with partial.open("wb") as handle:
                        while True:
                            check_cancel(cancel)
                            chunk = response.read(64 * 1024)
                            if not chunk:
                                break
                            handle.write(chunk)
                            digest.update(chunk)
                            count += len(chunk)
                            if time.monotonic() - last > .12:
                                progress(count, length)
                                last = time.monotonic()
                if not count or (length and length != count):
                    raise ValueError("文件长度校验失败")
                check_cancel(cancel)
                validate_media(partial, item["kind"])
                partial.replace(destination)
                complete = True
                progress(count, length or count)
                return {"path": str(destination), "bytes": count, "sha256": digest.hexdigest()}
            except Cancelled:
                raise
            except Exception:
                partial.unlink(missing_ok=True)
                if attempt == 2:
                    raise
                for _ in range((attempt + 1) * 5):
                    check_cancel(cancel)
                    time.sleep(.2)
    finally:
        partial.unlink(missing_ok=True)
        if not complete:
            destination.unlink(missing_ok=True)


def locate_ffmpeg():
    bundled = ROOT / "assets" / "ffmpeg.exe"
    if bundled.is_file():
        return str(bundled)
    import shutil
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        raise RuntimeError("GIF 转换组件缺失；原始 MP4 已保留。")


def convert_gif(source, destination, cancel):
    temp = destination.with_name(destination.stem + ".converting.gif")
    error_log = destination.with_name(destination.stem + ".conversion.log")
    command = [locate_ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(source),
               "-filter_complex", "[0:v]split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle",
               "-loop", "0", str(temp)]
    complete = False
    process = None
    try:
        check_cancel(cancel)
        with error_log.open("wb") as log:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=log, **HIDDEN_PROCESS)
            while process.poll() is None:
                if cancel.wait(.12):
                    raise Cancelled()
            if process.returncode:
                raise RuntimeError("GIF 转换未成功；原始 MP4 已保留。")
        with temp.open("rb") as handle:
            if handle.read(6) not in {b"GIF87a", b"GIF89a"}:
                raise ValueError("GIF 格式校验失败；原始 MP4 已保留。")
        check_cancel(cancel)
        temp.replace(destination)
        complete = True
        return {"path": str(destination), "bytes": destination.stat().st_size,
                "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=4)
        temp.unlink(missing_ok=True)
        if complete:
            error_log.unlink(missing_ok=True)
        elif destination.exists():
            destination.unlink(missing_ok=True)


def initial_state(directory):
    return {"phase": "idle", "message": "准备好，收藏下一份喜欢。", "progress": 0,
            "directory": str(directory), "job_directory": "", "items": [], "author": "", "text": "",
            "provider": "", "completed": 0, "failed": 0, "file_count": 0, "version": VERSION}


class DownloadManager:
    def __init__(self, directory):
        self.lock = threading.RLock()
        self.state = initial_state(directory)
        self.cancel_event = threading.Event()
        self.thread = None

    def snapshot(self):
        with self.lock:
            result = copy.deepcopy(self.state)
            for item in result["items"]:
                item.pop("url", None)
            return result

    def update(self, **values):
        with self.lock:
            self.state.update(values)

    def set_item(self, index, **values):
        with self.lock:
            self.state["items"][index].update(values)

    def start(self, link, gif=True, all_media=False):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return {"ok": False, "message": "当前下载进行中，可先取消。"}
            try:
                tweet_id, selected = parse_link(link)
            except ValueError as error:
                self.state.update(phase="error", message=str(error), progress=0)
                return {"ok": False, "message": str(error)}
            directory = self.state["directory"]
            self.state = initial_state(directory)
            self.state.update(phase="resolving", message="正在读取帖子媒体…")
            self.cancel_event = threading.Event()
            self.thread = threading.Thread(target=self.run, args=(tweet_id, None if all_media else selected, bool(gif)), daemon=True)
            self.thread.start()
            return {"ok": True}

    def run(self, tweet_id, selected, gif):
        try:
            post = resolve(tweet_id, self.cancel_event, lambda text: self.update(message=text))
            items = post["items"]
            if selected is not None:
                if selected > len(items):
                    raise ValueError("帖子共 %d 项媒体，链接指向第 %d 项；请切换为「全部媒体」。" % (len(items), selected))
                items = [items[selected - 1]]
            check_cancel(self.cancel_event)
            directory = Path(self.state["directory"]) / ("X_" + tweet_id)
            directory.mkdir(parents=True, exist_ok=True)
            self.update(phase="downloading", message="正在下载原始媒体…", items=items,
                        job_directory=str(directory), author=post["author"], text=post["text"], provider=post["provider"])
            completed, failed, file_count = 0, 0, 0
            for n, item in enumerate(items):
                check_cancel(self.cancel_event)
                try:
                    self.set_item(n, status="正在下载")
                    stem = "X_%s_%02d" % (tweet_id, item["index"])
                    destination = reserve_destination(directory, stem, item["ext"])
                    def progress(count, length):
                        ratio = count / length if length else 0
                        percent = min(94 if item["kind"] == "gif" and gif else 100, int(ratio * 100))
                        self.set_item(n, progress=percent, bytes=count)
                        self.update(progress=round((n + percent / 100) / len(items) * 100, 1))
                    saved = download_file(item, destination, self.cancel_event, progress)
                    file_count += 1
                    self.set_item(n, files=[saved], bytes=saved["bytes"])
                    if item["kind"] == "gif" and gif:
                        self.set_item(n, status="正在生成 GIF", progress=96)
                        self.update(phase="converting", message="正在生成原尺寸循环 GIF…")
                        target = reserve_destination(directory, destination.stem, "gif")
                        extra = convert_gif(destination, target, self.cancel_event)
                        self.set_item(n, files=[saved, extra])
                        file_count += 1
                    completed += 1
                    self.set_item(n, status="已保存", progress=100)
                except Cancelled:
                    self.set_item(n, status="已取消")
                    raise
                except Exception as error:
                    failed += 1
                    self.set_item(n, status="未完成", error=str(error))
                self.update(phase="downloading", completed=completed, failed=failed, file_count=file_count,
                            progress=round((n + 1) / len(items) * 100, 1))
            self.update(phase="partial" if failed else "done", progress=100,
                        message=("已保存 %d 个文件，%d 项待重试。" % (file_count, failed)) if failed else ("下载完成，已保存 %d 个文件。" % file_count))
        except Cancelled:
            with self.lock:
                file_count = sum(len(item["files"]) for item in self.state["items"])
            self.update(phase="cancelled", message="已取消；已完成的文件已保留。", file_count=file_count)
        except Exception as error:
            self.update(phase="error", message=str(error))

    def cancel(self):
        self.cancel_event.set()
        with self.lock:
            if self.state["phase"] in {"resolving", "downloading", "converting"}:
                self.state["message"] = "正在取消；已完成的文件会保留…"
        return {"ok": True}
