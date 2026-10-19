"""Read-only video inspection and sequential, bounded-memory FFmpeg decoding."""

import math
import subprocess
from collections.abc import Iterator
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np

from .config import ExtractionSettings


def inspect_video(path: Path) -> dict:
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError(f"无法打开视频：{path}")
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = capture.get(cv2.CAP_PROP_FPS)
        frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if width <= 0 or height <= 0 or not math.isfinite(fps) or fps <= 0 or frames <= 0:
            raise ValueError("无法取得可靠的视频尺寸、帧率或时长；不支持此文件或直播流。")
        return {
            "width": width,
            "height": height,
            "fps": fps,
            "frame_count": frames,
            "duration_seconds": frames / fps,
        }
    finally:
        capture.release()


def geometry(info: dict, settings: ExtractionSettings) -> dict:
    width, height = info["width"], info["height"]
    left, top, right, bottom = settings.region
    # Chroma subsampling in common videos requires even crop coordinates.
    x, y = int(left * width) // 2 * 2, int(top * height) // 2 * 2
    right_px, bottom_px = int(right * width) // 2 * 2, int(bottom * height) // 2 * 2
    crop_width, crop_height = right_px - x, bottom_px - y
    if crop_width < 2 or crop_height < 2:
        raise ValueError("字幕区域在当前视频中不足 2 × 2 像素。")
    output_width = min(settings.max_width, crop_width)
    output_height = max(2, round(crop_height * output_width / crop_width))
    return {
        "crop_pixels": [x, y, right_px, bottom_px],
        "output_width": output_width,
        "output_height": output_height,
    }


def save_preview(path: Path, output: Path, settings: ExtractionSettings, at: float) -> dict:
    info = inspect_video(path)
    if not math.isfinite(at) or not 0 <= at < info["duration_seconds"]:
        raise ValueError("at 必须位于视频时长范围内。")
    output.mkdir(parents=True, exist_ok=True)
    targets = [output / "frame.jpg", output / "region.jpg", output / "inspection.json"]
    if any(target.exists() for target in targets):
        raise FileExistsError("预览文件已存在，请使用新的 --output 目录。")
    capture = cv2.VideoCapture(str(path))
    try:
        capture.set(cv2.CAP_PROP_POS_MSEC, at * 1000)
        ok, frame = capture.read()
        if not ok:
            raise ValueError(f"无法读取 {at} 秒处画面。")
    finally:
        capture.release()
    shape = geometry(info, settings)
    x, y, right, bottom = shape["crop_pixels"]
    crop = frame[y:bottom, x:right]
    marked = frame.copy()
    cv2.rectangle(marked, (x, y), (right - 1, bottom - 1), (0, 220, 100), 5)
    for target, image in ((targets[0], marked), (targets[1], crop)):
        ok, encoded = cv2.imencode(".jpg", image)
        if not ok:
            raise RuntimeError(f"无法生成预览图片：{target}")
        encoded.tofile(target)
    return {"source": str(path), "sample_time_seconds": at, "video": info, **shape}


def _read_exact(stream, count: int) -> bytes:
    data = bytearray()
    while len(data) < count:
        chunk = stream.read(count - len(data))
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


def frames(
    path: Path,
    settings: ExtractionSettings,
    shape: dict,
    end: float,
    first_index: int,
    log_path: Path,
) -> Iterator[tuple[int, float, np.ndarray]]:
    """Resume at the next nominal sample time; no full-video frame cache in RAM."""
    start = settings.start + first_index / settings.fps
    if start >= end:
        return
    x, y, right, bottom = shape["crop_pixels"]
    width, height = shape["output_width"], shape["output_height"]
    filters = (
        f"fps={settings.fps}:start_time=0,"
        f"crop={right - x}:{bottom - y}:{x}:{y},scale={width}:{height}"
    )
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-ss",
        str(start),
        "-i",
        str(path),
        "-t",
        str(end - start),
        "-an",
        "-sn",
        "-vf",
        filters,
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "pipe:1",
    ]
    with log_path.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log)
        try:
            index = first_index
            while data := _read_exact(process.stdout, width * height * 3):
                if len(data) != width * height * 3:
                    raise RuntimeError("FFmpeg 输出了不完整的视频帧，请查看 ffmpeg.log。")
                sample_time = settings.start + index / settings.fps
                if sample_time >= end:
                    break
                yield (
                    index,
                    sample_time,
                    np.frombuffer(data, dtype=np.uint8).reshape(height, width, 3),
                )
                index += 1
            # FFmpeg may emit a final rounded sample at the end of the interval.
            # Drain it before waiting so the pipe cannot block process shutdown.
            while process.stdout.read(1024 * 1024):
                pass
            if process.wait() != 0:
                raise RuntimeError("FFmpeg 解码失败，请查看输出目录中的 ffmpeg.log。")
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
