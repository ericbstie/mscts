import json
from importlib import resources
from pathlib import Path

import pytest

from mscts.codec import regen
from mscts.codec.regen import (
    compare_or_write,
    data_generator_argv,
    fresh_data,
    packets_json_path,
    registry_names_json,
    registry_names_path,
)
from mscts.target import TARGET

# Names in protocol id order that are neither alphabetical nor reverse-alphabetical, so a
# sort by name (or by the report's key order, see _report) cannot pass for a sort by id.
_WANTED = {
    "minecraft:command_argument_type": ["minecraft:m", "minecraft:z", "minecraft:a"],
    "minecraft:consume_effect_type": ["minecraft:b", "minecraft:a"],
    "minecraft:data_component_type": ["minecraft:z", "minecraft:m", "minecraft:a"],
}


def _report(registries: dict[str, list[str]]) -> bytes:
    """A registries.json as the data generator writes it, with its entries out of id order."""
    report = {
        registry: {
            "entries": {
                name: {"protocol_id": protocol_id}
                for protocol_id, name in reversed(list(enumerate(names)))
            },
            "protocol_id": 7,
        }
        for registry, names in registries.items()
    }
    return json.dumps(report).encode()


def test_packets_json_path_is_the_committed_package_data() -> None:
    resource = resources.files("mscts.codec").joinpath(
        "data", TARGET.minecraft_version, "packets.json"
    )
    assert packets_json_path(TARGET) == Path(str(resource))


def test_registry_names_path_is_the_committed_package_data() -> None:
    resource = resources.files("mscts.codec").joinpath(
        "data", TARGET.minecraft_version, "registry_names.json"
    )
    assert registry_names_path(TARGET) == Path(str(resource))


def test_registry_names_json_lists_each_registry_in_protocol_id_order() -> None:
    other = {"minecraft:item": ["minecraft:stone"]}  # a registry the codec does not need
    names = json.loads(registry_names_json(_report({**_WANTED, **other})))
    assert names == _WANTED


def test_registry_names_json_is_two_space_indented_text_ending_in_a_newline() -> None:
    text = registry_names_json(_report(_WANTED)).decode()
    assert text == json.dumps(_WANTED, indent=2) + "\n"


@pytest.mark.parametrize("missing", list(_WANTED))
def test_registry_names_json_rejects_a_registry_missing_from_the_report(missing: str) -> None:
    present = {registry: names for registry, names in _WANTED.items() if registry != missing}
    with pytest.raises(regen.RegenError, match=missing):
        registry_names_json(_report(present))


@pytest.mark.parametrize("protocol_id", [5, 2], ids=["a gap", "a repeated id"])
def test_registry_names_json_rejects_protocol_ids_that_are_not_0_to_n(protocol_id: int) -> None:
    report = json.loads(_report(_WANTED))
    report["minecraft:data_component_type"]["entries"]["minecraft:m"]["protocol_id"] = protocol_id
    with pytest.raises(regen.RegenError, match="minecraft:data_component_type"):
        registry_names_json(json.dumps(report).encode())


@pytest.mark.parametrize("entry", [{}, {"protocol_id": "1"}, [1]], ids=["none", "text", "list"])
def test_registry_names_json_rejects_an_entry_without_an_integer_protocol_id(
    entry: object,
) -> None:
    report = json.loads(_report(_WANTED))
    report["minecraft:data_component_type"]["entries"]["minecraft:m"] = entry
    with pytest.raises(regen.RegenError, match=r"minecraft:data_component_type.*minecraft:m"):
        registry_names_json(json.dumps(report).encode())


def test_fresh_data_is_the_packet_report_and_the_registry_name_lists(tmp_path: Path) -> None:
    (tmp_path / "packets.json").write_bytes(b'{"packets": true}')
    (tmp_path / "registries.json").write_bytes(_report(_WANTED))
    assert fresh_data(TARGET, tmp_path) == {
        packets_json_path(TARGET): b'{"packets": true}',
        registry_names_path(TARGET): registry_names_json(_report(_WANTED)),
    }


def test_fresh_data_raises_when_the_registries_report_is_missing(tmp_path: Path) -> None:
    (tmp_path / "packets.json").write_bytes(b"{}")
    with pytest.raises(regen.RegenError, match=r"registries\.json"):
        fresh_data(TARGET, tmp_path)


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


def _regenerates(monkeypatch: pytest.MonkeyPatch, fresh: dict[Path, bytes]) -> None:
    monkeypatch.setattr(regen, "regenerate", lambda _target, _cache: fresh)


def test_main_reports_success_when_up_to_date(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    committed = tmp_path / "packets.json"
    committed.write_bytes(b"same")
    _regenerates(monkeypatch, {committed: b"same"})
    assert regen.main([]) == 0
    assert str(committed) in capsys.readouterr().out


def test_main_returns_nonzero_on_a_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    committed = tmp_path / "packets.json"
    committed.write_bytes(b"old")
    _regenerates(monkeypatch, {committed: b"new"})
    assert regen.main([]) == 1
    assert str(committed) in capsys.readouterr().err


def test_main_write_updates_the_committed_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    committed = tmp_path / "packets.json"
    committed.write_bytes(b"old")
    _regenerates(monkeypatch, {committed: b"fresh"})
    assert regen.main(["--write"]) == 0
    assert committed.read_bytes() == b"fresh"


def test_main_checks_every_committed_file_and_names_each_one_that_differs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    same, stale, missing = tmp_path / "same.json", tmp_path / "stale.json", tmp_path / "gone.json"
    same.write_bytes(b"same")
    stale.write_bytes(b"old")
    _regenerates(monkeypatch, {same: b"same", stale: b"new", missing: b"new"})
    assert regen.main([]) == 1
    err = capsys.readouterr().err
    assert str(stale) in err
    assert str(missing) in err
    assert str(same) not in err
    assert stale.read_bytes() == b"old"  # a check never writes


def test_main_write_updates_every_committed_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    first.write_bytes(b"old")
    _regenerates(monkeypatch, {first: b"one", second: b"two"})
    assert regen.main(["--write"]) == 0
    assert (first.read_bytes(), second.read_bytes()) == (b"one", b"two")
    out = capsys.readouterr().out
    assert str(first) in out
    assert str(second) in out


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
