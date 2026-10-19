"""Standard subtitle files plus a versioned contract for downstream applications."""

import html
from pathlib import Path

from .config import SCHEMA_VERSION
from .storage import write_json


def timestamp(seconds: float, separator: str = ",") -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    whole_seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02}{separator}{milliseconds:03}"


def export_subtitles(cues: list[dict], directory: Path, basename: str, source: dict) -> None:
    for language in ("en", "zh", "bilingual"):
        srt, vtt, text_lines = [], ["WEBVTT\n"], []
        for cue in cues:
            content = (
                "\n".join(text for text in (cue["zh"], cue["en"]) if text)
                if language == "bilingual"
                else cue[language]
            )
            if not content:
                continue
            content = content.replace("\r", " ").strip()
            srt.append(
                f"{len(srt) + 1}\n{timestamp(cue['start'])} --> "
                f"{timestamp(cue['end'])}\n{content}\n"
            )
            # Escape text so <, >, and & cannot be mistaken for WebVTT markup.
            vtt.append(
                f"{timestamp(cue['start'], '.')} --> {timestamp(cue['end'], '.')}\n"
                f"{html.escape(content, quote=False)}\n"
            )
            text_lines.append(content)
        for suffix, content in (
            ("srt", "\n".join(srt)),
            ("vtt", "\n".join(vtt)),
            ("txt", "\n".join(text_lines) + ("\n" if text_lines else "")),
        ):
            (directory / f"{basename}.{language}.{suffix}").write_text(content, encoding="utf-8")
    write_json(
        directory / "cues.json",
        {
            "schema_version": SCHEMA_VERSION,
            "time_unit": "seconds",
            "time_reference": "original_video",
            "source": source,
            "cues": cues,
        },
    )
