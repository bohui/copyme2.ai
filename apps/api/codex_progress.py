"""Private bounded protocol counts, independent of trajectory/renderer output."""
from copy import deepcopy
import hashlib
import math
import re
import time

MAX_TRACKED_TOOL_IDS = 256
MAX_PROGRESS_EVENTS = 4096
_OPERATIONS = ('commandExecution', 'mcpToolCall', 'dynamicToolCall', 'fileChange', 'webSearch')
_TOOL_NAMES = frozenset({'read_file', 'list_dir', 'grep_files', 'apply_patch', 'shell', 'exec_command', 'web_search'})


def _id(value):
    if type(value) is str and re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}', value):
        return hashlib.sha256(value.encode()).digest()
    return None


class WorkerProgress:
    def __init__(self):
        self._data = {'schema_version':'memoir-codex-progress/1', 'scope':'allowlisted_appserver_events', 'sealed':False,
            'appserver_turns_started':0, 'appserver_turns_completed':0,
            'additional_appserver_turns_started':0, 'last_progress_at_monotonic':None,
            'tools_by_operation':{name:{'started':0,'completed':0,'failed':0} for name in _OPERATIONS},
            'allowlisted_tool_starts':{name:0 for name in sorted(_TOOL_NAMES)},
            'unlisted_tool_name_events':0, 'distinct_tool_ids':0,
            'distinct_tool_ids_exact':True, 'repeated_allowlisted_name_starts':0,
            'progress_events':0, 'message_delta_events':0, 'reasoning_delta_events':0,
            'counts_truncated':False, 'timestamps_valid':True}
        self._ids = {}
        self._binding = None

    @property
    def tracked_ids(self):
        return len(self._ids)

    def _stamp(self):
        value = time.monotonic()
        before = self._data['last_progress_at_monotonic']
        if (type(value) not in (int,float) or not 0 <= value < 2**53 or not math.isfinite(value)
                or before is not None and value < before):
            self._data['timestamps_valid'] = False
            return False
        self._data['last_progress_at_monotonic'] = value
        return True

    def begin_turn(self):
        if self._data['sealed'] or not self._stamp():
            return
        self._binding = None
        if self._data['appserver_turns_started'] >= MAX_PROGRESS_EVENTS:
            self._data['counts_truncated'] = True
        self._data['appserver_turns_started'] = min(MAX_PROGRESS_EVENTS,
            self._data['appserver_turns_started'] + 1)
        self._data['additional_appserver_turns_started'] = max(0,self._data['appserver_turns_started'] - 1)

    def bind_turn(self, thread, turn):
        if not self._data['sealed']:
            ids = _id(thread), _id(turn)
            self._binding = ids if all(ids) else None

    def observe(self, method, params):
        if (self._data['sealed'] or self._binding is None or type(params) is not dict
                or (_id(params.get('threadId')), _id(params.get('turnId'))) != self._binding
                or method not in ('item/started','item/completed','item/agentMessage/delta',
                    'item/reasoning/textDelta','item/reasoning/summaryTextDelta')):
            return
        if method.endswith(('delta','Delta')):
            if self._stamp():
                if self._data['progress_events'] >= MAX_PROGRESS_EVENTS:
                    self._data.update(counts_truncated=True,distinct_tool_ids_exact=False)
                    return
                self._data['progress_events'] += 1
                key = 'message_delta_events' if method == 'item/agentMessage/delta' else 'reasoning_delta_events'
                self._data[key] += 1
            return
        item = params.get('item')
        if type(item) is not dict:
            return
        operation = item.get('type')
        identity = _id(item.get('id'))
        if type(operation) is not str or operation not in _OPERATIONS or identity is None:
            return
        item_status, exit_code = item.get('status'), item.get('exitCode')
        if (item_status is not None and (type(item_status) is not str
                or item_status not in ('inProgress','completed','failed','declined'))
                or exit_code is not None and (type(exit_code) is not int or not -2**31 <= exit_code < 2**31)):
            return
        status = 'started' if method == 'item/started' else 'completed'
        if item.get('status') in ('failed','declined') or item.get('exitCode') not in (None,0):
            status = 'failed'
        if not self._stamp():
            return
        if self._data['progress_events'] >= MAX_PROGRESS_EVENTS:
            self._data.update(counts_truncated=True,distinct_tool_ids_exact=False)
            return
        self._data['progress_events'] += 1
        self._data['tools_by_operation'][operation][status] += 1
        # Hash identifiers only in bounded memory. No identifiers enter receipts.
        key = self._binding + (identity,)
        flags = self._ids.get(key)
        if flags is None:
            if len(self._ids) >= MAX_TRACKED_TOOL_IDS:
                self._data.update(counts_truncated=True,distinct_tool_ids_exact=False)
                return
            self._ids[key] = flags = set()
            self._data['distinct_tool_ids'] += 1
        if status == 'started' and 'started' not in flags:
            flags.add('started')
            name = item.get('tool')
            if type(name) is str and name in _TOOL_NAMES:
                if self._data['allowlisted_tool_starts'][name]:
                    self._data['repeated_allowlisted_name_starts'] += 1
                self._data['allowlisted_tool_starts'][name] += 1
            else:
                self._data['unlisted_tool_name_events'] += 1

    def complete_turn(self):
        if not self._data['sealed'] and self._stamp():
            if self._data['appserver_turns_completed'] >= MAX_PROGRESS_EVENTS:
                self._data['counts_truncated'] = True
            self._data['appserver_turns_completed'] = min(MAX_PROGRESS_EVENTS,
                self._data['appserver_turns_completed'] + 1)

    def close(self):
        self._data['sealed'] = True
        self._ids.clear(); self._binding = None

    def snapshot(self):
        return deepcopy(self._data)
