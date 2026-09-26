from pathlib import Path

import pytest

from mscts.cache import cache_dir


@pytest.fixture(autouse=True)
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.delenv("MSCTS_CACHE", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def test_mscts_cache_comes_first(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MSCTS_CACHE", str(tmp_path / "shared"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert cache_dir() == tmp_path / "shared"


def test_then_the_xdg_cache_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert cache_dir() == tmp_path / "xdg/mscts"


def test_then_the_home_cache(home: Path) -> None:
    assert cache_dir() == home / ".cache/mscts"


def test_empty_variables_count_as_unset(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    monkeypatch.setenv("MSCTS_CACHE", "")
    monkeypatch.setenv("XDG_CACHE_HOME", "")
    assert cache_dir() == home / ".cache/mscts"


def test_a_relative_xdg_cache_home_is_ignored(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    # The XDG Base Directory spec: a relative path in these variables is invalid.
    monkeypatch.setenv("XDG_CACHE_HOME", "relative/cache")
    assert cache_dir() == home / ".cache/mscts"


def test_a_relative_mscts_cache_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # Resolved against each worktree's cwd, it would silently split the one shared cache.
    monkeypatch.setenv("MSCTS_CACHE", "relative/cache")
    with pytest.raises(ValueError, match="MSCTS_CACHE"):
        cache_dir()
