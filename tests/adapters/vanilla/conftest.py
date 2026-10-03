from collections.abc import Callable
from pathlib import Path

import pytest

type MakeJava = Callable[..., Path]


@pytest.fixture
def make_java(tmp_path: Path) -> MakeJava:
    """Make a fake Java runtime image under tmp_path; return its `bin/java` (never run).

    Like every Java 9+ runtime image, it has a `release` file naming its JAVA_VERSION.
    """

    def make(name: str, version: str = "25.0.4.1") -> Path:
        java = tmp_path / name / "bin" / "java"
        java.parent.mkdir(parents=True)
        java.write_bytes(b"")
        java.chmod(0o755)
        release = f'IMPLEMENTOR="mscts"\nJAVA_VERSION="{version}"\nOS_NAME="Linux"\n'
        (tmp_path / name / "release").write_text(release, encoding="utf-8")
        return java

    return make


@pytest.fixture
def java_25(make_java: MakeJava, monkeypatch: pytest.MonkeyPatch) -> Path:
    """MSCTS_JAVA names a fake Java 25, so prepare never looks at the host's Java (unit tier)."""
    java = make_java("jdk-25")
    monkeypatch.setenv("MSCTS_JAVA", str(java))
    return java
