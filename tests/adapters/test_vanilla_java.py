from collections.abc import Callable
from pathlib import Path

import pytest

from mscts.adapters.base import Installation, PrepareError
from mscts.adapters.vanilla import VanillaAdapter
from mscts.spec import ServerSpec
from mscts.target import TARGET

type MakeJava = Callable[[str], Path]


def launched_java(tmp_path: Path, adapter: VanillaAdapter | None = None) -> str:
    installation = Installation(adapter="vanilla", target=TARGET, root=tmp_path / "cache")
    plan = (adapter or VanillaAdapter()).prepare(
        installation, ServerSpec(port=25599), tmp_path / "w"
    )
    return plan.argv[0]


@pytest.fixture(autouse=True)
def no_java_configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MSCTS_JAVA", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))


def test_constructor_argument_comes_first(
    make_java: MakeJava, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    explicit = make_java("explicit")
    monkeypatch.setenv("MSCTS_JAVA", str(make_java("from-env")))
    monkeypatch.setenv("PATH", str(make_java("on-path").parent))
    assert launched_java(tmp_path, VanillaAdapter(java=explicit)) == str(explicit)


def test_mscts_java_comes_before_path(
    make_java: MakeJava, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from_env = make_java("from-env")
    monkeypatch.setenv("MSCTS_JAVA", str(from_env))
    monkeypatch.setenv("PATH", str(make_java("on-path").parent))
    assert launched_java(tmp_path) == str(from_env)


def test_path_is_the_last_resort(
    make_java: MakeJava, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    on_path = make_java("on-path")
    monkeypatch.setenv("PATH", f"{tmp_path / 'nothing-here'}:{on_path.parent}")
    assert launched_java(tmp_path) == str(on_path)


def test_empty_mscts_java_counts_as_unset(
    make_java: MakeJava, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    on_path = make_java("on-path")
    monkeypatch.setenv("MSCTS_JAVA", "")
    monkeypatch.setenv("PATH", str(on_path.parent))
    assert launched_java(tmp_path) == str(on_path)


def test_java_is_the_real_file_not_a_symlink(make_java: MakeJava, tmp_path: Path) -> None:
    # mise's versionless install dir (temurin-25 -> temurin-25.0.4+101.0.LTS) can move on
    # upgrade, and a symlink on PATH can be repointed: launch the exact runtime.
    real = make_java("temurin-25.0.4")
    (tmp_path / "temurin-25").symlink_to(tmp_path / "temurin-25.0.4")
    assert launched_java(tmp_path, VanillaAdapter(java=tmp_path / "temurin-25/bin/java")) == str(
        real.resolve()
    )


def test_relative_java_is_made_absolute(
    make_java: MakeJava, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    make_java("jdk")
    monkeypatch.chdir(tmp_path)
    java = launched_java(tmp_path, VanillaAdapter(java=Path("jdk/bin/java")))
    assert java == str((tmp_path / "jdk/bin/java").resolve())


def test_no_java_anywhere_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(PrepareError, match="MSCTS_JAVA"):
        launched_java(tmp_path)
