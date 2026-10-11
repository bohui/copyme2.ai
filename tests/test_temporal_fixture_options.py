"""Select a preinstalled official Temporal CLI without replacing the server."""
import pytest


def test_local_temporal_accepts_only_existing_absolute_binary(monkeypatch, tmp_path):
    from temporal_test_server import local_options
    binary = tmp_path / 'temporal'
    binary.write_text('fixture')
    binary.chmod(0o700)
    monkeypatch.setenv('MEMOIR_TEST_TEMPORAL_CLI', str(binary))
    options = local_options(tmp_path / 'state.sqlite')
    assert options['dev_server_existing_path'] == str(binary)
    assert options['ip'] == '127.0.0.1' and options['ui'] is False
    assert options['dev_server_database_filename'] == str(tmp_path / 'state.sqlite')
    monkeypatch.setenv('MEMOIR_TEST_TEMPORAL_CLI', 'relative-temporal')
    with pytest.raises(ValueError):
        local_options(tmp_path / 'state.sqlite')
