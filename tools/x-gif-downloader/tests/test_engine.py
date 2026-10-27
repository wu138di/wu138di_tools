import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import (Cancelled, DownloadManager, convert_gif, download_file,
                    normalize_media, original_photo, parse_link, reserve_destination,
                    resolve)


class ResolverTests(unittest.TestCase):
    def test_link_variants(self):
        self.assertEqual(parse_link('https://x.com/user/status/123/photo/2?s=20'), ('123', 2))
        self.assertEqual(parse_link('https://twitter.com/user/status/123'), ('123', None))
        self.assertEqual(parse_link('分享 https://x.com/i/web/status/123/video/1 。'), ('123', 1))

    def test_invalid_link(self):
        for value in ('', 'https://evil.example/u/status/1', 'https://x.com.evil.example/a/status/1', 'file:///1', 'http://x.com/a/status/1', 'https://x.com/a/status/1/photo/0'):
            with self.assertRaises(ValueError):
                parse_link(value)

    def test_photo_original(self):
        url, ext = original_photo('https://pbs.twimg.com/media/abc.jpg?name=small')
        self.assertEqual(url, 'https://pbs.twimg.com/media/abc?format=jpg&name=orig')
        self.assertEqual(ext, 'jpg')

    def test_best_video_and_order(self):
        items = normalize_media([
            {'type': 'photo', 'media_url_https': 'https://pbs.twimg.com/media/a.png', 'original_info': {'width': 100, 'height': 200}},
            {'type': 'animated_gif', 'video_info': {'variants': [
                {'content_type': 'application/x-mpegURL', 'url': 'https://video.twimg.com/a.m3u8'},
                {'content_type': 'video/mp4', 'bitrate': 200, 'url': 'https://video.twimg.com/low.mp4'},
                {'content_type': 'video/mp4', 'bitrate': 900, 'url': 'https://video.twimg.com/high.mp4'}]}}
        ])
        self.assertEqual([m['index'] for m in items], [1, 2])
        self.assertEqual(items[1]['url'], 'https://video.twimg.com/high.mp4')
        self.assertEqual(items[1]['kind'], 'gif')

    def test_fallback(self):
        fixture={'tweet':{'media':{'all':[{'type':'gif','format':'video/mp4','url':'https://video.twimg.com/a.mp4'}]},'author':{'name':'Name'},'text':'test'}}
        with patch('engine.request_json', side_effect=[ValueError(),fixture]):
            self.assertEqual(resolve('123',threading.Event())['provider'], 'FxTwitter')

    def test_media_thumbnail_is_validated(self):
        item = {'type': 'gif', 'format': 'video/mp4', 'url': 'https://video.twimg.com/a.mp4',
                'thumbnail_url': 'https://pbs.twimg.com/tweet_video_thumb/a.jpg'}
        self.assertEqual(normalize_media([item])[0]['thumbnail'], item['thumbnail_url'])
        item['thumbnail_url'] = 'https://other.example/track.jpg'
        self.assertEqual(normalize_media([item])[0]['thumbnail'], '')

    def test_reservation_preserves_existing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / 'one.mp4'
            original.write_bytes(b'keep-me')
            other = reserve_destination(root, 'one', 'mp4')
            self.assertNotEqual(original, other)
            self.assertEqual(original.read_bytes(), b'keep-me')

    def test_cancel_removes_partial_not_existing(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            original=root/'media.mp4';original.write_bytes(b'keep')
            target=reserve_destination(root,'media','mp4')
            event=threading.Event();event.set()
            with self.assertRaises(Cancelled):
                download_file({'kind':'gif','url':'https://video.twimg.com/a.mp4'},target,event,lambda a,b:None)
            self.assertFalse(target.exists())
            self.assertEqual(original.read_bytes(),b'keep')
            self.assertEqual(list(root.glob('*.part')),[])

    def test_manager_inline_error(self):
        with tempfile.TemporaryDirectory() as directory:
            manager=DownloadManager(directory)
            self.assertFalse(manager.start('not a URL')['ok'])
            self.assertEqual(manager.snapshot()['phase'],'error')

    def test_backend_no_hardcoded_media(self):
        text=(Path(__file__).resolve().parents[1]/'engine.py').read_text(encoding='utf-8')
        self.assertNotIn('HVhkje8XIAA9KC8',text)
        self.assertNotIn('2114550605356122308',text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
