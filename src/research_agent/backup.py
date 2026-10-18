"""Offline, checksummed backups of a private workspace, without credentials/sessions."""

import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path, PurePosixPath

DATABASES = ("research.sqlite3", "checkpoints.sqlite3")
DIRECTORIES = ("library", "uploads", "paper-downloads", "outputs", "documents")


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def create_backup(data_dir: Path, destination: Path):
    root, destination = data_dir.resolve(), destination.resolve()
    if destination.exists() or destination.is_relative_to(root):
        raise ValueError("备份必须保存到数据目录之外的新文件，避免覆盖或递归备份")
    if not (root / "research.sqlite3").is_file():
        raise ValueError("没有可备份的工作空间数据库")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        stage = Path(temporary)
        for name in DATABASES:
            source = root / name
            if not source.exists():
                continue
            if source.is_symlink():
                raise ValueError("备份不接受符号链接")
            with (
                closing(sqlite3.connect(source)) as db,
                closing(sqlite3.connect(stage / name)) as target,
            ):
                if name == "research.sqlite3":
                    tasks = db.execute("SELECT body FROM tasks").fetchall()
                    if any(json.loads(row[0])["status"] in {"running", "pending"} for row in tasks):
                        raise ValueError("存在未结束任务，请先停止服务并处理任务状态后备份")
                db.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("数据库完整性检查失败")
        for directory in DIRECTORIES:
            source = root / directory
            if not source.exists():
                continue
            for path in [source, *source.rglob("*")]:
                if path.is_symlink() or not path.resolve().is_relative_to(root):
                    raise ValueError("备份目录包含链接或越界路径")
                if path.is_file():
                    target = stage / path.relative_to(root)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
        manifest = {
            "format": 1,
            "data_dir": str(root),
            "files": {
                p.relative_to(stage).as_posix(): checksum(p)
                for p in stage.rglob("*")
                if p.is_file()
            },
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        archive = stage / "backup.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
            for name in ["manifest.json", *manifest["files"]]:
                output.write(stage / name, name)
        # Exclusive creation protects existing backups even if another process creates one now.
        with destination.open("xb") as output, archive.open("rb") as source:
            shutil.copyfileobj(source, output)
    return {
        "backup": str(destination),
        "files": len(manifest["files"]),
        "sha256": checksum(destination),
    }


def restore_backup(archive: Path, destination: Path):
    root = destination.resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("恢复目录必须为空；请停止服务并将原数据目录重命名保留")
    root.parent.mkdir(parents=True, exist_ok=True)
    with (
        zipfile.ZipFile(archive) as backup,
        tempfile.TemporaryDirectory(dir=root.parent) as temporary,
    ):
        names = backup.namelist()
        if len(names) != len(set(names)) or "manifest.json" not in names:
            raise ValueError("备份清单缺失或文件名重复")
        manifest = json.loads(backup.read("manifest.json"))
        if manifest.get("format") != 1 or Path(manifest.get("data_dir", "")).resolve() != root:
            raise ValueError("此版本仅支持恢复到原绝对数据路径，避免文档与产物链接失效")
        if set(names) != {"manifest.json", *manifest["files"]}:
            raise ValueError("备份文件与清单不一致")
        stage = Path(temporary)
        for name, expected in manifest["files"].items():
            parts = PurePosixPath(name)
            if "\\" in name or ":" in name or parts.is_absolute() or ".." in parts.parts:
                raise ValueError("备份包含不安全路径")
            if name not in DATABASES and (not parts.parts or parts.parts[0] not in DIRECTORIES):
                raise ValueError("备份包含未知数据文件")
            path = stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with backup.open(name) as source, path.open("xb") as output:
                shutil.copyfileobj(source, output)
            if checksum(path) != expected:
                raise ValueError("备份校验失败，原数据未改变")
        if not (stage / "research.sqlite3").is_file():
            raise ValueError("备份缺少主数据库")
        for name in DATABASES:
            if (stage / name).exists():
                with closing(sqlite3.connect(stage / name)) as db:
                    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise ValueError("恢复数据库完整性检查失败")
        if root.exists():
            root.rmdir()
        stage.rename(root)
        # TemporaryDirectory tolerates the stage having been moved.
    return {"restored": str(root), "files": len(manifest["files"])}
