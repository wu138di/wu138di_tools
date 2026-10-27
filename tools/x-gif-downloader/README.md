# wu138di X GIF下载器 v1.0

[使用教程与下载](../../README.md)

## 源码结构

- `main.py`：Windows 桌面窗口、界面交互与偏好设置。
- `engine.py`：帖子解析、原始媒体下载、GIF 转换。
- `preview.py`：本地媒体预览与 Range 请求转发。
- `ui/`：界面、用户提供的背景和 Logo、已公开使用的赞赏码。
- `assets/app.ico`：EXE 与窗口图标。
- `licenses/`：第三方组件许可。

## 从源码运行

使用 Windows x64 与 Python 3.14：

```powershell
cd tools/x-gif-downloader
python -m pip install -r requirements.txt
python main.py
```

运行时需要 Microsoft Edge WebView2 Runtime。FFmpeg 从系统 PATH 或 `imageio-ffmpeg` 中查找；发布 EXE 已内置该组件。

## 构建单文件 EXE

```powershell
python build.py
```

脚本从已安装的 `imageio-ffmpeg` 包复制 FFmpeg 到 `assets/ffmpeg.exe`，与界面一起打包。产物位于本目录的 `dist/`，中间文件位于 `build-cache/`；这两个目录以及 FFmpeg 二进制不提交到 Git。

```powershell
python tests/test_engine.py
python main.py --self-test --output self-test-downloads --report test-result.json
```

## 行为说明

- `/photo/2`、`/video/2` 等序号默认只下载对应项；“全部媒体”忽略序号。
- 图片请求平台原图，视频选择公开媒体信息中的最高可用 MP4 码率。
- MP4 直接下载；仅动图默认额外生成原尺寸、源帧率、无限循环 GIF。
- 取消任务会保留已完成文件；重复下载自动增加文件名编号。
- 界面保持本地运行，不读取浏览器登录信息。
- 优先请求 X 的公开媒体接口；失败时向 FxTwitter 公开接口查询该帖子。
- 预览使用绑定在 `127.0.0.1` 的本地端口，只提供随机令牌登记过的 X 媒体 URL，不开放任意本地文件读取。
- 保存位置与开关存于 `%LOCALAPPDATA%/ShiguangDownloader/settings.json`，不保存帖子历史。

背景、Logo 与赞赏码保留各自权利。未经原作者许可，请勿据此对插画等素材作额外授权或使用。详见 [NOTICE.md](NOTICE.md)。
