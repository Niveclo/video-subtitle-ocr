"""Serializable settings shared by extraction and offline export."""

import math
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 1
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".m4v", ".avi", ".webm", ".ts", ".mts"}
PROFILES = {
    "generic": {"region": (0.0, 0.70, 1.0, 1.0), "language": "auto"},
    "planet-earth-ii": {"region": (0.0, 0.82, 1.0, 0.985), "language": "bilingual"},
}


@dataclass(frozen=True)
class ExtractionSettings:
    region: tuple[float, float, float, float]
    fps: float = 4.0
    start: float = 0.0
    duration: float | None = None
    max_width: int = 1920
    text_score: float = 0.65
    device: str = "auto"
    device_id: int = 0
    cpu_threads: int = 4

    def validate(self) -> None:
        values = [*self.region, self.fps, self.start, self.text_score]
        if self.duration is not None:
            values.append(self.duration)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("参数必须是有限数值，不能使用 NaN 或 Infinity。")
        left, top, right, bottom = self.region
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise ValueError("region 格式为 left,top,right,bottom，值应在 0–1 且右下大于左上。")
        if not 0.1 <= self.fps <= 25 or self.start < 0:
            raise ValueError("fps 范围为 0.1–25，start 必须大于等于 0。")
        if self.duration is not None and self.duration <= 0:
            raise ValueError("duration 必须大于 0。")
        if self.max_width < 64 or not 0 <= self.text_score <= 1:
            raise ValueError("max-width 至少为 64；text-score 范围为 0–1。")
        if self.device_id < 0 or self.cpu_threads < 1:
            raise ValueError("device-id 必须非负；cpu-threads 必须为正整数。")

    def as_dict(self) -> dict:
        value = asdict(self)
        value["region"] = list(self.region)
        return value


@dataclass(frozen=True)
class ExportSettings:
    language: str = "auto"
    similarity: float = 0.94
    min_duration: float = 0.5
    review_score: float = 0.90
    bridge_seconds: float = 1.0

    def validate(self) -> None:
        if not all(
            math.isfinite(value) for value in asdict(self).values() if isinstance(value, float)
        ):
            raise ValueError("导出参数必须是有限数值。")
        if self.language not in {"auto", "bilingual", "english", "chinese"}:
            raise ValueError("未知字幕语言模式。")
        if not 0.5 <= self.similarity <= 1 or not 0 <= self.review_score <= 1:
            raise ValueError("similarity 范围为 0.5–1；review-score 范围为 0–1。")
        if self.min_duration < 0 or self.bridge_seconds < 0:
            raise ValueError("min-duration 和 bridge-seconds 不能为负。")
