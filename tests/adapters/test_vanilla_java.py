from collections.abc import Callable
from pathlib import Path

import pytest

from mscts.adapters.base import Installation, PrepareError
from mscts.adapters.vanilla import VanillaAdapter, resolve_java
from mscts.spec import ServerSpec
from mscts.target import TARGET

type MakeJava = Callable[..., Path]


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


@pytest.mark.parametrize("version", ["25", "25.0.4.1", "25-ea"])
def test_a_java_of_the_targets_major_version_is_accepted(
    make_java: MakeJava, tmp_path: Path, version: str
) -> None:
    java = make_java("jdk", version)
    assert launched_java(tmp_path, VanillaAdapter(java=java)) == str(java)


@pytest.mark.parametrize("version", ["21.0.8", "26", "1.8.0_392", "250"])
def test_a_java_of_another_major_version_is_refused(
    make_java: MakeJava, tmp_path: Path, version: str
) -> None:
    adapter = VanillaAdapter(java=make_java("jdk", version))
    with pytest.raises(PrepareError, match=rf"is Java {version}, but .* needs Java 25"):
        launched_java(tmp_path, adapter)


def test_a_launcher_outside_a_java_runtime_image_is_refused(tmp_path: Path) -> None:
    # A version-manager shim picks its JVM at run time (e.g. by cwd); it cannot be vouched for.
    shim = tmp_path / "shims/java"
    shim.parent.mkdir()
    shim.write_bytes(b"#!/bin/sh\n")
    with pytest.raises(PrepareError, match="not the launcher of a Java runtime"):
        launched_java(tmp_path, VanillaAdapter(java=shim))


def test_a_release_file_without_java_version_is_refused(
    make_java: MakeJava, tmp_path: Path
) -> None:
    java = make_java("jdk")
    (tmp_path / "jdk/release").write_text('IMPLEMENTOR="mscts"\n', encoding="utf-8")
    with pytest.raises(PrepareError, match="JAVA_VERSION"):
        launched_java(tmp_path, VanillaAdapter(java=java))


def test_a_missing_launcher_is_refused(make_java: MakeJava, tmp_path: Path) -> None:
    make_java("jdk")
    with pytest.raises(PrepareError, match="does not exist"):
        launched_java(tmp_path, VanillaAdapter(java=tmp_path / "jdk/bin/javaa"))


def test_a_refused_java_writes_nothing(make_java: MakeJava, tmp_path: Path) -> None:
    with pytest.raises(PrepareError):
        launched_java(tmp_path, VanillaAdapter(java=make_java("jdk", "21")))
    assert not (tmp_path / "w").exists()


def test_resolve_java_is_the_public_seam_prepare_uses(
    make_java: MakeJava, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Other callers (the codec regen module) need the exact same resolution prepare uses,
    # without an Installation or a workdir. `resolve_java` is that seam.
    on_path = make_java("on-path")
    monkeypatch.setenv("PATH", str(on_path.parent))
    assert resolve_java(TARGET) == on_path.resolve()


def test_resolve_java_takes_an_explicit_launcher_over_the_environment(
    make_java: MakeJava, monkeypatch: pytest.MonkeyPatch
) -> None:
    explicit = make_java("explicit")
    monkeypatch.setenv("MSCTS_JAVA", str(make_java("from-env")))
    assert resolve_java(TARGET, explicit) == explicit


def test_resolve_java_rejects_the_wrong_major_version(make_java: MakeJava) -> None:
    java = make_java("jdk", "21.0.8")
    with pytest.raises(PrepareError, match=r"is Java 21\.0\.8, but .* needs Java 25"):
        resolve_java(TARGET, java)
