"""Serial batch jobs, resumable frame logs, and OCR-independent export."""

import json
import math
import sys
import time
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path

from . import __version__
from .config import SCHEMA_VERSION, ExportSettings, ExtractionSettings
from .engine import OcrEngine
from .formats import export_subtitles
from .postprocess import group_frames, process
from .storage import now, read_frames, read_json, source_identity, write_json
from .video import frames, geometry, inspect_video


class EngineHolder:
    """Reuse one initialized engine across a serial batch."""

    def __init__(self, settings: ExtractionSettings, model_dir: Path):
        self.settings, self.model_dir = settings, model_dir
        self.engine = None

    def get(self) -> OcrEngine:
        if self.engine is None:
            self.engine = OcrEngine(self.settings, self.model_dir)
        return self.engine


def export_job(job: Path, settings: ExportSettings) -> dict:
    settings.validate()
    state = read_json(job / "run.json")
    if state.get("status") not in {"complete", "recognized"}:
        raise ValueError("任务尚未完整识别，不能导出正式字幕。请先 extract --resume。")
    records = read_frames(job / "frames.jsonl")
    extraction, window = state["extraction"], state["window"]
    raw = group_frames(records, extraction["fps"], window["start"], window["end"], settings)
    cues, excluded, actions = process(raw, settings)
    basename = Path(state["source"]["path"]).stem
    # Readers must not consume a partially replaced set of export files.
    state["status"] = "recognized"
    state.pop("exported_at", None)
    write_json(job / "run.json", state)
    write_json(job / "raw.cues.json", {"schema_version": SCHEMA_VERSION, "cues": raw})
    export_subtitles(cues, job, basename, state["source"])
    write_json(
        job / "review.json",
        {
            "schema_version": SCHEMA_VERSION,
            "excluded_candidates": excluded,
            "recovery_actions": actions,
            "flagged_cue_ids": [cue["id"] for cue in cues if cue["needs_review"]],
        },
    )
    warnings = list(state.get("engine_warnings", []))
    if not cues:
        warnings.append("未生成符合条件的字幕，请检查字幕区域、语言模式及原始候选。")
    report = {
        "schema_version": SCHEMA_VERSION,
        "tool_version": __version__,
        "source": state["source"],
        "video": state["video"],
        "window": window,
        "extraction": extraction,
        "export": asdict(settings),
        "providers": state.get("providers", {}),
        "model_dir": state["model_dir"],
        "dependency_versions": state["dependency_versions"],
        "sample_count": len(records),
        "raw_cue_count": len(raw),
        "cue_count": len(cues),
        "excluded_count": len(excluded),
        "recovery_count": len(actions),
        "needs_review_count": sum(cue["needs_review"] for cue in cues),
        "attempts": state["attempts"],
        "sampling_resolution_seconds": 1 / extraction["fps"],
        "warnings": warnings,
        "limitations": [
            "OCR confidence is not measured transcription accuracy.",
            "Times estimate visible subtitle boundaries, not speech alignment.",
            "Short or monolingual text may be withheld; see review.json.",
        ],
        "exported_at": now(),
    }
    write_json(job / "report.json", report)
    state["status"], state["exported_at"] = "complete", now()
    write_json(job / "run.json", state)
    return report


def _result(job: Path, report: dict) -> dict:
    return {
        "status": "complete",
        "output": str(job),
        "cue_count": report["cue_count"],
        "needs_review_count": report["needs_review_count"],
        "excluded_count": report["excluded_count"],
        "warnings": report["warnings"],
    }


def extract_job(
    source: Path,
    job: Path,
    settings: ExtractionSettings,
    policy: ExportSettings,
    holder: EngineHolder,
    *,
    resume: bool,
    overwrite: bool,
    skip_existing: bool,
) -> dict:
    identity = source_identity(source)
    dependencies = {
        name: version(name)
        for name in (
            "rapidocr",
            "onnxruntime-directml",
            "opencv-python-headless",
            "imageio-ffmpeg",
        )
    }
    manifest_path = job / "run.json"
    existing = read_json(manifest_path) if manifest_path.exists() and not overwrite else None
    matches = bool(
        existing
        and existing.get("source") == identity
        and existing.get("extraction") == settings.as_dict()
        and existing.get("tool_version") == __version__
        and existing.get("dependency_versions") == dependencies
        and existing.get("model_dir") == str(holder.model_dir.resolve())
    )
    if existing and skip_existing and matches and existing["status"] == "complete":
        report = read_json(job / "report.json")
        if report.get("export") != asdict(policy):
            raise ValueError("已有任务的导出参数不同；请使用 export 重新导出。")
        required = [job / "cues.json", job / "review.json", job / "frames.jsonl"]
        required += [
            job / f"{source.stem}.{lang}.{ext}"
            for lang in ("en", "zh", "bilingual")
            for ext in ("srt", "vtt", "txt")
        ]
        if not all(path.is_file() for path in required):
            raise ValueError("已有任务缺少输出文件；请使用 export 重新导出。")
        return {"status": "skipped", "output": str(job), "cue_count": report["cue_count"]}
    if resume and existing:
        if not matches:
            raise ValueError("恢复失败：视频身份、提取参数、工具/依赖版本或模型目录发生变化。")
        state = existing
        records = read_frames(job / "frames.jsonl", repair_tail=True)
    else:
        if job.exists() and any(job.iterdir()) and not overwrite:
            raise FileExistsError("输出目录非空；请选择 --resume、--skip-existing 或 --overwrite。")
        if resume and not existing and job.exists() and any(job.iterdir()):
            raise ValueError("输出目录缺少 run.json，无法恢复。")
        job.mkdir(parents=True, exist_ok=True)
        info = inspect_video(source)
        if settings.start >= info["duration_seconds"]:
            raise ValueError("start 已超出视频时长。")
        end = min(
            info["duration_seconds"],
            settings.start + settings.duration
            if settings.duration is not None
            else info["duration_seconds"],
        )
        state = {
            "schema_version": SCHEMA_VERSION,
            "tool_version": __version__,
            "status": "pending",
            "source": identity,
            "video": info,
            "extraction": settings.as_dict(),
            "window": {"start": settings.start, "end": end},
            "geometry": geometry(info, settings),
            "model_dir": str(holder.model_dir.resolve()),
            "dependency_versions": dependencies,
            "attempts": [],
            "created_at": now(),
            "export_defaults": asdict(policy),
        }
        write_json(manifest_path, state)
        # Only truncate this job's recognized files. Never recursively delete a directory.
        if overwrite:
            generated = [
                job / name
                for name in (
                    "cues.json",
                    "raw.cues.json",
                    "report.json",
                    "review.json",
                    "ffmpeg.log",
                )
            ]
            generated += [
                job / f"{source.stem}.{language}.{extension}"
                for language in ("en", "zh", "bilingual")
                for extension in ("srt", "vtt", "txt")
            ]
            for generated_file in generated:
                generated_file.unlink(missing_ok=True)
        (job / "frames.jsonl").write_bytes(b"")
        records = []
    window = state["window"]
    next_index = len(records)
    if (
        records
        and records[-1]["time"] + 1 / settings.fps >= window["end"] - 1e-6
        and state["status"] in {"complete", "recognized"}
    ):
        return _result(job, export_job(job, policy))
    attempt = {"started_at": now(), "first_sample_index": next_index}
    state["attempts"].append(attempt)
    state["status"] = "running"
    state.pop("last_error", None)
    write_json(manifest_path, state)
    started = time.perf_counter()
    try:
        engine = holder.get()
        state["providers"], state["engine_warnings"] = engine.providers(), engine.warnings
        write_json(manifest_path, state)
        print(f"OCR providers: {json.dumps(state['providers'])}", file=sys.stderr, flush=True)
        decoder = frames(
            source, settings, state["geometry"], window["end"], next_index, job / "ffmpeg.log"
        )
        expected = math.ceil((window["end"] - window["start"]) * settings.fps)
        try:
            with (job / "frames.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
                for index, sample_time, frame in decoder:
                    row = engine.recognize(frame, index, sample_time)
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                    stream.flush()
                    records.append(row)
                    if (index + 1) % 40 == 0:
                        print(
                            f"{source.name}: {index + 1}/{expected} 帧，"
                            f"本次耗时 {time.perf_counter() - started:.1f}s",
                            file=sys.stderr,
                            flush=True,
                        )
        finally:
            decoder.close()
        if not records or records[-1]["time"] + 1 / settings.fps < window["end"] - 1 / settings.fps:
            raise RuntimeError("解码提前结束，保留原始记录以便恢复；请查看 ffmpeg.log。")
        if source_identity(source) != identity:
            raise RuntimeError("处理期间源视频发生变化，结果未标为完成，请重新处理。")
        attempt.update(
            {
                "finished_at": now(),
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "new_sample_count": len(records) - next_index,
                "status": "complete",
            }
        )
        state["status"] = "recognized"
        write_json(manifest_path, state)
        report = export_job(job, policy)
        return _result(job, report)
    except (Exception, KeyboardInterrupt) as error:
        interrupted = isinstance(error, KeyboardInterrupt)
        attempt.update(
            {
                "finished_at": now(),
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "new_sample_count": len(records) - next_index,
                "status": "interrupted" if interrupted else "failed",
            }
        )
        state["status"] = "interrupted" if interrupted else "failed"
        state["last_error"] = str(error) or "KeyboardInterrupt"
        write_json(manifest_path, state)
        raise
