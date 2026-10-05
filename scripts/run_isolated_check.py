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
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


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
    with logfile.open('w') as stream:
        try:
            process = subprocess.Popen(command, cwd=args.root, stdout=stream,
                                       stderr=subprocess.STDOUT, start_new_session=True, env=env)
        except OSError as error:
            receipt.update(status='launch_failed', failure_class=type(error).__name__)
            save_receipt(receipt_path, receipt)
            return 2
        try:
            code = process.wait(timeout=args.timeout)
            status = 'completed'
        except subprocess.TimeoutExpired:
            stop_owned(process)
            code, status = 124, 'timed_out'
        except KeyboardInterrupt:
            stop_owned(process)
            code, status = 130, 'interrupted'
    receipt.update(status=status, exit_code=code, child_returncode=process.returncode,
                   duration_seconds=round(time.monotonic() - started, 2))
    save_receipt(receipt_path, receipt)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
