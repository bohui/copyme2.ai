from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_app_auto_localization_allows_implicit_memoir_invocation():
    metadata = (ROOT / "skills/app-auto-localization/agents/openai.yaml").read_text()

    assert "allow_implicit_invocation: true" in metadata


def test_app_auto_localization_documents_the_memoir_installer():
    readme = (ROOT / "skills/app-auto-localization/README.md").read_text()

    assert "make install_skill" in readme
    assert ".agents/skills" not in readme
