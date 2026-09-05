"""scripts/test_sync_codex_mirror.py — 미러 생성의 원자성

미러는 생성물이지만, 생성이 **중간에 실패했을 때 무엇이 남는가** 가 중요하다.
예전 구현은 `rmtree(dst)` 로 먼저 지우고 그 자리에서 다시 채웠기 때문에, 삭제나
복사가 중간에 실패하면 미러가 반쯤 지워진 채 남았다. Windows 에서 OneDrive·백신이
파일 핸들을 잠깐 붙들면 실제로 일어나는 일이다(WinError 5/32).

반쯤 지워진 미러는 그 다음 `--check` 에서 그냥 'STALE' 로 보고된다 — 원인이 파일
잠금이었다는 사실이 드러나지 않고, 사람은 스킬 문서를 안 고쳤는데 왜 stale 이냐고
헤매게 된다. 그래서 "실패하면 이전 미러가 그대로 남는다" 를 계약으로 고정한다.
"""
from __future__ import annotations

import pytest

import sync_codex_mirror as mirror


@pytest.fixture
def fake_source(tmp_path, monkeypatch):
    src = tmp_path / "skills"
    (src / "web-crawler").mkdir(parents=True)
    (src / "web-crawler" / "SKILL.md").write_text(
        "본문에서 .claude/skills 를 가리킨다\n", encoding="utf-8")
    monkeypatch.setattr(mirror, "SRC", src)
    return src


def test_build_creates_mirror(fake_source, tmp_path):
    dst = tmp_path / "codex-skills"
    mirror.build_mirror(dst)
    assert (dst / "_GENERATED.md").exists()
    assert (dst / "web-crawler" / "SKILL.md").exists()


def test_token_is_rewritten(fake_source, tmp_path):
    dst = tmp_path / "codex-skills"
    mirror.build_mirror(dst)
    body = (dst / "web-crawler" / "SKILL.md").read_text(encoding="utf-8")
    assert ".codex/skills" in body
    assert ".claude/skills" not in body


def test_rebuild_is_idempotent(fake_source, tmp_path):
    dst = tmp_path / "codex-skills"
    mirror.build_mirror(dst)
    first = (dst / "web-crawler" / "SKILL.md").read_bytes()
    mirror.build_mirror(dst)
    assert (dst / "web-crawler" / "SKILL.md").read_bytes() == first


def test_stale_files_are_removed_on_rebuild(fake_source, tmp_path):
    """SSOT 에서 사라진 파일은 미러에서도 사라져야 한다."""
    dst = tmp_path / "codex-skills"
    mirror.build_mirror(dst)
    orphan = dst / "web-crawler" / "삭제된문서.md"
    orphan.write_text("옛날 것", encoding="utf-8")
    mirror.build_mirror(dst)
    assert not orphan.exists()


def test_failed_build_leaves_previous_mirror_intact(fake_source, tmp_path, monkeypatch):
    """생성 도중 실패해도 기존 미러는 온전해야 한다 — 반쯤 지워진 상태를 만들지 않는다."""
    dst = tmp_path / "codex-skills"
    mirror.build_mirror(dst)
    before = (dst / "web-crawler" / "SKILL.md").read_bytes()

    def boom(_dst):
        raise OSError("디스크가 가득 찼다고 치자")

    monkeypatch.setattr(mirror, "_populate", boom)
    with pytest.raises(OSError):
        mirror.build_mirror(dst)

    assert (dst / "web-crawler" / "SKILL.md").read_bytes() == before
    assert (dst / "_GENERATED.md").exists()
    assert not (dst.parent / (dst.name + ".new")).exists()   # 작업 디렉터리는 치운다


def test_rmtree_retries_transient_lock(tmp_path, monkeypatch):
    """Windows 의 일시적 잠금은 재시도로 넘어간다 — 첫 실패로 포기하지 않는다."""
    target = tmp_path / "locked"
    target.mkdir()
    calls = {"n": 0}
    real_rmtree = mirror.shutil.rmtree

    def flaky(path, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(5, "액세스가 거부되었습니다")
        return real_rmtree(path, **kw)

    monkeypatch.setattr(mirror.shutil, "rmtree", flaky)
    monkeypatch.setattr(mirror.time, "sleep", lambda _s: None)
    mirror._rmtree_resilient(target)
    assert calls["n"] == 3
    assert not target.exists()


def test_rmtree_gives_up_after_attempts(tmp_path, monkeypatch):
    """무한정 재시도하지는 않는다 — 진짜 실패는 실패로 올린다."""
    target = tmp_path / "locked"
    target.mkdir()

    def always_fail(path, **kw):
        raise PermissionError(5, "액세스가 거부되었습니다")

    monkeypatch.setattr(mirror.shutil, "rmtree", always_fail)
    monkeypatch.setattr(mirror.time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        mirror._rmtree_resilient(target, attempts=3)
