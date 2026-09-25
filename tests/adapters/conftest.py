from collections.abc import Callable
from pathlib import Path

import pytest

type MakeJava = Callable[[str], Path]


@pytest.fixture
def make_java(tmp_path: Path) -> MakeJava:
    """Make a fake Java runtime image under tmp_path and return its `bin/java` (never run)."""

    def make(name: str) -> Path:
        java = tmp_path / name / "bin" / "java"
        java.parent.mkdir(parents=True)
        java.write_bytes(b"")
        java.chmod(0o755)
        return java

    return make


@pytest.fixture
def java_25(make_java: MakeJava, monkeypatch: pytest.MonkeyPatch) -> Path:
    """MSCTS_JAVA names a fake Java 25, so prepare never looks at the host's Java (unit tier)."""
    java = make_java("jdk-25")
    monkeypatch.setenv("MSCTS_JAVA", str(java))
    return java
