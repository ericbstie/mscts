from importlib import resources
from pathlib import Path

import pytest

from mscts.codec import regen
from mscts.codec.regen import compare_or_write, data_generator_argv, packets_json_path
from mscts.target import TARGET


def test_packets_json_path_is_the_committed_package_data() -> None:
    resource = resources.files("mscts.codec").joinpath(
        "data", TARGET.minecraft_version, "packets.json"
    )
    assert packets_json_path(TARGET) == Path(str(resource))


def test_data_generator_argv_matches_the_documented_command(tmp_path: Path) -> None:
    # protocol-research skill: java -DbundlerMainClass=net.minecraft.data.Main -jar <jar>
    # --reports --output <dir>
    java, jar, output = tmp_path / "java", tmp_path / "server.jar", tmp_path / "out"
    assert data_generator_argv(java, jar, output) == [
        str(java),
        "-DbundlerMainClass=net.minecraft.data.Main",
        "-jar",
        str(jar),
        "--reports",
        "--output",
        str(output),
    ]


def test_compare_or_write_matches_identical_bytes(tmp_path: Path) -> None:
    committed = tmp_path / "packets.json"
    committed.write_bytes(b"same")
    assert compare_or_write(b"same", committed, write=False) is None


def test_compare_or_write_reports_a_byte_difference(tmp_path: Path) -> None:
    committed = tmp_path / "packets.json"
    committed.write_bytes(b"old bytes")
    message = compare_or_write(b"new bytes", committed, write=False)
    assert message is not None
    assert str(committed) in message


def test_compare_or_write_reports_a_missing_committed_file(tmp_path: Path) -> None:
    committed = tmp_path / "missing" / "packets.json"
    message = compare_or_write(b"generated", committed, write=False)
    assert message is not None
    assert "--write" in message


def test_compare_or_write_writes_a_new_file_when_asked(tmp_path: Path) -> None:
    committed = tmp_path / "nested" / "packets.json"
    assert compare_or_write(b"generated", committed, write=True) is None
    assert committed.read_bytes() == b"generated"


def test_compare_or_write_overwrites_a_differing_file_when_asked(tmp_path: Path) -> None:
    committed = tmp_path / "packets.json"
    committed.write_bytes(b"old")
    assert compare_or_write(b"new", committed, write=True) is None
    assert committed.read_bytes() == b"new"


def test_main_reports_success_when_up_to_date(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    committed = tmp_path / "packets.json"
    committed.write_bytes(b"same")
    monkeypatch.setattr(regen, "packets_json_path", lambda _target: committed)
    monkeypatch.setattr(regen, "regenerate", lambda _target, _cache: b"same")
    assert regen.main([]) == 0
    assert str(committed) in capsys.readouterr().out


def test_main_returns_nonzero_on_a_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    committed = tmp_path / "packets.json"
    committed.write_bytes(b"old")
    monkeypatch.setattr(regen, "packets_json_path", lambda _target: committed)
    monkeypatch.setattr(regen, "regenerate", lambda _target, _cache: b"new")
    assert regen.main([]) == 1
    assert str(committed) in capsys.readouterr().err


def test_main_write_updates_the_committed_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    committed = tmp_path / "packets.json"
    committed.write_bytes(b"old")
    monkeypatch.setattr(regen, "packets_json_path", lambda _target: committed)
    monkeypatch.setattr(regen, "regenerate", lambda _target, _cache: b"fresh")
    assert regen.main(["--write"]) == 0
    assert committed.read_bytes() == b"fresh"


def test_main_returns_nonzero_when_regeneration_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    message = "the data generator exploded"

    def boom(_target: object, _cache: object) -> bytes:
        raise regen.RegenError(message)

    monkeypatch.setattr(regen, "regenerate", boom)
    assert regen.main([]) == 1
    assert message in capsys.readouterr().err


def test_main_without_an_installed_jar_fails_at_once_naming_the_install_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MSCTS_CACHE", str(tmp_path))
    assert regen.main([]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: vanilla 26.3 is not installed")
    assert "`mscts adapter install vanilla`" in err
    assert list(tmp_path.iterdir()) == []  # nothing downloaded


def test_run_data_generator_raises_when_the_report_is_missing(tmp_path: Path) -> None:
    # A java that exits 0 without writing reports/packets.json (e.g. a stub in a test) is
    # still an error: regen must not silently compare against an empty or stale file.
    java = tmp_path / "java"
    java.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    java.chmod(0o755)
    with pytest.raises(regen.RegenError, match=r"packets\.json"):
        regen.run_data_generator(java, tmp_path / "server.jar", tmp_path / "out")


def test_run_data_generator_runs_in_the_output_directory(tmp_path: Path) -> None:
    # Audit MD7 survivor G3: the bundler unpacks libraries/ and versions/ into its cwd,
    # so the generator must run in the (scratch) output dir, never the caller's cwd.
    java = tmp_path / "java"
    java.write_text(
        '#!/bin/sh\nmkdir -p reports\npwd > cwd.txt\necho "{}" > reports/packets.json\n',
        encoding="utf-8",
    )
    java.chmod(0o755)
    output = tmp_path / "out"
    report = regen.run_data_generator(java, tmp_path / "server.jar", output)
    assert report == output / "reports" / "packets.json"
    assert (output / "cwd.txt").read_text(encoding="utf-8").strip() == str(output)


def test_run_data_generator_raises_on_a_nonzero_exit(tmp_path: Path) -> None:
    java = tmp_path / "java"
    java.write_text("#!/bin/sh\necho boom >&2\nexit 1\n", encoding="utf-8")
    java.chmod(0o755)
    with pytest.raises(regen.RegenError, match="boom"):
        regen.run_data_generator(java, tmp_path / "server.jar", tmp_path / "out")
