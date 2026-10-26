"""Start a bounded stage independently of the tool transport; observe its files."""
import json
from pathlib import Path
import subprocess
import sys

here=Path(__file__).resolve().parent
stage=sys.argv[1]
assert stage in ('concept','design','whitebox','art','production','production_style')
log=(here/(stage+'.log')).open('a')
process=subprocess.Popen([sys.executable,str(here/'stages.py'),stage],cwd=here.parents[1],
    stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
log.close()
print(json.dumps(dict(stage=stage,pid=process.pid,log=str(here/(stage+'.log')))))
