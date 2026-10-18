import json
import zipfile

import pytest

from research_agent.backup import create_backup, restore_backup


def test_backup_restore_roundtrip_and_no_secrets(engine, tmp_path):
    root = engine.settings.data_dir
    engine.store.put("project", {"id": "p", "name": "test"})
    (root / "library").mkdir()
    (root / "library/paper.pdf").write_bytes(b"%PDF-test")
    (root / "secrets").mkdir()
    (root / "secrets/token").write_text("private")
    archive = tmp_path.parent / (tmp_path.name + ".zip")
    result = create_backup(root, archive)
    assert result["files"] == 2
    with zipfile.ZipFile(archive) as backup:
        assert not any("secrets" in name or "access.sqlite3" in name for name in backup.namelist())
    with pytest.raises(ValueError, match="为空"):
        restore_backup(archive, root)
    original = root.with_name(root.name + "-original")
    root.rename(original)
    restore_backup(archive, root)
    from research_agent.storage import Store

    assert Store(root).get("p")["name"] == "test"
    assert (root / "library/paper.pdf").read_bytes() == b"%PDF-test"


def test_backup_corruption_and_unsafe_paths(engine, tmp_path):
    root = engine.settings.data_dir
    archive = tmp_path.parent / (tmp_path.name + "-bad.zip")
    empty = tmp_path.parent / (tmp_path.name + "-restore")
    manifest = {"format": 1, "data_dir": str(empty), "files": {"../escape": "x"}}
    with zipfile.ZipFile(archive, "w") as backup:
        backup.writestr("manifest.json", json.dumps(manifest))
        backup.writestr("../escape", "bad")
    with pytest.raises(ValueError, match="不安全"):
        restore_backup(archive, empty)
    assert not empty.exists()
    manifest["files"] = {"research.sqlite3": "incorrect"}
    with zipfile.ZipFile(archive, "w") as backup:
        backup.writestr("manifest.json", json.dumps(manifest))
        backup.writestr("research.sqlite3", "corrupted")
    with pytest.raises(ValueError, match="校验失败"):
        restore_backup(archive, empty)
    assert not empty.exists()
    with pytest.raises(ValueError, match="之外"):
        create_backup(root, root / "backup.zip")
