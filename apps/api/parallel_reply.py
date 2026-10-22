"""Revisable current-turn text; completed policy still owns final saving."""
import asyncio
import json
import os


def parallel_policy_enabled():
    return os.getenv('MEMORY_SPARK_PARALLEL_POLICY_REVIEW', '').lower() in {'1', 'true', 'yes'}


async def discard_generation(task):
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    if not task.cancelled() and task.exception() is None:
        result = task.result()
        artifact = result.get('_artifact_task') if isinstance(result, dict) else None
        if artifact is not None:
            if not artifact.done(): artifact.cancel()
            await asyncio.gather(artifact, return_exceptions=True)


async def reviewed_reply(review, generate, *, source, retract):
    """A fast completed draft cannot commit before review; failed review cancels it."""
    task = asyncio.create_task(generate())
    kept = False
    try:
        decision = await review
        if (not isinstance(decision, dict) or decision.get('source_id') != source['id']
                or decision.get('source_version') != source['version']
                or type(decision.get('restricted')) is not bool):
            raise ValueError('Policy decision does not match the current draft source')
        if decision['restricted']:
            await retract()
            return None
        result = await task
        kept = True
        return result
    finally:
        if not kept:
            from .lifetime_memory_reads import _settle
            await _settle(asyncio.create_task(discard_generation(task)))


def _string(value, index):
    """Decode a JSON string prefix without emitting half an escape or surrogate."""
    if index >= len(value) or value[index] != '"': return None, index, False
    output = []
    index += 1
    escapes = {'"':'"', '\\':'\\', '/':'/', 'b':'\b', 'f':'\f', 'n':'\n', 'r':'\r', 't':'\t'}
    while index < len(value):
        char = value[index]
        if char == '"': return ''.join(output), index + 1, True
        if char == '\\':
            if index + 1 >= len(value): break
            escape = value[index + 1]
            if escape in escapes:
                output.append(escapes[escape]); index += 2; continue
            if escape != 'u': raise ValueError('Invalid reply string escape')
            if index + 6 > len(value): break
            code = int(value[index + 2:index + 6], 16)
            if 0xD800 <= code <= 0xDBFF:
                if index + 12 > len(value): break
                if value[index + 6:index + 8] != '\\u': raise ValueError('Invalid reply surrogate')
                low = int(value[index + 8:index + 12], 16)
                if not 0xDC00 <= low <= 0xDFFF: raise ValueError('Invalid reply surrogate')
                output.append(chr(0x10000 + ((code - 0xD800) << 10) + low - 0xDC00))
                index += 12; continue
            char = chr(code)
            index += 6
        else:
            if ord(char) < 32: raise ValueError('Invalid reply string character')
            index += 1
        if 0xD800 <= ord(char) <= 0xDFFF: raise ValueError('Invalid reply surrogate')
        output.append(char)
    return ''.join(output), index, False


class RevisableReplyStream:
    """Stream only top-level acknowledgement/question strings, never proposal data."""
    def __init__(self):
        self.buffer = ''
        self.text = ''

    def feed(self, chunk):
        self.buffer += chunk
        if len(self.buffer.encode('utf-8')) > 512_000:
            raise ValueError('Reply stream exceeds its byte limit')
        value = self.buffer.lstrip()
        fields = {}
        if not value.startswith('{'): return ''
        index = 1
        while index < len(value):
            while index < len(value) and value[index].isspace(): index += 1
            if index == len(value) or value[index] == '}': break
            try:
                key, end = json.JSONDecoder().raw_decode(value[index:])
            except json.JSONDecodeError: break
            index += end
            while index < len(value) and value[index].isspace(): index += 1
            if index == len(value): break
            if not isinstance(key, str) or value[index] != ':': raise ValueError('Invalid reply field')
            index += 1
            while index < len(value) and value[index].isspace(): index += 1
            if key in fields: raise ValueError('Duplicate visible reply field')
            if key in {'acknowledgement', 'question'}:
                text, end, complete = _string(value, index)
                if text is not None:
                    limit = 2000 if key == 'acknowledgement' else 800
                    fields[key] = text[:limit].strip()
                    index = end
                    if not complete: break
                else:
                    try: _, end = json.JSONDecoder().raw_decode(value[index:])
                    except json.JSONDecodeError: break
                    index += end
            else:
                try: _, end = json.JSONDecoder().raw_decode(value[index:])
                except json.JSONDecodeError: break
                index += end
            while index < len(value) and value[index].isspace(): index += 1
            if index == len(value) or value[index] == '}': break
            if value[index] != ',': raise ValueError('Invalid reply delimiter')
            index += 1
        text = fields.get('acknowledgement', '')
        if text and fields.get('question'): text += '\n\n' + fields['question']
        if not text.startswith(self.text): raise ValueError('Reply text changed within one revision')
        delta = text[len(self.text):]
        self.text = text
        return delta
