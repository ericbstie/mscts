from pathlib import Path

import pytest
from support.pumpkin import COMMIT, fake_pumpkin

from mscts.adapters.base import Build, ProvisionError
from mscts.adapters.pumpkin import PumpkinAdapter
from mscts.target import TARGET


def check(tmp_path: Path, body: bytes) -> Build:
    (tmp_path / "pumpkin").write_bytes(body)
    return PumpkinAdapter().check(tmp_path / "pumpkin", TARGET)


def test_check_reads_the_version_and_the_commit_a_build_names(tmp_path: Path) -> None:
    assert check(tmp_path, fake_pumpkin()) == Build(version="0.2.0+26.3-26.51", commit=COMMIT)


def test_a_build_made_without_git_has_no_commit(tmp_path: Path) -> None:
    built = check(tmp_path, fake_pumpkin(commit="unknown"))
    assert built == Build(version="0.2.0+26.3-26.51", commit=None)


def test_check_refuses_a_build_for_another_minecraft_version(tmp_path: Path) -> None:
    said = (
        f"{tmp_path / 'pumpkin'} is not supported: it is Pumpkin 0.2.0+26.4-26.60, "
        "for Minecraft 26.4, and this mscts tests Minecraft 26.3."
    )
    with pytest.raises(ProvisionError) as raised:
        check(tmp_path, fake_pumpkin(version="0.2.0+26.4-26.60"))
    assert str(raised.value) == said


def test_check_refuses_an_executable_that_names_no_pumpkin_version(tmp_path: Path) -> None:
    with pytest.raises(ProvisionError, match="names no Pumpkin version"):
        check(tmp_path, b"\x7fELF\x02\x01\x01\x00 some other server")


def test_check_refuses_a_file_that_is_not_an_executable(tmp_path: Path) -> None:
    with pytest.raises(ProvisionError, match="not an ELF executable"):
        check(tmp_path, b"<!DOCTYPE html> 0.2.0+26.3-26.51 (Commit: 4426d11/")
