# 设备与平台兼容性

本项目以本机 Windows x64 环境为实现目标。本文件说明其他设备可能的适用条件，
没有为其他系统引入条件依赖、CUDA、ROCm、Metal 或其他执行后端。

## 已有方案验证

| 项目 | 验证环境 |
|---|---|
| 系统 | Windows 11 Pro，64 位；本次读取的系统版本为 10.0.26300 |
| Shell | PowerShell 7.6.6 |
| CPU | AMD Ryzen 7 9700X，8 核、16 线程 |
| GPU | AMD Radeon RX 9070 XT；另有 AMD Radeon(TM) Graphics 核显 |
| 独显驱动 | 本次读取到 32.0.31041.1004 |
| 内存 | 前期检查中系统可见约 23.2 GiB，不作为最低内存要求 |
| Python | 3.12.15，由已有 uv 管理 |
| 推理运行库 | ONNX Runtime DirectML 1.24.4 |
| OCR | RapidOCR 3.10.0，PP-OCRv6 small 检测/识别模型 |
| 视频样例 | H.264 MP4，3840 × 2160，25 fps |

前期实验确认检测、识别两套会话的首选 provider 均为 `DmlExecutionProvider`。
这证明 DirectML 会话成功建立，不单独证明每个算子在 GPU 执行，也不将 adapter 0
未经核实地等同于 RX 9070 XT。

前三分钟采样 720 帧，识别阶段约 101.8 秒；观察到背景误识别和一次中文短暂漏检。
这属于前期验证脚本的样例结果，正式项目本轮只完成静态检查。
本项目新增批量、恢复、过滤及标准化输出流程尚未执行运行验证。
未测量内存/显存峰值、连续整集表现或其他设备速度。

## 其他硬件

| 设备 | 当前项目适用情况 | 限制 |
|---|---|---|
| Windows x64 + AMD GPU | 与本机相同路径，可尝试 DirectML | 需 DirectX 12 设备及可用驱动；其他型号未验证 |
| Windows x64 + NVIDIA GPU | 理论上可走 DirectML，或选 CPU | 当前没有 CUDA 模式，不因安装 CUDA 自动加速 |
| Windows x64 + Intel GPU | 理论上可走 DirectML，或选 CPU | 型号、驱动和算子兼容性影响结果，未验证 |
| Windows x64、无可用 GPU | 可选择 CPU | 仍需运行库依赖可导入；新项目 CPU 路径未运行验证 |
| Windows ARM64 | 当前锁文件和入口未适配 | 不承诺通过仿真运行；需要另行选依赖并验证 |
| Linux | 当前依赖和入口未适配 | DirectML 为 Windows 路径；迁移需重新选 CPU/CUDA/其他后端 |
| macOS / Apple Silicon | 当前依赖和入口未适配 | 未接入 CoreML/Metal；不能直接照搬当前环境 |
| 手机 | 不用于字幕提取 | 未来学习 App 可以经局域网使用生成的标准字幕 |

DirectML 的官方要求是 DirectX 12 兼容设备，覆盖多厂商硬件，
但这不等于每个型号、驱动和模型组合都已被本项目验证。
参见 [ONNX Runtime DirectML 要求](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html#requirements)。

## 设备选择和回退

- `--device auto`：有 DML provider 时尝试建立 DirectML 会话；初始化失败或实际回退到 CPU 时，
  记录警告并重新用 CPU 初始化。识别过程中发生的错误会标为任务失败，不在中途悄悄换后端。
- `--device dml`：显式要求 DirectML；不可用或初始化后仅剩 CPU 时失败，不自动改用 CPU。
- `--device cpu`：只为会话请求 CPU provider，不执行 GPU 推理。
- `--device-id 0`：DirectML 的 DXGI adapter index。多显卡设备可尝试其他非负编号，
  非法编号会由运行库报告。它不保证与 PowerShell 枚举顺序或任务管理器编号一致。

可参考 [DirectML device_id 定义](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html#ortsessionoptionsappendexecutionprovider_dml)。
`doctor` 只报告 provider 是否可用；最终以任务 `report.json` 的 `providers` 和 `warnings` 为准。

## 环境边界

- 项目锁定 Python 3.12 系列和上游核心依赖版本；不自动迁移到系统 Python 3.14。
- uv 在 `.venv/` 中安装依赖，不注册系统命令、不改 PATH、不改显卡驱动。
- 已缓存模型约 30 MiB；环境、原始 OCR 日志和输出另占磁盘空间。
  长视频的 `frames.jsonl` 会持续增长，RAM 中会保留文本记录，不保留所有视频像素帧。
- 字幕区域越大、采样越密，开销通常越高。CPU 和 GPU 的实际收益需要按视频评估。
- 首次模型下载依赖网络和上游地址，离线前需确保两套模型均已缓存。
- 若 Windows 缺少运行库或驱动，应由用户处理系统级安装；本项目不会代为安装。
- 输出可以跨设备使用，SRT/VTT/UTF-8 JSON 不依赖 AMD 或 Windows。

## 为什么保留小范围兼容适配

固定的 RapidOCR 版本在自定义 provider 参数中会传递 OmegaConf 映射，
而 ONNX Runtime 要求普通字典。`engine.py` 在当前 Python 进程中进行转换。
同时，DirectML 会话使用顺序执行并禁用 memory pattern optimization，
符合 [官方会话要求](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html#configuration-options)。

适配没有修改第三方安装文件。它使用了上游内部初始化接口，因此升级 RapidOCR
或 ONNX Runtime 后应重新检查；恢复旧任务也会校验核心依赖版本。
