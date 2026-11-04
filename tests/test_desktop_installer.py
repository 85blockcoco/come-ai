"""Installer checks use temporary bundles and never execute an app launcher."""
from __future__ import annotations

import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

from desktop import build_app as installer


@pytest.fixture
def install_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    def forbidden(*args, **kwargs):
        raise AssertionError("Installer must not launch a process or remove a directory")

    monkeypatch.setattr(installer.subprocess, "run", forbidden)
    monkeypatch.setattr(installer.shutil, "rmtree", forbidden)
    icon = tmp_path / "source.icns"
    png = tmp_path / "source.png"
    icon.write_bytes(b"first-icon")
    png.write_bytes(b"first-png")
    return {
        "app_path": tmp_path / "Desktop" / "NAGe.app",
        "repo": tmp_path / "repo with spaces",
        "backup_root": tmp_path / "backups",
        "icon": icon,
        "icon_png": png,
        "refresh": False,
    }


def test_rebuild_keeps_unknown_files_and_backs_up_before_overwrite(install_paths: dict):
    paths = install_paths
    app = paths["app_path"]
    legacy = app.parent / "Côme IA.app" / "Contents" / "keep.txt"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy data")
    assert installer.build_app(**paths) is None
    launcher = app / "Contents" / "MacOS" / "NAGe"
    launcher.write_text("old launcher")
    unknown = app / "Contents" / "Resources" / "my-note.txt"
    unknown.write_text("user-owned file")
    info_path = app / "Contents" / "Info.plist"
    original_info = plistlib.loads(info_path.read_bytes())
    original_info["UserField"] = "keep"
    original_info["CFBundleIdentifier"] = "old.bundle"
    info_path.write_bytes(plistlib.dumps(original_info))
    paths["icon"].write_bytes(b"second-icon")
    first_backup = installer.build_app(**paths)
    assert first_backup.is_dir()
    assert (first_backup / "Contents" / "MacOS" / "NAGe").read_text() == "old launcher"
    assert (first_backup / "Contents" / "Resources" / "NAGe.icns").read_bytes() == b"first-icon"
    assert plistlib.loads((first_backup / "Contents" / "Info.plist").read_bytes()) == original_info
    assert (first_backup / "Contents" / "Resources" / "my-note.txt").read_text() == "user-owned file"
    assert unknown.read_text() == "user-owned file"
    assert legacy.read_text() == "legacy data"
    assert (app / "Contents" / "Resources" / "NAGe.icns").read_bytes() == b"second-icon"
    current_info = plistlib.loads(info_path.read_bytes())
    assert current_info["UserField"] == "keep"
    assert current_info["CFBundleIdentifier"] == "ai.come.nage.desktop"
    assert current_info["CFBundleExecutable"] == "NAGe"
    assert launcher.stat().st_mode & 0o111 == 0o111
    assert installer.APP_URL in launcher.read_text()
    second_backup = installer.build_app(**paths)
    assert second_backup != first_backup
    assert first_backup.exists()
    assert unknown.read_text() == "user-owned file"
    assert legacy.read_text() == "legacy data"


def test_failed_backup_leaves_existing_bundle_unchanged(install_paths: dict, monkeypatch: pytest.MonkeyPatch):
    paths = install_paths
    installer.build_app(**paths)
    app = paths["app_path"]
    before = {p.relative_to(app): p.read_bytes() for p in app.rglob("*") if p.is_file()}

    def fail_backup(*args, **kwargs):
        raise OSError("backup disk unavailable")

    monkeypatch.setattr(installer.shutil, "copytree", fail_backup)
    paths["icon"].write_bytes(b"new icon")
    with pytest.raises(OSError, match="backup disk unavailable"):
        installer.build_app(**paths)
    after = {p.relative_to(app): p.read_bytes() for p in app.rglob("*") if p.is_file()}
    assert after == before


def test_managed_symlink_cannot_overwrite_external_file(install_paths: dict):
    paths = install_paths
    launcher = paths["app_path"] / "Contents" / "MacOS" / "NAGe"
    launcher.parent.mkdir(parents=True)
    outside = paths["app_path"].parent / "outside.txt"
    outside.write_text("must remain intact")
    launcher.symlink_to(outside)
    with pytest.raises(ValueError, match="lien symbolique"):
        installer.build_app(**paths)
    assert outside.read_text() == "must remain intact"
    assert launcher.is_symlink()


def test_backup_must_be_outside_bundle(install_paths: dict):
    paths = install_paths | {"backup_root": install_paths["app_path"] / "backups"}
    with pytest.raises(ValueError, match="extérieur"):
        installer.build_app(**paths)
    assert not paths["app_path"].exists()


def test_launcher_has_canonical_url_profile_logs_and_valid_zsh_syntax(tmp_path: Path):
    shell = shutil.which("zsh")
    if shell is None:
        pytest.skip("zsh is required to validate the macOS launcher syntax")
    repo = tmp_path / "repo's $HOME `literal`"
    launcher = tmp_path / "launcher.zsh"
    script = installer.render_launcher(repo)
    launcher.write_text(script)
    subprocess.run([shell, "-n", str(launcher)], check=True, capture_output=True, text=True)
    assert installer.APP_URL == "http://127.0.0.1:8765/v5#v5/assistantView"
    assert f'APP_URL="{installer.APP_URL}"' in script
    assert 'cd "$REPO"' in script
    assert '"$REPO/.venv/bin/python" "$REPO/run_come_ai_v3.py" --port 8765 --no-browser' in script
    assert 'PROFILE="$HOME/Library/Application Support/NAGE/window"' in script
    assert 'LOG_DIR="$HOME/Library/Logs/NAGe"' in script
    assert '"$LOG_DIR/server.log"' in script
    assert '--app="$APP_URL"' in script
