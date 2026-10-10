"""Real -m launch with synthetic resources, no native/model/listener actions."""
import json
from pathlib import Path
import subprocess
import sys

from test_single_collector_observation import plan


def test_real_module_entrypoint_uses_canonical_gate_and_terminal_identity(tmp_path):
    directory=tmp_path/'run';directory.mkdir()
    fixture=tmp_path/'fixture';fixture.mkdir()
    # A child-only Python fixture replaces every live preflight/resource seam.
    # The -m entrypoint, canonical gate, observe and teardown remain production.
    (fixture/'sitecustomize.py').write_text('''
from contextlib import asynccontextmanager
from types import SimpleNamespace
from scripts import single_collector_observation as canonical
from scripts import run_issue14_subscription_evaluation as launcher
from scripts import issue14_subscription_session as sessions
from scripts import issue14_subscription_source_contract_v6 as source
import sys
launcher.validate_native_plan=lambda plan:None
launcher.verify_main_source=lambda revision:None
source.audit_subscription_source_v6=lambda root:None
canonical._require_parent_lease=lambda *args:None
# Replace the live lease seam in the pre-repair __main__ copy as well, so
# the red probe reaches the gate identity check rather than allocating a lease.
def entry_trace(frame,event,arg):
    if event=='call' and frame.f_code.co_name=='_child_main' and frame.f_globals.get('__name__')=='__main__':
        frame.f_globals['_require_parent_lease']=lambda *args:None
    return entry_trace
sys.settrace(entry_trace)
@asynccontextmanager
async def resources(plan,run,directory,receipt):
    receipt['native']={'cleanup_complete':False}
    try:yield {}
    finally:receipt['native']['cleanup_complete']=True
launcher.native_resources=resources
class Owner:
    def __init__(self,run):
        self._collector_observation=canonical.CollectorObservationGate(run)
        self.runtime=self
    def bridge_for_case(self,case):
        return SimpleNamespace(driver_inputs=lambda:{'rounds':['synthetic original source'],
            'project_id':'synthetic-project','language':'en-AU'},before_round=lambda *args:{'scope':'synthetic'})
    def storage_for_case(self,case):return object()
    def activate_round(self,case,ordinal):return {'scope':'synthetic'}
    async def turn(self,*args,**kwargs):
        gate=self._collector_observation
        gate.admit('collector',gate.scope)
        gate.complete()
    async def close(self):pass
    def worker_receipts(self):return []
async def create(**kwargs):
    assert kwargs['single_collector_observation'] is True
    assert kwargs['collector_timeout_seconds']==180
    return Owner(kwargs['run'])
sessions.OwnedSubscriptionSession.create=create
def owned(owner):assert type(owner) is Owner
sessions.assert_owned_subscription_session=owned
''')
    value={'plan':plan(),'directory':str(directory),'api_key':'synthetic-private-token','supervisor_pid':1}
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run([sys.executable,'-B','-m','scripts.single_collector_observation','--owned-child'],
        input=json.dumps(value),text=True,capture_output=True,cwd=root,timeout=8,
        env={'PYTHONPATH':str(fixture)+':'+str(root),'PATH':'/usr/bin:/bin'})
    assert result.returncode==0
    receipt=json.loads((directory/'receipt.json').read_text())
    assert receipt['status']=='observation'
    assert receipt['observation']['outcome']=='collector_completed'
    assert receipt['observation']['collector_dispatches']==1
    assert receipt['observation']['conversation_commit_verified'] is False
    assert receipt['cleanup_complete'] is True
    assert receipt['request_accounting']['closed'] is True
    assert receipt['request_accounting']['client_requests_started']==0
    assert 'synthetic-private-token' not in result.stdout+result.stderr+json.dumps(receipt)
