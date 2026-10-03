"""mscts words the two refusals an Adapter reports: UnsupportedError and UnavailableError."""

from mscts.adapters.base import Build, ProvisionError, UnavailableError, UnsupportedError
from mscts.target import TARGET


def test_unsupported_names_what_was_asked_for_and_the_minecraft_version_tested() -> None:
    refusal = UnsupportedError("vanilla@26.4", target=TARGET)
    assert isinstance(refusal, ProvisionError)
    assert str(refusal) == "vanilla@26.4 is not supported: this mscts tests Minecraft 26.3."


def test_unsupported_says_what_a_file_is_when_it_is_known() -> None:
    refusal = UnsupportedError("./server.jar", target=TARGET, actual="vanilla 26.4")
    assert str(refusal) == (
        "./server.jar is not supported: it is vanilla 26.4, and this mscts tests Minecraft 26.3."
    )


def test_unavailable_names_the_latest_build_and_how_to_install_another() -> None:
    latest = Build(version="nightly", commit="4426d1113a211e6018a2db416e33b6b8a7802614")
    refusal = UnavailableError("pumpkin", "8f3c2a1", latest=latest)
    assert isinstance(refusal, ProvisionError)
    assert str(refusal) == (
        "pumpkin@8f3c2a1 is not available for download. The latest is pumpkin nightly 4426d11.\n"
        "Build it yourself and install it with:\n"
        "  mscts adapter install pumpkin --from <file>"
    )
