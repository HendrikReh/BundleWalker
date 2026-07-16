from __future__ import annotations

import hashlib

import pytest

import bundlewalker.conventions as conventions_module
from bundlewalker.conventions import ConventionsStyle, load_conventions
from bundlewalker.errors import WorkspaceError

EXPECTED_DIGESTS = {
    ConventionsStyle.DEFAULT: "8320de0bb0d570a0aaf08425991ab75b4f1a5a94a056c62bb7ddd79f17c59680",
    ConventionsStyle.PERSONAL_WORKBOOK: (
        "53ca429d23a0441f3bbf56ce0dd9217200ca7071941dc1f264f8eea645629991"
    ),
}

PRESET_CONTRACTS = {
    ConventionsStyle.PERSONAL_WORKBOOK: (
        "reflective personal workbook",
        "state sourced facts plainly and neutrally",
        "use first person for personal interpretation",
        "evidence that could change it",
        "do not add personal interpretation or opinion to a source page",
        "never resolve the disagreement",
        "generic ai prose",
    ),
    ConventionsStyle.AGENT_CONTEXT: (
        "authoritative facts",
        "inferred conclusions",
        "proposed actions",
        "scope and applicability",
        "precedence",
        "recovery",
        "source page",
        "topic page",
        "entity page",
        "synthesis page",
    ),
    ConventionsStyle.SOFTWARE_AGENT: (
        "exact working directory",
        "architecture boundaries",
        "dependency direction",
        "generated files",
        "security",
        "definition of done",
        "current repository behavior",
        "write clean code",
    ),
    ConventionsStyle.RESEARCH_AGENT: (
        "observation",
        "reported result",
        "hypothesis",
        "speculation",
        "sample",
        "timeframe",
        "source count",
        "absence of evidence",
        "falsify",
    ),
}


def test_conventions_style_has_the_exact_public_values() -> None:
    assert tuple(style.value for style in ConventionsStyle) == (
        "default",
        "personal-workbook",
        "agent-context",
        "software-agent",
        "research-agent",
    )


@pytest.mark.parametrize("style", list(ConventionsStyle))
def test_each_conventions_resource_is_valid_text(style: ConventionsStyle) -> None:
    text = load_conventions(style)

    assert text.strip()
    assert text.endswith("\n")
    assert not text.endswith("\n\n")
    assert "placeholder" not in text.casefold()


@pytest.mark.parametrize(("style", "digest"), EXPECTED_DIGESTS.items())
def test_canonical_conventions_resources_are_byte_exact(
    style: ConventionsStyle,
    digest: str,
) -> None:
    content = load_conventions(style).encode("utf-8")

    assert hashlib.sha256(content).hexdigest() == digest
    if style is ConventionsStyle.DEFAULT:
        assert len(content.decode("utf-8").splitlines()) == 18
    else:
        assert len(content.decode("utf-8").splitlines()) == 64


@pytest.mark.parametrize(("style", "required_phrases"), PRESET_CONTRACTS.items())
def test_each_specialized_preset_has_its_required_contract(
    style: ConventionsStyle,
    required_phrases: tuple[str, ...],
) -> None:
    text = load_conventions(style).casefold()

    missing = [phrase for phrase in required_phrases if phrase not in text]
    assert not missing, f"{style.value} missing: {missing}"


@pytest.mark.parametrize(
    "failure",
    [
        ModuleNotFoundError("private package path"),
        FileNotFoundError("private resource path"),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid byte"),
    ],
)
def test_conventions_loader_sanitizes_resource_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    def fail_resources(_package: object) -> object:
        raise failure

    monkeypatch.setattr(conventions_module.resources, "files", fail_resources)

    with pytest.raises(WorkspaceError) as caught:
        load_conventions(ConventionsStyle.RESEARCH_AGENT)

    assert str(caught.value) == "could not load conventions style: research-agent"
    assert "private" not in str(caught.value)
