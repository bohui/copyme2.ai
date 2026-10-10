"""Keep the v1 publisher historical; never silently enable new prompt exports."""
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_original_publication_contract_runs_unchanged_on_verified_snapshot(tmp_path):
    from scripts.issue14_subscription_source_contract_v5 import historical_v4_files, historical_test_files
    from scripts.run_isolated_check import offline_environment
    for name, raw in {**historical_v4_files(ROOT), **historical_test_files(ROOT)}.items():
        path = tmp_path / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    report = tmp_path / 'historical-results.xml'
    env = offline_environment(tmp_path)
    env.update(PYTHONPATH=str(tmp_path), PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q',
        str(tmp_path / 'tests/test_issue6_langfuse_publication.py'),
        '--basetemp', str(tmp_path / 'test-output'), '--junitxml', str(report)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    suites = ET.parse(report).getroot().findall('testsuite')
    assert sum(int(suite.attrib['tests']) for suite in suites) == 38
    assert all(int(suite.attrib.get(key, 0)) == 0
               for suite in suites for key in ('failures', 'errors', 'skipped'))


def test_v1_publisher_rejects_current_prompt_source_before_any_network(monkeypatch):
    import socket
    from scripts.issue6_langfuse_publication import build_manifest
    def forbidden(*_args, **_kwargs):
        pytest.fail('A blocked historical publisher must make zero network contacts')
    monkeypatch.setattr(socket, 'socket', forbidden)
    with pytest.raises(ValueError, match='Reviewed application extraction validator or stage vocabulary changed'):
        build_manifest()


def test_v1_export_cannot_relabel_current_source_or_create_output(tmp_path):
    from scripts.run_isolated_check import offline_environment
    destination = tmp_path / 'unapproved-current-export.json'
    env = offline_environment(ROOT)
    env['MEMORY_SPARK_LLM_API_KEY'] = 'synthetic-must-not-be-printed'
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/issue6_langfuse_publication.py'),
        '--export', str(destination)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and not destination.exists()
    assert 'synthetic-must-not-be-printed' not in result.stdout + result.stderr


def test_current_source_gate_is_separate_from_historical_publication_permission():
    from scripts.issue14_subscription_source_contract_v6 import audit_subscription_source_v6
    report = audit_subscription_source_v6(ROOT)
    assert report['source_gate_passed'] is True
    assert report['historical_publication_test_source_verified'] is True
    assert report['live_execution_authorized'] is report['provider_capability_verified'] is False
