#!/usr/bin/env python3
"""Run a task-owned check and retain a reviewable exit-code receipt."""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time


def offline_environment(root):
    keep = {'PATH', 'HOME', 'TMPDIR', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'SHELL'}
    keep.update({'MEMOIR_TEST_POSTGRES_BACKEND', 'MEMOIR_BROWSER_URL', 'MEMOIR_TEST_URL',
                 'MEMORY_SPARK_API_ORIGIN', 'PLAYWRIGHT_BROWSERS_PATH',
                 'MEMORY_SPARK_SHOW_THINKING_STEPS', 'MEMORY_SPARK_TASK_DB',
                 'MEMORY_SPARK_DATABASE', 'MEMOIR_RENDERER_FIXTURES',
                 'MEMOIR_RENDERER_EXPECT_FALLBACK', 'MEMOIR_BROWSER_PROFILE_FIXTURE'})
    env = {key: value for key, value in os.environ.items() if key in keep}
    env['PATH'] = (str(root / 'output/mac-validation/node-runtime/node_modules/.bin') + ':'
                   + str(root / '.venv/bin') + ':' + env.get('PATH', ''))
    env.update(MEMORY_SPARK_TEST_MODE='1', MEMORY_SPARK_ENTITLEMENT_MODEL='legacy',
               NEXT_TELEMETRY_DISABLED='1')
    return env


def save_receipt(path, receipt):
    temporary = path.with_suffix('.json.tmp')
    with temporary.open('w') as stream:
        stream.write(json.dumps(receipt, indent=2) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def stop_owned(process):
    # Popen created this exact process group with start_new_session=True.
    # Its leader exiting does not mean its owned descendants have exited.
    group_id = process.pid
    def group_exists():
        try:
            os.killpg(group_id, 0)
            return True
        except ProcessLookupError:
            return False
    if group_exists():
        try:
            os.killpg(group_id, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            process.poll()  # Reap our immediate child without losing its group.
            if not group_exists():
                break
            time.sleep(.05)
        if group_exists():
            try:
                os.killpg(group_id, signal.SIGKILL)
            except ProcessLookupError:
                pass
    if process.poll() is None:
        process.wait(timeout=5)
    deadline = time.monotonic() + 1
    while group_exists() and time.monotonic() < deadline:
        time.sleep(.05)
    return {'owned_group_id': group_id, 'group_gone': not group_exists()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--timeout', type=float, default=900)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', args.name) or not command or args.timeout <= 0:
        parser.error('A safe receipt name, command and positive timeout are required')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = args.output_dir / (args.name + '.json')
    if receipt_path.exists():
        parser.error('Receipt already exists; choose a new name to preserve earlier evidence')
    receipt = {'name': args.name, 'command': command, 'exit_code': None}
    try:
        identity = subprocess.check_output(['git', 'rev-parse', 'HEAD', 'HEAD^{tree}'],
                                           cwd=args.root, text=True, stderr=subprocess.DEVNULL).splitlines()
        if len(identity) != 2 or any(len(value) != 40 for value in identity):
            raise ValueError('Missing Git identity')
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        receipt.update(status='metadata_unavailable', failure_class=type(error).__name__)
        save_receipt(receipt_path, receipt)
        return 2
    receipt.update(base_head=identity[0], tree=identity[1], status='running')
    save_receipt(receipt_path, receipt)
    started = time.monotonic()
    logfile = args.output_dir / (args.name + '.log')
    env = offline_environment(args.root)
    env['MEMOIR_NETWORK_RECEIPT'] = args.name + '-network'
    if any(str(value).startswith('tests/browser_') for value in command):
        env.setdefault('MEMOIR_BROWSER_PROFILE_FIXTURE', '1')
    termination = None
    def receive_signal(signum, frame):
        # Only record intent in the signal handler. Cleanup and receipt I/O
        # happen in the ordinary control flow after Popen returns its handle.
        nonlocal termination
        termination = termination or signum
    handlers = {signum: signal.signal(signum, receive_signal)
                for signum in (signal.SIGINT, signal.SIGTERM)}
    process = None
    code, status = 2, 'launch_failed'
    with logfile.open('w') as stream:
        try:
            process = subprocess.Popen(command, cwd=args.root, stdout=stream,
                                       stderr=subprocess.STDOUT, start_new_session=True, env=env)
            deadline = time.monotonic() + args.timeout
            while termination is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    code, status = 124, 'timed_out'
                    break
                try:
                    code = process.wait(timeout=min(remaining, .2))
                    status = 'completed'
                    break
                except subprocess.TimeoutExpired:
                    pass
        except OSError as error:
            receipt['failure_class'] = type(error).__name__
        finally:
            try:
                if termination is not None:
                    code = 128 + termination
                    status = 'interrupted' if termination == signal.SIGINT else 'terminated'
                    receipt['termination_signal'] = termination
                if process is not None and status != 'completed':
                    try:
                        receipt['cleanup'] = stop_owned(process)
                    except OSError as error:
                        # Preserve the check's failure and actual child outcome
                        # even when the environment blocks group verification.
                        receipt['cleanup'] = {'owned_group_id': process.pid,
                                              'group_gone': False,
                                              'failure_class': type(error).__name__,
                                              'errno': error.errno}
                receipt.update(status=status, exit_code=code,
                               child_returncode=process.returncode if process else None,
                               duration_seconds=round(time.monotonic() - started, 2))
                save_receipt(receipt_path, receipt)
            finally:
                for signum, handler in handlers.items():
                    signal.signal(signum, handler)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
