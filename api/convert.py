"""Docling conversion adapter used by POST /convert.

The conversion itself remains the engine code (`engine.convert`).  This module only:
  * checks that Docling is importable before starting (clear 503 instead of a vague
    "failed" status caused by an ImportError hidden inside the retry cascade);
  * validates the file extension;
  * returns the engine's summary dict.
"""
from __future__ import annotations

import importlib.util
import shutil
import uuid
from pathlib import Path

from engine.convert import SUPPORTED_SUFFIXES, make_converter, plan_attempts, process_file


def docling_available() -> bool:
    """True when the `docling` package can be imported."""
    return importlib.util.find_spec("docling") is not None


def safe_upload_name(filename: str | None) -> str:
    """Strip directories from an uploaded name and add a short unique prefix."""
    name = Path(filename or "upload.bin").name
    return f"{uuid.uuid4().hex[:8]}_{name}"


def save_upload(file_obj, upload_dir: str | Path, filename: str | None) -> Path:
    """Copy a FastAPI UploadFile's stream to disk and return the path."""
    upload_dir = Path(upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / safe_upload_name(filename)
    with target.open("wb") as handle:
        shutil.copyfileobj(file_obj, handle)
    return target


def convert_file(
    source: str | Path,
    out_root: str | Path,
    accurate: bool = False,
    ocr: bool = False,
    fallback: bool = True,
) -> dict:
    """Run the engine with its retry cascade and return `summary.json` as a dict."""
    if not docling_available():
        raise RuntimeError(
            "Docling is not installed in this Python environment. "
            "Install it with `pip install -r requirements.txt`, or ingest an existing "
            "engine output folder and call POST /reload."
        )
    source = Path(source)
    if source.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(
            f"unsupported file type {source.suffix!r}; supported: {sorted(SUPPORTED_SUFFIXES)}"
        )
    plan = plan_attempts(source, accurate=accurate, ocr=ocr, vlm=False, fallback=fallback)
    cache: dict[str, object] = {}

    def get_converter(mode: str):
        if mode not in cache:
            cache[mode] = make_converter(mode)
        return cache[mode]

    return process_file(source, Path(out_root), plan, get_converter)
