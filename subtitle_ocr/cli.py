"""Public CLI. Human progress goes to stderr; the final summary is JSON on stdout."""

import argparse
import json
import platform
import sys
from contextlib import redirect_stdout
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .config import PROFILES, PROJECT_ROOT, VIDEO_EXTENSIONS, ExportSettings, ExtractionSettings
from .storage import now, read_json, write_json


def _region(value: str) -> tuple[float, float, float, float]:
    try:
        numbers = tuple(float(part) for part in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("region 需要 4 个逗号分隔的数字。") from error
    if len(numbers) != 4:
        raise argparse.ArgumentTypeError("region 格式：left,top,right,bottom。")
    return numbers


def _video_options(parser) -> None:
    parser.add_argument("--profile", choices=PROFILES, default="generic")
    parser.add_argument("--region", type=_region, help="归一化 left,top,right,bottom，覆盖预设")


def _policy_options(parser, *, inherit: bool = False) -> None:
    parser.add_argument(
        "--language", choices=("auto", "bilingual", "english", "chinese"), default=None
    )
    parser.add_argument("--similarity", type=float, default=None if inherit else 0.94)
    parser.add_argument("--min-duration", type=float, default=None if inherit else 0.5)
    parser.add_argument("--review-score", type=float, default=None if inherit else 0.90)
    parser.add_argument("--bridge-seconds", type=float, default=None if inherit else 1.0)


def _policy(args) -> ExportSettings:
    value = ExportSettings(
        language=args.language or PROFILES[args.profile]["language"],
        similarity=args.similarity,
        min_duration=args.min_duration,
        review_score=args.review_score,
        bridge_seconds=args.bridge_seconds,
    )
    value.validate()
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="本地视频硬字幕 OCR（Windows x64 / Python 3.12）")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="查看环境，不下载模型或执行 OCR")
    doctor.add_argument("--model-dir", type=Path, default=PROJECT_ROOT / "models")
    inspect = commands.add_parser("inspect", help="导出画面和字幕区域预览")
    inspect.add_argument("input", type=Path)
    inspect.add_argument("--output", "-o", type=Path, required=True)
    inspect.add_argument("--at", type=float, default=60)
    _video_options(inspect)
    extract = commands.add_parser("extract", help="识别一个视频或目录中的视频")
    extract.add_argument("input", type=Path)
    extract.add_argument("--output", "-o", type=Path, default=PROJECT_ROOT / "output")
    extract.add_argument("--recursive", action="store_true")
    _video_options(extract)
    _policy_options(extract)
    extract.add_argument("--fps", type=float, default=4)
    extract.add_argument("--start", type=float, default=0)
    extract.add_argument("--duration", type=float)
    extract.add_argument("--max-width", type=int, default=1920)
    extract.add_argument("--text-score", type=float, default=0.65)
    extract.add_argument("--device", choices=("auto", "dml", "cpu"), default="auto")
    extract.add_argument("--device-id", type=int, default=0)
    extract.add_argument("--cpu-threads", type=int, default=4)
    extract.add_argument("--model-dir", type=Path, default=PROJECT_ROOT / "models")
    mode = extract.add_mutually_exclusive_group()
    mode.add_argument(
        "--resume", action="store_true", help="校验身份与参数后恢复；未开始的任务正常创建"
    )
    mode.add_argument(
        "--skip-existing", action="store_true", help="仅跳过参数匹配且输出齐全的完成任务"
    )
    mode.add_argument("--overwrite", action="store_true", help="重新识别并覆盖本任务生成的文件")
    export = commands.add_parser("export", help="根据 frames.jsonl 重新导出，不执行 OCR")
    export.add_argument("job", type=Path, help="包含 run.json 和 frames.jsonl 的单个任务目录")
    _policy_options(export, inherit=True)
    return parser


def _doctor(model_dir: Path) -> dict:
    import imageio_ffmpeg
    import onnxruntime

    return {
        "tool_version": __version__,
        "python": sys.version,
        "os": platform.platform(),
        "architecture": platform.machine(),
        "cpu": platform.processor(),
        "onnxruntime": onnxruntime.__version__,
        "available_providers": onnxruntime.get_available_providers(),
        "ffmpeg": imageio_ffmpeg.get_ffmpeg_exe(),
        "model_dir": str(model_dir.resolve()),
        "cached_models": sorted(path.name for path in model_dir.glob("*.onnx")),
        "note": "Provider 可用不代表特定 GPU 会话已成功初始化；extract 的 report.json 记录实际会话。",
    }


def _extract(args) -> tuple[dict, int]:
    from .pipeline import EngineHolder, extract_job

    source = args.input.resolve()
    if not source.exists():
        raise FileNotFoundError(f"输入不存在：{source}")
    if source.is_file():
        if source.suffix.lower() not in VIDEO_EXTENSIONS:
            raise ValueError(f"不支持的扩展名：{source.suffix}")
        videos, base = [source], source.parent
    else:
        candidates = source.rglob("*") if args.recursive else source.iterdir()
        videos = sorted(
            (
                path
                for path in candidates
                if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
            ),
            key=lambda path: str(path).casefold(),
        )
        base = source
    if not videos:
        raise ValueError("输入目录中未找到支持的视频文件。")
    settings = ExtractionSettings(
        region=args.region or PROFILES[args.profile]["region"],
        fps=args.fps,
        start=args.start,
        duration=args.duration,
        max_width=args.max_width,
        text_score=args.text_score,
        device=args.device,
        device_id=args.device_id,
        cpu_threads=args.cpu_threads,
    )
    settings.validate()
    policy = _policy(args)
    holder = EngineHolder(settings, args.model_dir.resolve())
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    jobs = []
    for video in videos:
        relative = video.relative_to(base)
        job = output / relative.parent / f"{video.stem}-{video.suffix[1:].lower()}"
        print(f"处理：{video}", file=sys.stderr, flush=True)
        try:
            with redirect_stdout(sys.stderr):
                result = extract_job(
                    video,
                    job,
                    settings,
                    policy,
                    holder,
                    resume=args.resume,
                    overwrite=args.overwrite,
                    skip_existing=args.skip_existing,
                )
            jobs.append({"source": str(video), **result})
        except KeyboardInterrupt:
            jobs.append({"source": str(video), "output": str(job), "status": "interrupted"})
            summary = {"finished_at": now(), "jobs": jobs, "interrupted": True}
            write_json(output / "batch-report.json", summary)
            return summary, 130
        except Exception as error:
            print(f"失败：{video.name}：{error}", file=sys.stderr, flush=True)
            jobs.append(
                {"source": str(video), "output": str(job), "status": "failed", "error": str(error)}
            )
    summary = {
        "finished_at": now(),
        "jobs": jobs,
        "failed_count": sum(job["status"] == "failed" for job in jobs),
    }
    write_json(output / "batch-report.json", summary)
    return summary, 1 if summary["failed_count"] else 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = _parser()
    args = parser.parse_args()
    if sys.platform != "win32" or platform.machine().upper() not in {"AMD64", "X86_64"}:
        parser.error("本项目锁定 Windows x64；其他设备兼容说明见 docs/compatibility.md。")
    try:
        code = 0
        if args.command == "doctor":
            result = _doctor(args.model_dir)
        elif args.command == "inspect":
            from .video import save_preview

            settings = ExtractionSettings(region=args.region or PROFILES[args.profile]["region"])
            settings.validate()
            result = save_preview(args.input.resolve(), args.output.resolve(), settings, args.at)
            write_json(args.output.resolve() / "inspection.json", result)
        elif args.command == "extract":
            result, code = _extract(args)
        else:
            from .pipeline import export_job

            # Export defaults to the previous export policy, including its language.
            report_path = args.job.resolve() / "report.json"
            previous = (
                read_json(report_path)["export"]
                if report_path.exists()
                else read_json(args.job.resolve() / "run.json")["export_defaults"]
            )
            supplied = vars(args)
            policy_keys = asdict(ExportSettings()).keys()
            policy = ExportSettings(
                **{
                    key: previous[key] if supplied[key] is None else supplied[key]
                    for key in policy_keys
                }
            )
            policy.validate()
            result = export_job(args.job.resolve(), policy)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    except KeyboardInterrupt:
        print("已中断。", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2
