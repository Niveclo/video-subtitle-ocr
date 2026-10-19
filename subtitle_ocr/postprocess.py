"""Conservative temporal grouping with traceable filtering and gap recovery."""

import copy
import re
from collections import Counter
from difflib import SequenceMatcher

from .config import ExportSettings


def normalize(text: str) -> str:
    return re.sub(r"[^\w]", "", text.casefold())


def _same(left: dict, right: dict, threshold: float) -> bool:
    for language in ("en", "zh"):
        a, b = normalize(left[language]), normalize(right[language])
        if bool(a) != bool(b):
            return False
        if a != b and SequenceMatcher(None, a, b).ratio() < threshold:
            return False
    return True


def group_frames(
    records: list[dict], fps: float, start: float, end: float, settings: ExportSettings
) -> list[dict]:
    cues, group = [], []
    half_interval = 0.5 / fps

    def finish() -> None:
        if not group:
            return
        confidences = [line["score"] for row in group for line in row["lines"]]
        cue = {
            "start": round(max(start, group[0]["time"] - half_interval), 6),
            "end": round(min(end, group[-1]["time"] + half_interval), 6),
            "en": Counter(row["en"] for row in group).most_common(1)[0][0],
            "zh": Counter(row["zh"] for row in group).most_common(1)[0][0],
            "sample_count": len(group),
            "min_confidence": min(confidences, default=0),
            "flags": [],
        }
        if group[0]["index"] == 0:
            cue["flags"].append("touches_window_start")
        if group[-1]["time"] + 1 / fps >= end - 1e-6:
            cue["flags"].append("touches_window_end")
        if cue["end"] > cue["start"]:
            cues.append(cue)

    for record in records:
        if not record["en"] and not record["zh"]:
            finish()
            group = []
        elif group and _same(group[0], record, settings.similarity):
            group.append(record)
        else:
            finish()
            group = [record]
    finish()
    return cues


def process(raw_cues: list[dict], settings: ExportSettings) -> tuple[list, list, list]:
    cues = copy.deepcopy(raw_cues)
    actions = []
    # Restore only a brief monolingual dropout bracketed by the same fully
    # bilingual caption. Do not bridge a genuine blank interval or changed text.
    for index in range(1, len(cues) - 1):
        before, current, after = cues[index - 1 : index + 2]
        if current["end"] - current["start"] > settings.bridge_seconds:
            continue
        if (
            abs(before["end"] - current["start"]) > 1e-5
            or abs(current["end"] - after["start"]) > 1e-5
        ):
            continue
        for missing, present in (("zh", "en"), ("en", "zh")):
            if (
                not current[missing]
                and current[present]
                and before[missing]
                and before[missing] == after[missing]
                and normalize(before[present])
                == normalize(current[present])
                == normalize(after[present])
            ):
                current[missing] = before[missing]
                current["flags"].append(f"recovered_{missing}_from_neighbors")
                actions.append(
                    {
                        "start": current["start"],
                        "end": current["end"],
                        "action": f"recover_{missing}_from_matching_neighbors",
                    }
                )

    merged = []
    for cue in cues:
        if (
            merged
            and merged[-1]["en"] == cue["en"]
            and merged[-1]["zh"] == cue["zh"]
            and abs(merged[-1]["end"] - cue["start"]) < 1e-5
        ):
            previous = merged[-1]
            previous["end"] = cue["end"]
            previous["sample_count"] += cue["sample_count"]
            previous["min_confidence"] = min(previous["min_confidence"], cue["min_confidence"])
            previous["flags"] = sorted(set(previous["flags"] + cue["flags"]))
        else:
            merged.append(cue)

    accepted, excluded = [], []
    for cue in merged:
        reasons = []
        if cue["end"] - cue["start"] + 1e-6 < settings.min_duration:
            reasons.append("shorter_than_min_duration")
        if settings.language == "bilingual" and (not cue["en"] or not cue["zh"]):
            reasons.append("missing_bilingual_text")
        elif settings.language == "english" and not cue["en"]:
            reasons.append("missing_english")
        elif settings.language == "chinese" and not cue["zh"]:
            reasons.append("missing_chinese")
        if reasons:
            excluded.append({**cue, "exclusion_reasons": reasons})
            continue
        if cue["min_confidence"] < settings.review_score:
            cue["flags"].append("low_confidence")
        if settings.language == "auto" and (not cue["en"] or not cue["zh"]):
            cue["flags"].append("single_language_candidate")
        cue["needs_review"] = bool(cue["flags"])
        cue["id"] = f"cue-{len(accepted) + 1:06}"
        accepted.append(cue)
    return accepted, excluded, actions
