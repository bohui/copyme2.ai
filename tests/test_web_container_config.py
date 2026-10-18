from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_container_up_refreshes_web_image_with_internal_api_origin() -> None:
    compose = (ROOT / "compose.yml").read_text(encoding="utf-8")
    api = compose.split("\n  api:\n", 1)[1].split("\n  codex-worker:\n", 1)[0]

    web = compose.split("\n  web:\n", 1)[1].split("\nvolumes:\n", 1)[0]
    build = web.split("    build:\n", 1)[1].split("    ports:\n", 1)[0]
    assert 'MEMORY_SPARK_API_ORIGIN: "http://api:8000"' in build

    containerfile = (ROOT / "apps/web/Containerfile").read_text(encoding="utf-8")
    assert "ARG MEMORY_SPARK_API_ORIGIN=http://api:8000" in containerfile
    assert "MEMORY_SPARK_API_ORIGIN=${MEMORY_SPARK_API_ORIGIN}" in containerfile

    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    container_up = makefile.split("\ncontainer-up:", 1)[1].split("\ncontainer-health:", 1)[0]
    assert 'python3 scripts/start_container_stack.py' in container_up
    assert '$(filter 1,$(CONTAINER_REBUILD))' in container_up
    assert "_container-up: runtime-start _validate-skills" in container_up
    assert "codex-harness" not in compose
    assert "codex-worker" in compose


def test_frontend_caches_compilation_and_ships_only_standalone_runtime():
    containerfile = (ROOT / 'apps/web/Containerfile').read_text()
    node_majors = [int(major) for major in re.findall(r'FROM node:(\d+)', containerfile)]
    assert node_majors and min(node_majors) >= 22
    runner = containerfile.split(' AS runner', 1)[1]
    assert 'target=/app/.next/cache' in containerfile
    assert 'sharing=locked' in containerfile
    assert '/app/.next/standalone ./' in runner
    assert '/app/.next/static ./.next/static' in runner
    assert 'npm ci' not in runner
    assert 'CMD ["node", "server.js"]' in runner
    assert 'output: "standalone"' in (ROOT / 'apps/web/next.config.mjs').read_text()


def test_local_backend_uses_dependency_images_with_current_source_mounts():
    compose = (ROOT / 'compose.yml').read_text()
    for service in ('api', 'photo-worker', 'codex-worker', 'worker'):
        section = re.split(r'\n  [a-zA-Z]', compose.split('\n  ' + service + ':\n', 1)[1], maxsplit=1)[0]
        assert '      target: runtime' in section
        for source in ('apps/__init__.py', 'apps/api', 'skills', 'README.md'):
            assert './' + source + ':/app/' + source + ':ro' in section
