"""Tests for grouped bundle export (N100-G05)."""

from __future__ import annotations

from pathlib import Path

import pytest

from career.bundle_export import create_bundle, list_bundle, BundleResult


@pytest.fixture
def tmp_files(tmp_path: Path):
    a = tmp_path / "cv.pdf"
    b = tmp_path / "letter.pdf"
    a.write_text("cv content", encoding="utf-8")
    b.write_text("letter content", encoding="utf-8")
    return a, b, tmp_path


def test_create_bundle(tmp_files) -> None:
    a, b, d = tmp_files
    out = d / "bundle.zip"
    res = create_bundle(out, [a, b])
    assert isinstance(res, BundleResult)
    assert res.ok is True
    assert len(res.files_included) == 2
    assert res.size_bytes > 0
    assert out.exists()


def test_list_bundle(tmp_files) -> None:
    a, b, d = tmp_files
    out = d / "bundle.zip"
    create_bundle(out, [a, b])
    names = list_bundle(out)
    assert "cv.pdf" in names
    assert "letter.pdf" in names


def test_missing_files_skipped(tmp_files) -> None:
    a, b, d = tmp_files
    out = d / "bundle.zip"
    missing = d / "nope.pdf"
    res = create_bundle(out, [a, missing])
    assert res.ok is True
    assert len(res.files_included) == 1


def test_list_missing_bundle(tmp_path) -> None:
    assert list_bundle(tmp_path / "nope.zip") == []


def test_base_dir(tmp_path) -> None:
    base = tmp_path / "files"
    base.mkdir()
    (base / "cv.pdf").write_text("x", encoding="utf-8")
    out = tmp_path / "out.zip"
    res = create_bundle(out, ["cv.pdf"], base_dir=base)
    assert res.ok is True
    assert len(res.files_included) == 1


def test_empty_files(tmp_path) -> None:
    out = tmp_path / "empty.zip"
    res = create_bundle(out, [])
    assert res.ok is True
    assert res.files_included == []