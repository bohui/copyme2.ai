"""Install the Atlas notification triggers from the current database baseline."""
import os
from pathlib import Path
import sys

import psycopg

BASELINE = Path(__file__).resolve().parents[1] / 'supabase/migrations/202610180001_initial_schema.sql'


def install_atlas_notifications(dsn):
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        connection.execute("set local lock_timeout = '5s'")
        connection.execute("set local statement_timeout = '20s'")
        connection.execute("select pg_advisory_xact_lock(hashtext('memoir_atlas_notifications'))")
        installed, = connection.execute("""
            select count(*) from pg_catalog.pg_trigger
            where tgfoid = to_regprocedure('public.notify_memoir_atlas_update()')
              and tgenabled in ('O', 'A')
              and (tgrelid, tgname) in (
                  ('public.user_memoir_project'::regclass, 'atlas_project_update'),
                  ('public.user_memoir_lane'::regclass, 'atlas_lane_update'),
                  ('public.user_background_skill_work'::regclass, 'atlas_skill_progress'),
                  ('public.user_memory'::regclass, 'atlas_saved_reply')
              )
        """).fetchone()
        if installed == 4:
            return False

        baseline = BASELINE.read_text()
        start = baseline.index('-- Atlas workspace notifications\n')
        end = baseline.index('-- End Atlas workspace notifications\n', start)
        ddl = baseline[start:end].replace('CREATE FUNCTION', 'CREATE OR REPLACE FUNCTION', 1)
        connection.execute(ddl.replace('CREATE TRIGGER atlas_', 'CREATE OR REPLACE TRIGGER atlas_'))
        return True


if __name__ == '__main__':
    try:
        changed = install_atlas_notifications(os.environ['SUPABASE_DB_URL'])
    except (psycopg.Error, OSError, ValueError, KeyError) as error:
        # Error details can contain connection information.
        print(f'Atlas notification setup failed ({type(error).__name__}).', file=sys.stderr)
        raise SystemExit(1) from None
    print('Atlas notifications installed.' if changed else 'Atlas notifications already installed.')
