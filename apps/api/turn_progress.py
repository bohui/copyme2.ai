"""User-visible operation summaries, independent of private model reasoning."""
import os


def thinking_steps_enabled():
    return os.getenv('MEMORY_SPARK_SHOW_THINKING_STEPS', '').strip().lower() in {'1', 'true', 'yes', 'on'}


class TurnProgress:
    def __init__(self, emit, turn_id, project_id, language, *, enabled=True):
        self.enabled = enabled
        self.emit = emit
        self.turn_id = turn_id
        self.project_id = project_id
        self.language = language
        self.steps = []

    async def update(self, key, english, chinese, *, status='running', skill=None, question_pool=None):
        if not self.enabled:
            return
        labels = {'context': ('Conversation context', '对话背景'), 'reply': ('Reply', '回复'), 'save': ('Save', '保存'), 'workspace': ('Workspace', '工作区')}
        label = labels.get(key, (key, key))[self.language == 'zh-CN']
        step = {'id': key, 'kind': 'skill' if skill else 'progress',
                'label': skill or label, 'detail': chinese if self.language == 'zh-CN' else english,
                'status': status}
        if skill:
            step['skill'] = skill
        index = next((i for i, previous in enumerate(self.steps) if previous['id'] == key), None)
        if index is None:
            self.steps.append(step)
        else:
            self.steps[index] = step
        if self.emit:
            await self.emit({'type': 'progress', 'turn_id': self.turn_id,
                             'project_id': self.project_id, 'data': step})

    async def record_question_pool(self, plan):
        """Expose validated question outputs without the collector's private plan."""
        candidates = [{key: candidate[key] for key in ('id', 'question', 'bridge')}
                      for candidate in sorted(plan['candidates'], key=lambda item: item['order'])]
        count = len(candidates)
        await self.update('question-pool',
                          f'Generated question pool · {count} candidates' if count else 'No follow-up questions generated',
                          f'已生成问题池 · {count} 个候选问题' if count else '本轮未生成追问',
                          status='completed')

    async def harness_event(self, event):
        if event.get('type') != 'codex_activity':
            return
        data = event['data']
        statuses = {'running': ('Running', '正在执行'), 'completed': ('Completed', '已完成'), 'failed': ('Failed', '失败')}
        english, chinese = statuses[data['status']]
        await self.update(data['id'], f"{data['label']} · {english}",
                          f"{data['label']} · {chinese}", status=data['status'])
