# 命令行参考

在项目根目录执行 `uv run python -m subtitle_ocr <command>`。
进度和错误写入 stderr，完成摘要以 UTF-8 JSON 写入 stdout。
第三方原生库在异常情况下仍可能直接输出诊断内容，不宜把 stdout 当作严格的流式协议。

## doctor

```powershell
uv run python -m subtitle_ocr doctor
```

输出 Python、系统、CPU 描述、可用 provider、FFmpeg 路径和模型缓存情况。
不会下载模型、初始化 GPU 推理会话或执行 OCR；CPU 字符串未必包含完整商品型号。
`--model-dir PATH` 可以查看其他模型目录。

## inspect INPUT --output PATH

只接受单个本地视频。输出 `frame.jpg`、`region.jpg`、`inspection.json`。

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--at` | `60` | 截图的原视频秒数，必须位于时长范围内 |
| `--profile` | `generic` | `generic` 或 `planet-earth-ii` |
| `--region` | 继承预设 | `left,top,right,bottom`，0–1 坐标 |
| `--output` / `-o` | 必填 | 图片输出目录；已有同名图片时拒绝覆盖 |

绿色框标示识别范围。为兼容常见色度采样，像素坐标向下对齐到偶数，
与比例换算结果可能相差 1 像素，以 `inspection.json` 中的 `crop_pixels` 为准。

## extract INPUT

INPUT 为本地视频文件或目录。不加 `--duration` 时处理到估计的视频结尾。

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--output` / `-o` | 项目根目录下 `output/` | 总输出目录 |
| `--recursive` | 关闭 | 目录输入时扫描子目录 |
| `--profile` | `generic` | 通用区域或《地球脉动》预设 |
| `--region` | 继承预设 | 显式设置时覆盖预设区域 |
| `--language` | 继承预设 | `auto`、`bilingual`、`english`、`chinese` |
| `--fps` | `4` | 0.1–25，采样帧率；更高会增加开销，仍可能漏检 |
| `--start` | `0` | 非负，原视频秒数 |
| `--duration` | 未限制 | 正数秒；超出视频部分被截断 |
| `--max-width` | `1920` | OCR 输入区域的最大宽度，至少 64；不向上放大 |
| `--text-score` | `0.65` | 0–1，OCR 低于此分数的文本不进入帧文本 |
| `--device` | `auto` | 自动尝试 DirectML，或显式 `dml` / `cpu` |
| `--device-id` | `0` | DirectML 的 DXGI adapter index，非负 |
| `--cpu-threads` | `4` | CPU intra-op 线程数，正整数；超出库支持范围时由运行库决定 |
| `--model-dir` | 项目 `models/` | 本地模型缓存，缺失时由 RapidOCR 下载 |
| `--similarity` | `0.94` | 0.5–1，连续帧归为同条字幕的文本相似度阈值 |
| `--min-duration` | `0.5` | 非负秒，短于此值的候选放入复核记录 |
| `--review-score` | `0.90` | 0–1，低于此值标记待复核，不自动移除 |
| `--bridge-seconds` | `1.0` | 最长可恢复的单语漏检段；`0` 禁用恢复 |

`--resume`、`--skip-existing`、`--overwrite` 互斥：

| 选项 | 行为 |
|---|---|
| 都不指定 | 新任务；非空任务目录会报错 |
| `--resume` | 参数一致时恢复；完成任务重新导出；尚未开始的文件正常创建 |
| `--skip-existing` | 只跳过身份、提取参数、导出参数一致且输出齐全的完成任务 |
| `--overwrite` | 重新识别；仅覆盖本任务已知输出，不递归删除目录 |

恢复按下一个名义采样时间重新定位 FFmpeg，不保证与未中断运行逐像素相同。
仅完整 JSON 行用于恢复，不完整的最后一行可截断重写。
源视频以绝对路径、字节大小和修改时间判断身份，不对多 GB 文件做全量哈希。
不要在恢复期间替换模型。异常退出后的旧导出文件不能单独视为完成结果，
应检查 `run.json` 的 `status`。

### 语言模式

- `auto`：保留英文、中文或双语条目；单语条目标记为待复核。
- `bilingual`：要求一条字幕同时有中英文；缺少任一种时暂不纳入正式字幕。
- `english`：要求有英文；画面同时存在的中文仍保留。
- `chinese`：要求有中文；画面同时存在的英文仍保留。

这些模式控制候选保留规则，不是翻译开关或模型语言切换。
无论选择哪种模式，都输出 en / zh / bilingual 三组文件；某一组可为空。
默认模型主要针对中英文，不承诺其他文字体系的识别质量。

预设：

| 名称 | 区域 | 语言模式 |
|---|---|---|
| `generic` | `0,0.70,1,1` | `auto` |
| `planet-earth-ii` | `0,0.82,1,0.985` | `bilingual` |

## export JOB

JOB 是包含 `run.json`、`frames.jsonl` 的单视频任务目录。
状态为 `recognized` 或 `complete` 时可重新导出；其他状态应先恢复提取。
不执行 OCR、不访问源视频、不初始化引擎或下载模型。
当前实现仍需要项目依赖可正常导入。

可使用 `--language`、`--similarity`、`--min-duration`、`--review-score`、`--bridge-seconds`。
未给出的参数继承上一次导出；首次导出尚未完成时，继承 `run.json` 的初始设置。
不能用此命令修改识别区域、采样率或 `text-score`。

例如查看被双语模式排除的单语候选：

```powershell
uv run python -m subtitle_ocr export '.\output\第1集 岛屿-mp4' --language auto --min-duration 0
```

## 退出码

| 退出码 | 含义 |
|---|---|
| `0` | 全部处理完成或按要求跳过；可能仍有质量警告或空字幕 |
| `1` | 批量处理中至少一个文件失败，已继续处理其他文件 |
| `2` | 参数、输入、环境或单独导出命令错误 |
| `130` | 用户中断；提取过程中保留已写入的帧记录 |

不使用网络服务、账号、API Key、管理员权限或系统环境变量修改。
