"""User-visible operation summaries, independent of private model reasoning."""
import os

from .interview_questions import question_candidates


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

    async def record_question_pool(self, plan, *, context=None):
        """Report the saved selection without exposing private candidate contents."""
        count = len(plan['candidates'])
        await self.update('question-pool',
                          f'Generated question pool · {count} candidates' if count else 'No follow-up questions generated',
                          f'已生成问题池 · {count} 个候选问题' if count else '本轮未生成追问',
                          status='completed')
        chosen_id = plan['chosen_id']
        if chosen_id is None:
            return
        supplied = question_candidates(context or {})
        selected = next((candidate for candidate in supplied if candidate['id'] == chosen_id), None)
        # Saved replies retain their validated B identity even without the original context.
        if selected is not None or chosen_id.startswith('bq-'):
            english, chinese = 'Selected Lane B guidance', '已选用 B 访谈建议'
            labels = {
                'conflict': ('conflict clarification', '核对矛盾信息'),
                'clarification': ('identity clarification', '澄清人物关系'),
                'historical_news': ('historical context', '历史背景线索'),
                'topic_transition': ('connected topic transition', '衔接新话题'),
                'life_essence': ('life reflection', '人生感悟'),
                'follow_up': ('follow-up question', '继续追问'),
            }
            if selected is not None and selected.get('trigger') in labels:
                trigger_english, trigger_chinese = labels[selected['trigger']]
                english += ' · ' + trigger_english
                chinese += ' · ' + trigger_chinese
        elif supplied:
            english, chinese = 'Selected a question for the current narration', '已选择围绕当前讲述的提问'
        else:
            return
        await self.update('question-selection', english, chinese, status='completed')

    async def harness_event(self, event):
        if event.get('type') != 'codex_activity':
            return
        data = event['data']
        statuses = {'running': ('Running', '正在执行'), 'completed': ('Completed', '已完成'), 'failed': ('Failed', '失败')}
        english, chinese = statuses[data['status']]
        await self.update(data['id'], f"{data['label']} · {english}",
                          f"{data['label']} · {chinese}", status=data['status'])
