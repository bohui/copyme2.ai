"""Run issue70 checks without inherited provider/application credentials.

Set ISSUE70_TEST_PATH to your virtualenv/native-PostgreSQL PATH; optional
ISSUE70_TEST_PYTHONPATH and ISSUE70_TEST_LD_LIBRARY_PATH support local test deps.
An explicit MEMOIR_TEST_TEMPORAL_CLI may select an installed official local CLI.
No model/provider/application credentials are forwarded.
"""
import os
import subprocess
import sys


def main():
    env={key:os.environ[key] for key in ('HOME','LANG','TZ','TMPDIR') if key in os.environ}
    env.update(PATH=os.getenv('ISSUE70_TEST_PATH',os.environ.get('PATH','')),
        MEMORY_SPARK_TEST_MODE='1',MEMOIR_TEST_POSTGRES_BACKEND='native',NO_COLOR='1')
    for source,target in (
        ('ISSUE70_TEST_PYTHONPATH','PYTHONPATH'),
        ('ISSUE70_TEST_LD_LIBRARY_PATH','LD_LIBRARY_PATH'),
        ('MEMOIR_TEST_TEMPORAL_CLI','MEMOIR_TEST_TEMPORAL_CLI')):
        if os.getenv(source):env[target]=os.environ[source]
    command=sys.argv[1:] or [sys.executable,'-m','pytest','-q',
        'tests/test_interview_strategy.py','tests/test_interview_strategy_postgres.py',
        'tests/test_interview_strategy_runtime.py','tests/test_issue70_review_repairs.py',
        'tests/test_issue70_strategy_review_repairs.py','tests/test_two_lane_memory.py']
    return subprocess.call(command,env=env)


if __name__=='__main__':raise SystemExit(main())
