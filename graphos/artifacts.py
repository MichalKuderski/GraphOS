"""Immutable UTF-8 artifact bundles with verified content-addressed storage."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from typing import Any

MAX_FILES = 64
MAX_FILE_BYTES = 512 * 1024
MAX_BUNDLE_BYTES = 2 * 1024 * 1024
MAX_JSON_BYTES = 1024 * 1024
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_PATH = re.compile(r"[A-Za-z0-9._/-]{1,160}\Z")
_RESERVED = {".git", ".hg", ".svn", ".env", "node_modules", "__pycache__"}
_DEVICES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
            *(f"lpt{i}" for i in range(1, 10))}


class ArtifactError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ArtifactError("artifact is not canonical UTF-8 JSON") from exc


def validate_digest(value: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ArtifactError("invalid SHA-256 digest")
    return value


def validate_files(files: dict[str, str]) -> dict[str, bytes]:
    if not isinstance(files, dict) or not 1 <= len(files) <= MAX_FILES:
        raise ArtifactError(f"bundle requires 1..{MAX_FILES} files")
    normalized: dict[str, bytes] = {}
    seen: set[str] = set()
    total = 0
    for name, content in files.items():
        if not isinstance(name, str) or not _PATH.fullmatch(name):
            raise ArtifactError("invalid artifact path")
        parts = name.split("/")
        if (name.startswith("/") or any(p in {"", ".", ".."} for p in parts)
                or str(PurePosixPath(name)) != name):
            raise ArtifactError("artifact paths must be normalized relative POSIX paths")
        for part in parts:
            lowered = part.lower()
            if (part.endswith(".") or lowered in _RESERVED or lowered.startswith(".env.")
                    or lowered.split(".", 1)[0] in _DEVICES):
                raise ArtifactError("reserved artifact path")
        if name.casefold() in seen:
            raise ArtifactError("case-colliding artifact paths")
        seen.add(name.casefold())
        if not isinstance(content, str):
            raise ArtifactError("bundle contents must be UTF-8 strings, never filesystem paths")
        try:
            data = content.encode("utf-8")
        except UnicodeError as exc:
            raise ArtifactError("invalid UTF-8 content") from exc
        if len(data) > MAX_FILE_BYTES:
            raise ArtifactError("artifact file exceeds size limit")
        total += len(data)
        if total > MAX_BUNDLE_BYTES:
            raise ArtifactError("artifact bundle exceeds size limit")
        normalized[name] = data
    # Reject a file that is also another file's parent (including case aliases).
    for name in normalized:
        if any(str(parent).casefold() in seen for parent in PurePosixPath(name).parents
               if str(parent) != "."):
            raise ArtifactError("file/directory path collision")
    return normalized


def bundle_digest(files: dict[str, str]) -> str:
    validated = validate_files(files)
    manifest = {"kind": "bundle", "version": 1, "files": [
        {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
        for name, data in sorted(validated.items())]}
    return hashlib.sha256(canonical(manifest)).hexdigest()


def _reject_symlink_components(path: Path) -> None:
    absolute = path.absolute()
    for component in (absolute, *absolute.parents):
        if component.is_symlink():
            raise ArtifactError("symlink directory is not allowed")


def _safe_directory(path: Path) -> None:
    _reject_symlink_components(path)
    absolute = path.absolute()
    if not absolute.is_dir():
        raise ArtifactError("artifact directory is missing")


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = Path(root).absolute()
        _reject_symlink_components(self.root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        _safe_directory(self.root)
        self.objects = self.root / "objects"
        self.objects.mkdir(exist_ok=True, mode=0o700)
        _safe_directory(self.objects)

    def _read(self, digest: str, limit: int) -> bytes:
        validate_digest(digest)
        _safe_directory(self.objects)
        try:
            descriptor = os.open(self.objects / digest, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                    raise ArtifactError("invalid stored object type or size")
                data = stream.read(limit + 1)
        except OSError as exc:
            raise ArtifactError("artifact object unavailable or unsafe") from exc
        if len(data) > limit or hashlib.sha256(data).hexdigest() != digest:
            raise ArtifactError("artifact object failed content verification")
        return data

    def _write(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        _safe_directory(self.objects)
        target = self.objects / digest
        descriptor, name = tempfile.mkstemp(prefix=".pending-", dir=self.objects)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
                os.fchmod(stream.fileno(), 0o444)
            try:
                os.link(name, target, follow_symlinks=False)
            except FileExistsError:
                if self._read(digest, max(len(data), 1)) != data:
                    raise ArtifactError("existing content-addressed object differs")
            directory = os.open(self.objects, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            os.unlink(name)
        return digest

    def put_bundle(self, files: dict[str, str]) -> str:
        validated = validate_files(files)
        manifest = {"kind": "bundle", "version": 1, "files": [
            {"path": name, "sha256": self._write(data), "size": len(data)}
            for name, data in sorted(validated.items())]}
        return self._write(canonical(manifest))

    def get_bundle(self, digest: str) -> dict[str, str]:
        try:
            manifest = json.loads(self._read(digest, MAX_JSON_BYTES))
            if (not isinstance(manifest, dict) or set(manifest) != {"kind", "version", "files"}
                    or manifest["kind"] != "bundle" or manifest["version"] != 1
                    or not isinstance(manifest["files"], list)
                    or not 1 <= len(manifest["files"]) <= MAX_FILES):
                raise ArtifactError("invalid bundle manifest")
            files: dict[str, str] = {}
            total = 0
            for entry in manifest["files"]:
                if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size"}:
                    raise ArtifactError("invalid manifest entry")
                if not isinstance(entry["path"], str) or entry["path"] in files:
                    raise ArtifactError("duplicate or invalid manifest path")
                if type(entry["size"]) is not int or not 0 <= entry["size"] <= MAX_FILE_BYTES:
                    raise ArtifactError("invalid manifest size")
                total += entry["size"]
                if total > MAX_BUNDLE_BYTES:
                    raise ArtifactError("manifest exceeds bundle size limit")
                data = self._read(entry["sha256"], MAX_FILE_BYTES)
                if len(data) != entry["size"]:
                    raise ArtifactError("manifest size mismatch")
                files[entry["path"]] = data.decode("utf-8")
            validate_files(files)
            return files
        except (json.JSONDecodeError, UnicodeError, KeyError, TypeError) as exc:
            raise ArtifactError("invalid bundle data") from exc

    def put_json(self, value: dict) -> str:
        if not isinstance(value, dict):
            raise ArtifactError("evidence must be a JSON object")
        data = canonical({"kind": "json", "version": 1, "value": value})
        if len(data) > MAX_JSON_BYTES:
            raise ArtifactError("JSON evidence exceeds size limit")
        return self._write(data)

    def get_json(self, digest: str) -> dict:
        try:
            value = json.loads(self._read(digest, MAX_JSON_BYTES))
            if (not isinstance(value, dict) or set(value) != {"kind", "version", "value"}
                    or value["kind"] != "json" or value["version"] != 1
                    or not isinstance(value["value"], dict)):
                raise ArtifactError("invalid JSON evidence envelope")
            return value["value"]
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ArtifactError("invalid JSON evidence") from exc

    def materialize(self, digest: str, destination: Path) -> None:
        materialize_files(self.get_bundle(digest), destination)


def materialize_files(files: dict[str, str], destination: Path) -> None:
    validated = validate_files(files)
    destination = Path(destination).absolute()
    _reject_symlink_components(destination)
    destination.mkdir(exist_ok=True, mode=0o755)
    _safe_directory(destination)
    if any(destination.iterdir()):
        raise ArtifactError("materialization destination must be empty")
    destination.chmod(0o755)
    for name, data in sorted(validated.items()):
        target = destination / name
        parent = destination
        for part in PurePosixPath(name).parts[:-1]:
            parent = parent / part
            parent.mkdir(exist_ok=True, mode=0o755)
            _safe_directory(parent)
            parent.chmod(0o755)
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            os.fchmod(stream.fileno(), 0o444)
