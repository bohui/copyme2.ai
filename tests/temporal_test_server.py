"""Real disposable Temporal with an optional preinstalled official CLI."""
import os
from pathlib import Path


def local_options(database):
    options = {'download_dest_dir': '/tmp/memoir-issue6-temporal',
               'dev_server_database_filename': str(database), 'ip': '127.0.0.1', 'ui': False}
    existing = os.getenv('MEMOIR_TEST_TEMPORAL_CLI')
    if existing:
        path = Path(existing)
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError('MEMOIR_TEST_TEMPORAL_CLI must be an existing absolute executable')
        options['dev_server_existing_path'] = str(path)
    return options
