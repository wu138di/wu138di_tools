"""Local, token-scoped media proxy and asynchronous post preview."""
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import secrets
import threading
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from engine import HEADERS, Cancelled, parse_link, resolve


class MediaServer:
    def __init__(self):
        self._lock = threading.Lock()
        self._urls = {}
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.serve(False)

            def do_HEAD(self):
                self.serve(True)

            def serve(self, head):
                with owner._lock:
                    url = owner._urls.get(self.path)
                if not url:
                    self.send_error(404)
                    return
                headers = dict(HEADERS)
                value = self.headers.get('Range', '')
                if value:
                    import re
                    if not re.fullmatch(r'bytes=\d*-\d*', value):
                        self.send_error(416)
                        return
                    headers['Range'] = value
                started = False
                try:
                    with urlopen(Request(url, headers=headers, method='HEAD' if head else 'GET'), timeout=20) as response:
                        self.send_response(response.status)
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.send_header('Accept-Ranges', 'bytes')
                        self.send_header('Cache-Control', 'private, max-age=1800')
                        self.send_header('X-Content-Type-Options', 'nosniff')
                        for name in ['Content-Type', 'Content-Length', 'Content-Range']:
                            if response.headers.get(name):
                                self.send_header(name, response.headers[name])
                        self.end_headers()
                        started = True
                        if not head:
                            while True:
                                data = response.read(64 * 1024)
                                if not data:
                                    break
                                self.wfile.write(data)
                except (ConnectionError, BrokenPipeError):
                    pass
                except Exception as error:
                    if not started:
                        try:
                            self.send_error(error.code if isinstance(error, HTTPError) else 502)
                        except ConnectionError:
                            pass

        self._server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self._server.daemon_threads = True
        self._server.block_on_close = False
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def register(self, url):
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname not in {'pbs.twimg.com', 'video.twimg.com'}:
            raise ValueError('预览媒体地址校验失败')
        token = '/media/' + secrets.token_urlsafe(24)
        with self._lock:
            self._urls[token] = url
            # Keep recent tokens alive while existing media elements finish reading.
            if len(self._urls) > 128:
                self._urls.pop(next(iter(self._urls)))
        return 'http://127.0.0.1:%d%s' % (self._server.server_port, token)

    def close(self):
        self._server.shutdown()
        self._server.server_close()


class PreviewManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._server = None
        self._generation = 0
        self._cancel = threading.Event()
        self._key = None
        self._state = {'phase': 'idle', 'items': [], 'message': ''}

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._state)

    def start(self, link, all_media=False):
        try:
            tweet_id, index = parse_link(link)
        except ValueError:
            with self._lock:
                self._cancel.set()
                self._generation += 1
                self._key = None
                self._state = {'phase': 'idle', 'items': [], 'message': ''}
            return {'ok': False}
        selected = None if all_media else index
        key = (tweet_id, selected)
        with self._lock:
            if key == self._key and self._state['phase'] in {'loading', 'ready'}:
                return {'ok': True}
            self._cancel.set()
            self._cancel = threading.Event()
            self._generation += 1
            generation, cancel = self._generation, self._cancel
            self._key = key
            self._state = {'phase': 'loading', 'items': [], 'message': '加载中…'}
        threading.Thread(target=self._run, args=(tweet_id, selected, generation, cancel), daemon=True).start()
        return {'ok': True}

    def _run(self, tweet_id, selected, generation, cancel):
        try:
            post = resolve(tweet_id, cancel)
            items = post['items']
            if selected is not None:
                if selected > len(items):
                    raise ValueError('该媒体序号不存在')
                items = [items[selected - 1]]
            with self._lock:
                if generation != self._generation or cancel.is_set():
                    return
                if self._server is None:
                    self._server = MediaServer()
                previews = [{key: item[key] for key in ['index', 'kind', 'width', 'height', 'name']} for item in items]
                for preview, item in zip(previews, items):
                    preview['src'] = self._server.register(item['url'])
                self._state = {'phase': 'ready', 'items': previews, 'message': ''}
        except Cancelled:
            pass
        except Exception:
            with self._lock:
                if generation == self._generation:
                    self._state = {'phase': 'error', 'items': [], 'message': '预览暂未加载'}

    def close(self):
        self._cancel.set()
        with self._lock:
            self._generation += 1
            server, self._server = self._server, None
        if server:
            server.close()
