from scripts import truncate_local_data


def test_check_scope_builds_a_read_only_cache_dependency_guard(monkeypatch):
    calls = []

    def run(command, check):
        calls.append((command, check))

    monkeypatch.setattr(truncate_local_data.subprocess, 'run', run)

    truncate_local_data.check_reset_scope('fixture-database')

    command, check = calls[0]
    sql = command[-1].lower()
    assert check is True
    assert 'lock table' in sql
    assert 'raise exception' in sql
    assert 'truncate ' not in sql
    assert 'delete from auth.users' not in sql
