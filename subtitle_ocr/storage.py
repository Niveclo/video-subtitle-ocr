"""UTF-8 state files and source identities; video bytes are never rewritten."""

import json
from datetime import UTC, datetime
from pathlib import Path


def now() -> str:
    return datetime.now(UTC).isoformat()


def write_json(path: Path, value: object) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def source_identity(path: Path) -> dict:
    stat = path.stat()
    return {"path": str(path.resolve()), "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def read_frames(path: Path, *, repair_tail: bool = False) -> list[dict]:
    """Allow only a truncated final JSON line after an interrupted append."""
    rows = []
    mode = "r+b" if repair_tail else "rb"
    with path.open(mode) as stream:
        while True:
            offset = stream.tell()
            line = stream.readline()
            if not line:
                break
            try:
                if not line.endswith(b"\n"):
                    raise ValueError("末行未完整写入")
                row = json.loads(line)
                if row["index"] != len(rows):
                    raise ValueError("frame index 不连续")
                rows.append(row)
            except (ValueError, KeyError, TypeError) as error:
                if repair_tail and not line.endswith(b"\n") and not stream.read(1):
                    stream.seek(offset)
                    stream.truncate()
                    break
                raise ValueError(f"原始帧记录损坏：{path}，偏移 {offset}：{error}") from error
    return rows
