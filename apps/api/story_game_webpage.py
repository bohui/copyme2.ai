"""Validate Astra's markup; executable game behavior belongs to the host."""
from html.parser import HTMLParser
import re


ALLOWED_TAGS = frozenset(('html head meta title body main header footer section div p span '
    'h1 h2 h3 h4 button details summary style svg g path rect circle ellipse line polyline polygon').split())
REQUIRED_CLASSES = ('game-framing', 'game-stage', 'game-world', 'game-player',
    'game-scene-label', 'game-controls', 'game-dialogue', 'game-text-equivalent')


class WebpageValidator(HTMLParser):
    def __init__(self, allowed_text):
        super().__init__(convert_charrefs=True)
        self.allowed_text = {' '.join(value.split()) for value in allowed_text} | {'←', '→'}
        self.stack = []
        self.counts = {}
        self.moves = []
        self.interactions = 0
        self.roots = 0
        self.summaries = 0

    def handle_starttag(self, tag, attributes):
        if tag not in ALLOWED_TAGS or len(dict(attributes)) != len(attributes):
            raise ValueError('game_webpage_element_invalid')
        attrs = dict(attributes)
        if any(key.startswith('on') or key in {'src', 'srcdoc', 'href', 'xlink:href', 'nonce',
                'http-equiv', 'formaction'} for key in attrs):
            raise ValueError('game_webpage_attribute_invalid')
        if tag == 'meta' and not (set(attrs) <= {'charset'} or
                set(attrs) <= {'name', 'content'} and attrs.get('name') == 'viewport'):
            raise ValueError('game_webpage_meta_invalid')
        self.check_css(attrs.get('style', ''))
        if attrs.get('id') == 'memoir-game':
            if tag not in {'main', 'div'} or not any(parent == 'body' for parent, _ in self.stack):
                raise ValueError('game_webpage_root_required')
            self.roots += 1
        if tag in {'html', 'head', 'body'}:
            self.counts[tag] = self.counts.get(tag, 0) + 1
        for name in (attrs.get('class') or '').split():
            if name in REQUIRED_CLASSES:
                if not any(parent_attrs.get('id') == 'memoir-game' for _, parent_attrs in self.stack):
                    raise ValueError('game_webpage_root_required')
                self.counts[name] = self.counts.get(name, 0) + 1
        classes = (attrs.get('class') or '').split()
        parents = {name for _, values in self.stack for name in (values.get('class') or '').split()}
        if tag == 'summary' and self.stack and 'game-text-equivalent' in (self.stack[-1][1].get('class') or '').split():
            self.summaries += 1
        if ('game-world' in classes and 'game-stage' not in parents or
                'game-player' in classes and 'game-world' not in parents or
                'game-text-equivalent' in classes and tag != 'details'):
            raise ValueError('game_webpage_structure_invalid')
        if 'game-stage' in (attrs.get('class') or '').split() and attrs.get('tabindex') != '0':
            raise ValueError('game_webpage_focus_required')
        if 'data-game-move' in attrs:
            if tag != 'button' or 'game-controls' not in parents:
                raise ValueError('game_webpage_controls_invalid')
            self.moves.append(attrs['data-game-move'])
        if 'data-game-interact' in attrs:
            if tag != 'button' or 'game-controls' not in parents:
                raise ValueError('game_webpage_controls_invalid')
            self.interactions += 1
        if tag != 'meta':
            self.stack.append((tag, attrs))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag != 'meta':
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1][0] != tag:
            raise ValueError('game_webpage_markup_invalid')
        self.stack.pop()

    def handle_data(self, text):
        if self.stack and self.stack[-1][0] == 'style':
            self.check_css(text)
        elif text.strip() and ' '.join(text.split()) not in self.allowed_text:
            raise ValueError('game_webpage_text_invalid')

    @staticmethod
    def check_css(text):
        # CSS escapes/comments must not conceal an import or external URL.
        text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
        if '\\' in text or re.search(r'url\s*\(|@import|expression\s*\(', text, re.I):
            raise ValueError('game_webpage_css_invalid')


def validate_webpage(html, ui):
    if not isinstance(html, str) or not 100 <= len(html.encode()) <= 150000:
        raise ValueError('game_webpage_size_invalid')
    parser = WebpageValidator(ui.values())
    parser.feed(html)
    parser.close()
    if (parser.stack or parser.roots != 1 or
            any(parser.counts.get(name) != 1 for name in (*REQUIRED_CLASSES, 'html', 'head', 'body'))
            or sorted(parser.moves) != ['-1', '1'] or parser.interactions != 1 or parser.summaries != 1):
        raise ValueError('game_webpage_structure_invalid')
    return html
