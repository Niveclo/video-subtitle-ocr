# Video Subtitle OCR

从本地视频画面中的**硬字幕**提取中英文文字和显示时间，输出标准字幕文件。
可用于纪录片、课程或其他已经压制字幕的视频，并供独立的听力学习 App 使用。

采用 **Python 3.12 + uv + RapidOCR / PP-OCRv6 + ONNX Runtime DirectML**。
目前提供本地命令行工具，面向 Windows x64。视频、截图和识别结果在本机处理；
首次缺少模型时会联网下载模型，缓存完成后可离线使用。

## 能做什么

- 单个视频或整个目录输入，可递归扫描子目录。
- 配置字幕区域、采样频率、起点和处理时长。
- 输出英文、中文、双语三组 **SRT、WebVTT、TXT**，以及结构化 JSON。
- 合并连续重复字幕；谨慎恢复同一句中短暂漏识别的一门语言。
- 保留逐帧 OCR、原始字幕候选、过滤原因和待复核标记。
- 中断后恢复，批量任务跳过已完成文件，修改过滤参数后直接重新导出。
- `auto`、`dml`、`cpu` 三种设备选择；报告记录实际启用的 provider。

本工具读取画面文字，不从声音生成字幕，不翻译，不提取软字幕轨道，
也不执行发音对齐。没有画面字幕的视频不适用。
“一条字幕”按画面显示区间划分，可能只是一个长句的部分内容。

## 环境

当前项目锁定 **Windows x64 / Python 3.12**，使用 uv 创建项目内的 `.venv/`。
FFmpeg 来自 `imageio-ffmpeg` 依赖，无需单独安装系统 FFmpeg、CUDA、PaddlePaddle 或编译工具。
CPU 模式仍使用同一套项目依赖。

本机方案验证环境：

| 项目 | 配置 |
|---|---|
| 系统 | Windows 11 Pro，64 位 |
| CPU | AMD Ryzen 7 9700X，8 核 16 线程 |
| GPU | AMD Radeon RX 9070 XT；另有 Radeon 核显 |
| Python | CPython 3.12.15，由 uv 管理 |
| OCR | RapidOCR 3.10.0，PP-OCRv6 small 检测与识别模型 |
| 推理 | ONNX Runtime DirectML 1.24.4 |

先前验证项目对 4K/25fps 视频的前 3 分钟进行了 720 帧 OCR，识别阶段约 102 秒。
该数据只代表验证脚本和该片段；不能视为本项目正式版、其他设备或整季的性能保证。
provider 名称不等于具体显卡名称，多显卡机器请结合 `--device-id` 和实际 GPU 使用情况判断。

详见 [设备与平台兼容说明](docs/compatibility.md)。

## 安装和快速开始

需要已有的 uv。若没有 uv，请先自行安装；本项目不会修改系统环境。
下列命令在项目根目录的 PowerShell 中执行：

```powershell
Set-Location 'D:\Resources\NIVECLO_SPACE\Projects\video-subtitle-ocr'
uv sync --locked --python 3.12 --link-mode copy
uv run python -m subtitle_ocr doctor
```

无需激活虚拟环境。复制到其他目录后，只需切换到新的项目根目录。
依赖版本保存在 `uv.lock`。本机已把验证过的两套模型复制到 `models/`，无需再次下载。
源代码共享时不包含 `.venv/`、`models/` 和 `output/`。

### 1. 先查看字幕区域

```powershell
uv run python -m subtitle_ocr inspect `
  'C:\Users\Niveclo\Videos\Planet Earth II\第1集 岛屿.mp4' `
  --profile planet-earth-ii --at 60 --output '.\output\preview-islands'
```

查看生成的 `frame.jpg`（绿色区域框）和 `region.jpg`（实际识别范围）。
预览目录中已有同名文件时会拒绝覆盖，可换一个输出目录。
预览不执行 OCR、不下载模型。

### 2. 识别单个视频

```powershell
uv run python -m subtitle_ocr extract `
  'C:\Users\Niveclo\Videos\Planet Earth II\第1集 岛屿.mp4' `
  --profile planet-earth-ii --output '.\output'
```

默认处理整个视频。可以先增加 `--duration 180` 查看短片段结果。
`planet-earth-ii` 预设使用已验证的画面高度 82%–98.5%，并要求字幕同时包含中英文。
它只是预设，不会按文件名或台词硬编码字幕内容。

### 3. 批量处理整个目录

```powershell
uv run python -m subtitle_ocr extract `
  'C:\Users\Niveclo\Videos\Planet Earth II' `
  --profile planet-earth-ii --output '.\output' --skip-existing
```

任务串行处理，共享一套 OCR 引擎；单个文件失败后继续后续文件。
`--recursive` 可扫描子目录。`output/batch-report.json` 记录本次批量结果。
这里没有自动开始整季处理，以上是供你执行的命令。

### 4. 处理其他视频

```powershell
uv run python -m subtitle_ocr inspect 'D:\Videos\lesson.mp4' `
  --region '0.05,0.76,0.95,0.98' --at 30 --output '.\output\preview-lesson'

uv run python -m subtitle_ocr extract 'D:\Videos\lesson.mp4' `
  --region '0.05,0.76,0.95,0.98' --language english --output '.\output'
```

`region` 顺序是 **left, top, right, bottom**，使用相对于整幅画面的 0–1 坐标。
未指定预设时，默认区域为画面底部 30%，语言模式为 `auto`。
字幕位置随镜头变化、遮挡或混有水印时，需要更仔细地复核输出。

## 输入与输出

输入是一个本地视频文件路径或目录路径，不通过 stdin 传输视频字节。
候选扩展名：`.mp4`、`.mkv`、`.mov`、`.m4v`、`.avi`、`.webm`、`.ts`、`.mts`；
能否读取仍取决于容器和编码，不支持网络地址、直播流或受保护视频。
中文和含空格的路径请始终加引号。

每个视频拥有独立任务目录，例如：

```text
output/
  batch-report.json
  第1集 岛屿-mp4/
    第1集 岛屿.en.srt
    第1集 岛屿.zh.srt
    第1集 岛屿.bilingual.srt
    第1集 岛屿.en.vtt          # 另有 zh、bilingual
    第1集 岛屿.en.txt          # 另有 zh、bilingual
    cues.json                # 下游 App 使用的结构化字幕
    report.json              # 参数、设备、数量、警告和耗时
    review.json              # 排除候选、恢复操作、待复核 ID
    raw.cues.json            # 去重后的原始字幕候选
    frames.jsonl             # 每个采样帧的原始 OCR
    run.json                 # 恢复任务所需的状态
    ffmpeg.log
```

目录名带原视频扩展名，可区分同目录中的 `lesson.mp4` 和 `lesson.mkv`。
递归处理时保留输入中的相对子目录。字幕均为 UTF-8，无 BOM；SRT 使用毫秒，
VTT 使用标准 WebVTT 时间格式，JSON 使用原视频的秒数。
即使处理片段从 600 秒开始，输出时间也从原视频的 600 秒附近开始，不归零。

听力 App 可以直接使用 SRT/VTT，或按 [输出数据契约](docs/output-format.md) 读取 `cues.json`。
没有识别到字幕时也会输出空字幕和警告；退出成功只表示处理完成，不代表质量合格。

## 中断、恢复和重新导出

按 Ctrl+C 中断后，保留已完整写入的 OCR 帧记录。
使用原命令和相同提取参数，增加 `--resume`：

```powershell
uv run python -m subtitle_ocr extract `
  'C:\Users\Niveclo\Videos\Planet Earth II' `
  --profile planet-earth-ii --output '.\output' --resume
```

恢复会检查视频路径、大小、修改时间、提取参数、模型目录及工具/依赖版本。
不满足条件时拒绝拼接；`--overwrite` 可显式重新处理本任务。
未带任何重用参数时，非空任务目录会被拒绝。
模型目录相同不等于模型文件内容相同，请勿在恢复期间手动替换模型。

修改导出过滤规则无需重新识别：

```powershell
uv run python -m subtitle_ocr export '.\output\第1集 岛屿-mp4' `
  --language auto --min-duration 0.25
```

`export` 从完成识别的任务重新生成字幕、候选和报告，并覆盖之前的导出文件，
不会改动 `frames.jsonl`。未指定的导出参数沿用上一次设置。
若要保留两份不同过滤规则的字幕，请先复制需要的导出文件。

所有命令参数、退出码和过滤行为见 [命令行参考](docs/cli.md)。

## 识别质量和时间轴

- 默认 4 fps 是 **0.25 秒采样分辨率**，不是整体时间误差保证。
- 画面字幕边界与发音边界可能不同；淡入淡出、漏检、短字幕会影响起止时间。
- 低于 `min-duration` 的候选、双语模式下缺少一门语言的候选会放入 `review.json`。
  它们可能是真实短句、片名、单语说明或误识别，并非自动判定为错误。
- 短暂单语漏检只有在前后中英文一致、区间相连时才恢复，恢复结果仍标为待复核。
- 模型置信度不是真实准确率。背景纹理也可能得到较高分数。
- 中英文沿用画面配对，译文可能跨条调整语序；不自动改写或重新翻译。
- 分段窗口首尾的字幕可能被截断，相关条目会标记 `touches_window_*`。
- 视频时长由 OpenCV 元数据估计；对可变帧率、损坏或特殊封装视频不保证精确覆盖。

本项目建议配合 Subtitle Edit 人工校对，先抽查片段，再处理长视频。

## 项目结构与开发检查

```text
subtitle_ocr/
  cli.py          # 命令行入口
  config.py       # 参数、预设与校验
  engine.py       # RapidOCR / DirectML 适配
  video.py        # 元数据、区域预览、FFmpeg 视频帧
  pipeline.py     # 任务状态、批量、恢复、重新导出
  postprocess.py  # 去重、短暂漏检恢复、过滤与复核标记
  formats.py      # SRT、VTT、TXT、JSON
  storage.py      # UTF-8 状态文件与原始帧日志
docs/
models/           # 本地缓存，不纳入版本控制
output/           # 本地结果，不纳入版本控制
```

此轮只执行静态检查，没有编译、构建、运行测试、运行正式 CLI 或进行整集识别：

```powershell
uv run ruff check subtitle_ocr
uv run ruff format --check subtitle_ocr
```

此前 `subtitle-extraction-lab` 的运行验证仍独立保留。
本项目的新增批量、恢复和导出流程尚未做运行验证。

[上游依赖和模型说明](docs/dependencies.md)。
