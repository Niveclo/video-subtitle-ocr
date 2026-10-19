# 依赖、模型和上游资料

本项目编排视频解码、OCR、去重与标准字幕导出，不训练识别模型。
依赖以 `pyproject.toml` 和 `uv.lock` 为准。

| 组件 | 用途 | 上游 |
|---|---|---|
| RapidOCR 3.10.0 | 模型管理、文本检测与识别 | [RapidOCR](https://github.com/RapidAI/RapidOCR) |
| PP-OCRv6 small | 中英文文字检测和识别模型 | [RapidOCR 模型资料](https://rapidai.github.io/RapidOCRDocs/main/models/) |
| ONNX Runtime DirectML 1.24.4 | Windows CPU / DirectML 推理 | [DirectML provider](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html) |
| OpenCV headless 4.12.0.88 | 视频元数据、截图与图像处理 | [OpenCV](https://opencv.org/) |
| imageio-ffmpeg 0.6.0 | 项目内 FFmpeg 可执行文件、视频解码 | [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) |
| NumPy / Pillow | 图像数据及上游所需支持 | [NumPy](https://numpy.org/)、[Pillow](https://python-pillow.org/) |
| Ruff | 静态检查与格式化 | [Ruff](https://docs.astral.sh/ruff/) |

`Video-subtitle-extractor` 是前期工具调研参考，当前项目不依赖或安装其完整 GUI/Paddle 环境。
参见 [其上游项目](https://github.com/YaoFANGUK/video-subtitle-extractor)。

## 模型缓存

默认缓存路径为项目 `models/`，包括：

```text
PP-OCRv6_det_small.onnx
PP-OCRv6_rec_small.onnx
```

本机文件来自前期验证项目的已验证缓存，复制进本项目以避免重复下载。
RapidOCR 加载模型时按照其上游清单校验文件；不要手动用其他文件替换同名模型。
首次缺失模型时，由 RapidOCR 从其配置的上游地址下载。
未缓存时不能保证离线运行，下载中断时可在网络恢复后重试。

## 分发说明

模型、Python 依赖及 FFmpeg 各自适用其上游许可证和归属要求。
如需向他人分发可运行环境或模型，请分别检查对应版本的许可文件；
不要把本项目源代码的使用权限等同于全部第三方文件的再分发权限。
当前没有生成安装包或复制上游完整源代码，`.venv/` 和 `models/` 不纳入版本控制。

与设备相关的要求和当前验证范围见 [compatibility.md](compatibility.md)。
