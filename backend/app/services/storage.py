"""Uploaded-file storage on a local volume. Files get random names; the original filename
lives only in the database, so user input never becomes a path component."""

import shutil
import uuid
from pathlib import Path

from app.core.config import Settings


def _course_dir(settings: Settings, course_id: uuid.UUID) -> Path:
    return Path(settings.upload_dir) / str(course_id)


def save(settings: Settings, course_id: uuid.UUID, doc_id: uuid.UUID, ext: str, data: bytes) -> str:
    directory = _course_dir(settings, course_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{doc_id}{ext}"
    path.write_bytes(data)
    return str(path)


def delete(path: str) -> None:
    Path(path).unlink(missing_ok=True)


def delete_course_files(settings: Settings, course_id: uuid.UUID) -> None:
    shutil.rmtree(_course_dir(settings, course_id), ignore_errors=True)
