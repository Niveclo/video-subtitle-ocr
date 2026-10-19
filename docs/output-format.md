# 输入输出数据契约 v1

下游学习 App 可以直接读取标准 SRT/VTT，也可以使用 `cues.json`。
两个项目只交换文件，不共享 Python 模块、GPU、模型或数据库。

## 任务目录

输入为单文件时，输出 `<output>/<stem>-<extension>/`。
目录输入时，在此之前保留视频相对于输入根目录的子目录。
例如 `courses/chapter1/lesson.mp4` 相对于 `courses` 输入，输出为
`<output>/chapter1/lesson-mp4/`。

所有输出采用 UTF-8，无 BOM。时间始终相对于原视频，单位为秒；
采样窗口不会归零。字幕起点包含、终点不包含：`start <= time < end`。
正式字幕按时间升序排列，去重不会跨真实空白区间拼接。

## cues.json

```json
{
  "schema_version": 1,
  "time_unit": "seconds",
  "time_reference": "original_video",
  "source": {
    "path": "D:\\Videos\\lesson.mp4",
    "size_bytes": 123456789,
    "mtime_ns": 1700000000000000000
  },
  "cues": [
    {
      "id": "cue-000001",
      "start": 8.125,
      "end": 10.875,
      "en": "When you look down on the Earth's surface",
      "zh": "俯瞰地球表面",
      "sample_count": 11,
      "min_confidence": 0.98,
      "flags": [],
      "needs_review": false
    }
  ]
}
```

示例置信度和文件身份仅说明格式，不是实测完整任务输出。

| 字段 | 含义 |
|---|---|
| `schema_version` | 当前为 1，遇到未知主版本应拒绝或显式迁移 |
| `source.path` | 原视频的本机绝对路径；手机不能直接读取此 Windows 路径 |
| `source.size_bytes / mtime_ns` | 轻量身份校验，不是完整内容哈希 |
| `id` | 当前导出中的条目 ID；重新导出后可能重新编号，不是永久外部 ID |
| `start / end` | 原视频秒数，`0 <= start < end` |
| `en / zh` | 按画面分离的文本，缺失时为空字符串 |
| `sample_count` | 合并的采样帧数量，不是原视频全部帧数量 |
| `min_confidence` | 相关 OCR 文本的最低分数，不是真实准确率 |
| `flags / needs_review` | 质量提示；无标记也不保证无误 |

`source.path` 是关联信息，不是网页可直接播放的 URL。
未来局域网 App 应把视频通过本机文件服务映射为 HTTP 地址，并映射对应字幕。

## 复核记录

`review.json` 包含：

- `excluded_candidates`：未进入正式字幕的完整候选及 `exclusion_reasons`。
- `recovery_actions`：根据前后相同字幕恢复短暂缺失语言的区间。
- `flagged_cue_ids`：需复核的正式条目 ID。

常见原因：

| 值 | 含义 |
|---|---|
| `shorter_than_min_duration` | 短于导出规则指定的最短时间 |
| `missing_bilingual_text` | 双语模式下缺少中英文之一 |
| `missing_english / missing_chinese` | 未满足语言保留规则 |
| `low_confidence` | 低于人工复核分数阈值 |
| `single_language_candidate` | auto 模式保留的单语候选 |
| `recovered_zh_from_neighbors / recovered_en_from_neighbors` | 根据前后相同字幕恢复 |
| `touches_window_start / touches_window_end` | 接近截取窗口边缘，可能不是完整条目 |

规则排除不等于确认错误；片名、单语注释、真实短句也可能被排除。
人工修改正式字幕文件后，不应再次执行 `export` 覆盖修改，或应先备份。

## 原始数据与状态

- `frames.jsonl`：每行是一个完整采样记录，包含从 0 开始的 `index`、
  原视频 `time`、`en`、`zh` 和 `lines`。每条 line 保存文本、分数、四点框和中心坐标。
  坐标基于裁剪并缩放后的 OCR 图像，非原视频坐标；换算参数在 `run.json.geometry` 中。
- `raw.cues.json`：按本次相似度参数整理的原始候选，尚未做语言过滤与邻居恢复。
  每次重新导出会更新；永久逐帧证据是 `frames.jsonl`。
- `run.json`：`pending`、`running`、`interrupted`、`failed`、`recognized`、`complete` 状态，
  以及来源身份、提取参数、裁剪尺寸、尝试记录和版本信息。
- `report.json`：本次导出参数、实际 provider、数量、警告、尝试耗时。
- `batch-report.json`：本次目录处理的摘要。下一次命令会更新此摘要，单任务原始日志仍保留。

消费字幕前应检查 `run.json.status == "complete"`。
`recognized` 表示 OCR 已完成但导出尚未完成；`failed` 或 `interrupted` 的任务目录
可能残留之前的导出文件，不应直接当作本次成功输出。

v1 允许增加说明性字段，下游可忽略未知字段；核心时间和文本语义改变时升级版本。
