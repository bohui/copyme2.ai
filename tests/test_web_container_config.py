from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_container_up_refreshes_web_image_with_internal_api_origin() -> None:
    compose = (ROOT / "compose.yml").read_text(encoding="utf-8")
    api = compose.split("\n  api:\n", 1)[1].split("\n  codex-worker:\n", 1)[0]
    assert "./Mira_Memoir_Journalist_System_Prompt_v1.0.md:/app/Mira_Memoir_Journalist_System_Prompt_v1.0.md:ro" in api

    web = compose.split("\n  web:\n", 1)[1].split("\nvolumes:\n", 1)[0]
    build = web.split("    build:\n", 1)[1].split("    ports:\n", 1)[0]
    assert 'MEMORY_SPARK_API_ORIGIN: "http://api:8000"' in build

    containerfile = (ROOT / "apps/web/Containerfile").read_text(encoding="utf-8")
    assert "ARG MEMORY_SPARK_API_ORIGIN=http://api:8000" in containerfile
    assert "MEMORY_SPARK_API_ORIGIN=${MEMORY_SPARK_API_ORIGIN}" in containerfile

    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    container_up = makefile.split("\ncontainer-up:", 1)[1].split("\ncontainer-health:", 1)[0]
    assert "$(MOCKER) compose build -f $(COMPOSE_FILE) web" in container_up
    assert "codex-harness" not in compose
    assert "codex-worker" in compose
