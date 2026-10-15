"""Process-owned, provider-free canonical five-case driver adapter."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import signal
import sys
from scripts.controlled_native_state import ROOT, controlled_database, open_case, snapshot_case
from scripts.controlled_lifecycle import ALLOCATION_ROOT_ENV, new_native_root, reconcile_native_directory, sigterm_cancellable


CHILD_CLEANUP_SECONDS = 20


async def cleanup_case(creation, database_directory, environment):
    """Let finally run, then reconcile only this child's private native cluster."""
    process = None
    if creation is not None:
        try:
            process = await creation
        except Exception:
            # The original launch failure still propagates from the caller.
            pass
    if process is not None and process.returncode is None:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), CHILD_CLEANUP_SECONDS)
        except TimeoutError:
            process.kill()
            await asyncio.wait_for(process.wait(), 5)
    await asyncio.to_thread(reconcile_native_directory, database_directory, environment)


@sigterm_cancellable
async def run_isolated_case(case, expected_payload, case_expected, *, args, run_dir, max_rounds, langfuse_publisher=None):
    from scripts.run_isolated_check import offline_environment
    env = offline_environment(ROOT)
    # Dynamic loader and owned CLI paths are runtime prerequisites, not provider
    # or database authority. No configured key/DSN is inherited by this child.
    for key in ('LD_LIBRARY_PATH','MEMOIR_TEST_TEMPORAL_CLI'):
        if os.environ.get(key): env[key]=os.environ[key]
    rounds_dir = Path(run_dir)/'cases'/case['id']/'rounds'
    before = {path.name:path.read_bytes() for path in rounds_dir.glob('round-???.json')}
    database_directory = new_native_root('memoir-case-')
    env[ALLOCATION_ROOT_ENV] = str(database_directory)
    process = creation = None
    value=dict(case=case,expected_payload=expected_payload,case_expected=case_expected,
        args=vars(args),run_dir=str(run_dir),max_rounds=max_rounds,database_directory=str(database_directory))
    try:
        creation = asyncio.create_task(asyncio.create_subprocess_exec(sys.executable,'-m','scripts.controlled_five_case',
            cwd=ROOT,env=env,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE))
        # A cancelled supervisor must still obtain and reap an in-flight child.
        process = await asyncio.shield(creation)
        stdout,_=await process.communicate(json.dumps(value).encode())
    finally:
        # Further cancellation cannot interrupt the bounded reconciliation task.
        cleanup = asyncio.create_task(cleanup_case(creation, database_directory, env))
        cancelled_during_cleanup = False
        while True:
            try:
                await asyncio.shield(cleanup)
                break
            except asyncio.CancelledError:
                cancelled_during_cleanup = True
                if cleanup.done():
                    cleanup.result()
                    break
        if cancelled_during_cleanup:
            raise asyncio.CancelledError
    if process.returncode:
        raise RuntimeError('Controlled canonical case subprocess failed')
    result = json.loads(stdout)
    if langfuse_publisher is not None:
        # Only the parent owns the explicitly configured publisher. The native
        # child receives neither its SDK object nor telemetry credentials.
        from scripts.run_memoir_five_case_evaluation import (
            build_langfuse_round_scores,langfuse_deterministic_status,write_json)
        submitted,unavailable,disabled = 0,0,False
        for path in sorted(rounds_dir.glob('round-???.json')):
            raw=path.read_bytes()
            if before.get(path.name)==raw: continue
            record=json.loads(raw)
            trajectory=record.get('response',{}).get('trajectory')
            if not isinstance(trajectory,dict) or disabled:
                unavailable+=1
                continue
            try:
                with langfuse_publisher.case(name=f"memoir-five-case-{case['id']}-round-{record['round']:03d}",
                        task={'case_id':case['id'],'round':record['round'],'text':record['input']['text']},
                        correlation=trajectory['correlation']) as sink:
                    sink.publish(trajectory,build_langfuse_round_scores(record['grade']),extra_metadata={
                        'round_status':record['grade']['overall'],
                        'deterministic_status':langfuse_deterministic_status(record['grade']),
                        'execution_mode':'fixture'})
                    record['langfuse']={'status':'submitted','durable_readback':'not_verified',
                        'trace_id':sink.trace_id,'observation_id':sink.observation_id,
                        'step_observations':dict(sink.step_observations)}
                submitted+=1
            except Exception as error:
                disabled=True;unavailable+=1
                record['langfuse']={'status':'unavailable','error_type':type(error).__name__}
            write_json(path,record)
        result['langfuse'].update(configured=True,submitted_rounds=submitted,unavailable_rounds=unavailable,
            disabled_after_error=disabled,durable_readback='not_verified' if submitted else 'not_available')
        write_json(Path(run_dir)/'cases'/case['id']/'summary.json',result)
    return result


async def execute(value):
    from scripts.run_memoir_five_case_evaluation import _run_case
    args=argparse.Namespace(**value['args'])
    for key in ('inputs','truth','expected','env_file','output_root'):
        if hasattr(args,key): setattr(args,key,Path(getattr(args,key)))
    case=value['case'];run_dir=Path(value['run_dir'])
    state_path=run_dir/'cases'/case['id']/'storage_state.json'
    state=json.loads(state_path.read_text()) if args.resume and state_path.exists() else None
    with controlled_database(directory_root=value.get('database_directory')) as sql:
        storage,adapter,legacy_places=open_case(sql,case,state)
        storage.place_history=lambda:legacy_places+storage.lifetime_rpc('read_lifetime_place_journeys',p_project_id=storage.project_id)
        storage.state_snapshot=lambda:snapshot_case(sql,storage,legacy_places)
        def entitlement(enabled):
            adapter.entitlement.update(family_tree=enabled,timeline=enabled)
        storage.set_round_entitlement=entitlement
        os.environ.update(MEMORY_SPARK_COLLECTOR_MODEL='synthetic-byte-bpe',
            MEMORY_SPARK_MEMOIR_COMPOSER_MODEL='synthetic-byte-bpe',
            STRIPE_PRICE_FAMILY='synthetic-family-price')
        try:
            storage.save_profile({'preferred_language':case['locale']}) if not state else None
            return await _run_case(case,value['expected_payload'],value['case_expected'],args=args,
                run_dir=run_dir,execution_mode='fixture',max_rounds=value['max_rounds'],canonical_storage=storage)
        finally:
            storage.client.close()


async def main():
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    previous = signal.getsignal(signal.SIGTERM)
    loop.add_signal_handler(signal.SIGTERM, task.cancel)
    try:
        return await execute(json.load(sys.stdin))
    finally:
        loop.remove_signal_handler(signal.SIGTERM)
        signal.signal(signal.SIGTERM, previous)


if __name__=='__main__':
    result=asyncio.run(main())
    print(json.dumps(result,ensure_ascii=False))
