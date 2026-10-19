"""Version-pinned RapidOCR adapter; provider choices are reported, not assumed."""

import re
import sys
from pathlib import Path

import onnxruntime as ort
from rapidocr import RapidOCR
from rapidocr.inference_engine.onnxruntime.main import OrtInferSession
from rapidocr.inference_engine.onnxruntime.provider_config import ProviderConfig

from .config import ExtractionSettings

_ORIGINAL_OPTIONS = OrtInferSession._init_sess_opts
_ORIGINAL_PROVIDERS = ProviderConfig.get_ep_list


def _session_options(config):
    options = _ORIGINAL_OPTIONS(config)
    if config.get("use_dml", False):
        options.enable_mem_pattern = False
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    return options


def _providers(config):
    # RapidOCR 3.10.0 supplies an OmegaConf DictConfig for custom DML options.
    return [(name, dict(options)) for name, options in _ORIGINAL_PROVIDERS(config)]


class OcrEngine:
    def __init__(self, settings: ExtractionSettings, model_dir: Path):
        # Process-local compatibility adapters; never edit site-packages or the OS.
        OrtInferSession._init_sess_opts = staticmethod(_session_options)
        ProviderConfig.get_ep_list = _providers
        self.settings = settings
        self.model_dir = model_dir.resolve()
        self.warnings = []
        wants_dml = (
            settings.device != "cpu" and "DmlExecutionProvider" in ort.get_available_providers()
        )
        if settings.device == "dml" and not wants_dml:
            raise RuntimeError("DirectML provider 不可用。请检查环境，或显式选择 --device cpu。")
        if settings.device == "auto" and not wants_dml:
            self.warnings.append("DirectML 不可用，auto 模式选择 CPU。")
        try:
            self.engine = self._load(wants_dml)
            actual = self.providers()
            if wants_dml and any(value[0] != "DmlExecutionProvider" for value in actual.values()):
                raise RuntimeError(f"DirectML 会话初始化后发生 CPU 回退：{actual}")
        except Exception as error:
            if settings.device != "auto" or not wants_dml:
                raise
            self.warnings.append(f"DirectML 初始化失败，auto 模式改用 CPU：{error}")
            self.engine = self._load(False)
        for warning in self.warnings:
            print(f"警告：{warning}", file=sys.stderr, flush=True)

    def _load(self, use_dml: bool):
        engine = RapidOCR(
            params={
                "Global.model_root_dir": str(self.model_dir),
                "Global.use_cls": False,
                "Global.text_score": self.settings.text_score,
                "Global.log_level": "error",
                "EngineConfig.onnxruntime.use_dml": use_dml,
                "EngineConfig.onnxruntime.dml_ep_cfg": {"device_id": str(self.settings.device_id)},
                "EngineConfig.onnxruntime.intra_op_num_threads": self.settings.cpu_threads,
                "EngineConfig.onnxruntime.inter_op_num_threads": 1,
                "Det.limit_side_len": 960,
            }
        )
        # Force both sessions to initialize even for a video without any text.
        engine._load_det_model()
        engine._load_rec_model()
        return engine

    def providers(self) -> dict:
        return {
            name: getattr(self.engine, name).session.session.get_providers()
            for name in ("text_det", "text_rec")
        }

    def recognize(self, frame, index: int, sample_time: float) -> dict:
        result = self.engine(frame)
        lines = []
        if result.txts is not None:
            for box, text, score in zip(result.boxes, result.txts, result.scores, strict=True):
                text = text.strip()
                if text:
                    lines.append(
                        {
                            "text": text,
                            "score": round(float(score), 6),
                            "box": box.tolist(),
                            "x": float(box[:, 0].mean()),
                            "y": float(box[:, 1].mean()),
                        }
                    )
        # Cluster actual line centers rather than relying on rounding-bin edges.
        rows = []
        for line in sorted(lines, key=lambda item: item["y"]):
            if rows and abs(rows[-1][0]["y"] - line["y"]) < 15:
                rows[-1].append(line)
            else:
                rows.append([line])
        lines = [line for row in rows for line in sorted(row, key=lambda item: item["x"])]
        en, zh = [], []
        for line in lines:
            if re.search(r"[\u3400-\u9fff]", line["text"]):
                zh.append(line["text"])
            elif re.search(r"[A-Za-z0-9]", line["text"]):
                en.append(line["text"])
        return {
            "index": index,
            "time": sample_time,
            "en": " ".join(en),
            "zh": " ".join(zh),
            "lines": lines,
        }
