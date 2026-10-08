"""Offline launcher gates; no native container, Temporal or provider execution."""
import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

import scripts.run_issue14_subscription_evaluation as module

REVISION = '9895006f0aaec8425abb21a99f88e39a3a982c2f'


def plan():
    binary = Path('/bin/true').resolve()
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    return module.build_plan(run_id=str(uuid4()), source_revision=REVISION,
        codex_binary=binary, codex_sha256=digest, temporal_binary=binary, temporal_sha256=digest,
        max_client_requests=160, max_elapsed_seconds=1800)


def test_plan_is_bounded_and_never_reads_credentials_or_starts_services(monkeypatch):
    monkeypatch.setattr(module, 'configured_credential', lambda: pytest.fail('Plan read credentials'))
    value = plan()
    assert value['max_client_requests'] == 160
    assert value['max_elapsed_seconds'] == 1800
    assert value['concurrency'] == 1
    assert value['case_ids'] == ['chapters.transitions.en-AU', 'chapters.transitions.zh-CN']
    assert value['rounds_per_case'] == 15
    assert value['execution_started'] is False
    assert value['hard_token_cap_verified'] is value['hard_dollar_cap_verified'] is False


@pytest.mark.parametrize('key,value', [('max_client_requests',0),('max_client_requests',161),
    ('max_client_requests',True),('max_elapsed_seconds',0),('max_elapsed_seconds',1801),
    ('max_elapsed_seconds',float('inf')),('source_revision','main'),('run_id','not-uuid'),
    ('codex_sha256','a'*64),('temporal_sha256','b'*64)])
def test_invalid_plan_fails_before_native_setup(key,value):
    good=plan()
    args={name:good[name] for name in ('run_id','source_revision','codex_binary','codex_sha256',
        'temporal_binary','temporal_sha256','max_client_requests','max_elapsed_seconds')}
    args[key]=value
    with pytest.raises(ValueError):module.build_plan(**args)


@pytest.mark.parametrize('condition', ['wrong_head','dirty','untracked_python'])
def test_source_gate_rejects_unreviewed_tree(monkeypatch,condition):
    def git(*args):
        if args == ('rev-parse','HEAD'):return 'a'*40 if condition=='wrong_head' else REVISION
        if args == ('status','--porcelain','--untracked-files=no'):return ' M apps/api/main.py' if condition=='dirty' else ''
        if args == ('ls-files','--others','--exclude-standard'):return 'tests/unknown.py' if condition=='untracked_python' else ''
        pytest.fail(str(args))
    monkeypatch.setattr(module,'git_read',git)
    with pytest.raises(ValueError):module.verify_source(REVISION)


def test_missing_execute_flag_has_zero_native_calls(tmp_path,monkeypatch):
    called=[]
    monkeypatch.setattr(module,'configured_credential',lambda:called.append('credential'))
    monkeypatch.setattr(module,'execute_native',lambda *a,**k:called.append('native'))
    p=plan()
    args=['--run-id',p['run_id'],'--source-revision',REVISION,'--run-dir',str(tmp_path/'run'),
          '--codex-binary',p['codex_binary'],'--codex-sha256',p['codex_sha256'],
          '--temporal-binary',p['temporal_binary'],'--temporal-sha256',p['temporal_sha256'],
          '--max-client-requests','160','--max-elapsed-seconds','1800']
    assert module.main(args)==0
    assert called==[]
    assert not (tmp_path/'run').exists()


def test_current_route_is_required_before_reading_key(monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_LLM_BASE_URL','http://other.invalid/v1')
    monkeypatch.delenv('MEMORY_SPARK_LLM_API_KEY',raising=False)
    with pytest.raises(ValueError,match='route'):
        module.configured_credential()


def test_key_is_not_part_of_plan_or_error(monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_LLM_BASE_URL',module.EXISTING_ORIGIN)
    monkeypatch.setenv('MEMORY_SPARK_LLM_API_KEY','synthetic-private')
    assert module.configured_credential()=='synthetic-private'
    assert 'synthetic-private' not in str(plan())


def test_existing_env_loader_is_private_allowlisted_and_never_interpolates(tmp_path,monkeypatch):
    path=tmp_path/'.env'
    path.write_text('MEMORY_SPARK_LLM_BASE_URL="'+module.EXISTING_ORIGIN+'"\n'
        'MEMORY_SPARK_LLM_API_KEY="synthetic-${HOME}-private"\n'
        'PATH=/untrusted\nOTHER_SECRET=synthetic-ignored\n')
    path.chmod(0o600)
    monkeypatch.setattr(module.os,'environ',{})
    module.load_existing_application_env(path)
    assert module.os.environ=={'MEMORY_SPARK_LLM_BASE_URL':module.EXISTING_ORIGIN,
        'MEMORY_SPARK_LLM_API_KEY':'synthetic-${HOME}-private'}


def test_explicit_env_file_cannot_inherit_an_unrelated_key(tmp_path,monkeypatch):
    path=tmp_path/'.env';path.write_text('MEMORY_SPARK_LLM_BASE_URL='+module.EXISTING_ORIGIN+'\n');path.chmod(0o600)
    monkeypatch.setenv('MEMORY_SPARK_LLM_API_KEY','synthetic-other-account')
    with pytest.raises(ValueError):module.load_existing_application_env(path)


@pytest.mark.parametrize('uncertain,created,removed,temporal_attempted,temporal_stopped,complete',[
    (True,False,False,False,False,False),(False,True,None,False,False,False),
    (False,True,True,True,False,False),(False,True,True,True,True,True),
    (False,False,False,False,False,True)])
def test_aggregate_cleanup_never_hides_uncertain_allocations(uncertain,created,removed,
        temporal_attempted,temporal_stopped,complete):
    native={'ownership':{'creation_uncertain':uncertain},'postgres_allocation':{'created':created},
        'postgres_removed':removed,'temporal_start_attempted':temporal_attempted,'temporal_stopped':temporal_stopped}
    assert module.native_cleanup_complete(native,False) is complete
    assert module.native_cleanup_complete(native,True) is False


@pytest.mark.parametrize('kind',['public','symlink','fifo','missing'])
def test_existing_env_rejects_unowned_or_nonregular_inputs(tmp_path,kind):
    import os
    path=tmp_path/'.env'
    if kind=='public':
        path.write_text('MEMORY_SPARK_LLM_API_KEY=synthetic-private\n');path.chmod(0o644)
    elif kind=='symlink':path.symlink_to(tmp_path/'missing')
    elif kind=='fifo':os.mkfifo(path,mode=0o600)
    with pytest.raises(ValueError,match='Existing private application environment'):
        module.load_existing_application_env(path)


def test_fresh_process_plan_cannot_construct_global_worker_or_read_key(tmp_path):
    import subprocess,sys,json,os
    program='''
import os,sys,json,hashlib
from pathlib import Path
from uuid import uuid4
home=Path(sys.argv[1]);os.environ['MEMORY_SPARK_CODEX_HOME']=str(home)
reads=[];old=os.getenv
def get(name,default=None):
 if name=='MEMORY_SPARK_LLM_API_KEY':reads.append(name)
 return old(name,default)
os.getenv=get
from scripts.run_issue14_subscription_evaluation import build_plan
b=Path('/bin/true').resolve();h=hashlib.sha256(b.read_bytes()).hexdigest()
build_plan(run_id=str(uuid4()),source_revision='a'*40,codex_binary=b,codex_sha256=h,
 temporal_binary=b,temporal_sha256=h,max_client_requests=160,max_elapsed_seconds=1800)
print(json.dumps({'created':home.exists(),'reads':reads}))
'''
    env={k:v for k,v in os.environ.items() if not k.startswith('MEMORY_SPARK_')}
    result=subprocess.run([sys.executable,'-c',program,str(tmp_path/'unowned')],
        env=env,capture_output=True,text=True,timeout=10,check=True)
    assert json.loads(result.stdout)=={'created':False,'reads':[]}


def test_task_native_environment_is_mac_compatible_and_keeps_model_provenance(tmp_path,monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_LLM_API_KEY','synthetic-private')
    environment=module.native_environment(tmp_path,str(uuid4()))
    assert 'MEMORY_SPARK_LLM_API_KEY' not in environment
    assert environment['MEMORY_SPARK_DISABLE_PRIVDROP']=='1'
    assert environment['MEMORY_SPARK_PRIVATE_DRAFT_CADENCE']=='5'
    assert environment['MEMORY_SPARK_MEMOIR_COMPOSER_MODEL']=='memoir-luna-low'
    assert environment['MEMORY_SPARK_LLM_MODEL']=='gpt-5.6-luna-pooled'
    assert environment['MEMORY_SPARK_AUTHOR_TIMELINE_REASONING_EFFORT']=='low'


def test_native_teardown_failure_invalidates_completed_evaluation(tmp_path,monkeypatch):
    import asyncio
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    import scripts.issue14_subscription_session as sessions
    import scripts.issue14_subscription_runner as runners
    from scripts.issue14_subscription_transport import SubscriptionTransport
    reached=[]
    @asynccontextmanager
    async def resources(plan,run,directory,receipt):
        receipt['native']={'cleanup_complete':False}
        yield {}
        reached.append('teardown')
        raise RuntimeError('synthetic teardown failure')
    async def create(**kwargs):
        async def close():
            await kwargs['provider_transport'].aclose();kwargs['run'].close()
        return SimpleNamespace(close=close,worker_receipts=lambda:[])
    class Runner:
        def __init__(self,session):self.session=session
        async def run(self,**kwargs):
            await self.session.close()
            reached.append('completed')
            return {'status':'completed','output':['synthetic'],'cases':[
                {'observation':{'output':'synthetic'}}]}
    monkeypatch.setattr(module,'native_resources',resources)
    monkeypatch.setattr(sessions.OwnedSubscriptionSession,'create',create)
    monkeypatch.setattr(runners,'SubscriptionProgressiveRunner',Runner)
    monkeypatch.setattr(SubscriptionTransport,'existing_route',lambda *,run,authorization:
        SubscriptionTransport.controlled(run=run,endpoint='http://127.0.0.1:65432/v1/responses'))
    result=asyncio.run(module.execute_native(plan(),tmp_path/'run','synthetic-token'))
    assert reached==['completed','teardown']
    assert result['status']==result['evaluation']['status']=='incomplete'
    assert result['evaluation']['output'] is None
    assert result['evaluation']['cases'][0]['observation']['output'] is None
    assert result['request_accounting']['client_requests_started']==0


@pytest.mark.parametrize('flag',['--assume-unchanged','--skip-worktree'])
def test_exact_source_gate_rejects_hidden_index_changes(tmp_path,monkeypatch,flag):
    import subprocess
    def git(*args):return subprocess.check_output(['git',*args],cwd=tmp_path,text=True).strip()
    git('init','-q');git('config','user.name','Synthetic');git('config','user.email','synthetic@invalid')
    (tmp_path/'guarded.py').write_text('allowed = False\n')
    git('add','guarded.py');git('commit','-qm','synthetic')
    revision=git('rev-parse','HEAD')
    monkeypatch.setattr(module,'ROOT',tmp_path)
    module.verify_source(revision)
    git('update-index',flag,'guarded.py')
    (tmp_path/'guarded.py').write_text('allowed = True\n')
    assert git('status','--porcelain')==''
    with pytest.raises(ValueError):module.verify_source(revision)


@pytest.mark.parametrize('returncode,stderr,accepted',[(0,'',False),(1,'daemon unavailable',False),
    (1,'container not found: memoir-issue6-pg-123456abcdef',True)])
def test_existing_container_or_uncertain_probe_blocks_fixture(monkeypatch,returncode,stderr,accepted):
    from types import SimpleNamespace
    monkeypatch.setattr(module.subprocess,'run',lambda command,**kwargs:
        SimpleNamespace(returncode=returncode,stderr=stderr))
    if accepted:module.require_absent_container('memoir-issue6-pg-123456abcdef')
    else:
        with pytest.raises(ValueError):module.require_absent_container('memoir-issue6-pg-123456abcdef')


@pytest.mark.parametrize('creation_ok',[False,True])
def test_fixture_can_stop_only_once_after_confirmed_owned_create(monkeypatch,creation_ok):
    from types import SimpleNamespace
    calls=[]
    class Deadline:
        def run(self,command,**kwargs):
            calls.append(command)
            if command[:2]==['container','run'] and not creation_ok:
                raise RuntimeError('synthetic already exists or uncertain launch')
            return SimpleNamespace(returncode=0)
    namespace={'ProcessDeadline':Deadline}
    exec('def fixture():\n return ProcessDeadline()\n',namespace)
    monkeypatch.setattr(module,'require_absent_container',lambda name:None)
    name='memoir-issue6-pg-123456abcdef'
    with module.postgres_fixture_ownership(namespace['fixture'],name) as state:
        adapter=namespace['ProcessDeadline']()
        if creation_ok:
            adapter.run(['container','run','--name',name])
            adapter.run(['container','stop',name])
            with pytest.raises(RuntimeError):adapter.run(['container','stop',name])
        else:
            with pytest.raises(RuntimeError):adapter.run(['container','run','--name',name])
            with pytest.raises(RuntimeError):adapter.run(['container','stop',name])
            assert state['creation_uncertain'] is True
        assert state['creation_confirmed'] is creation_ok
    assert sum(command[:2]==['container','stop'] for command in calls)==int(creation_ok)
    assert namespace['ProcessDeadline'] is Deadline
