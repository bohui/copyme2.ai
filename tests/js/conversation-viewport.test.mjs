import test from 'node:test';
import assert from 'node:assert/strict';
import { installConversationViewport } from '../../apps/web/client/memoir/conversation-scroll.mjs';

// Safari's keyboard changes the VisualViewport without changing layout height.
// Focus and viewport events can arrive in either order; dismissal can retain focus.
function fixture({width = 390, height = 844, touch = true, viewport = true} = {}) {
  const window = new EventTarget();
  Object.assign(window, {innerWidth: width, innerHeight: height,
    matchMedia: () => ({matches: touch})});
  if (viewport) {
    window.visualViewport = new EventTarget();
    Object.assign(window.visualViewport, {height, offsetTop: 0, scale: 1});
  }
  const classes = new Set();
  const properties = new Map();
  const document = new EventTarget();
  Object.assign(document, {activeElement: null, documentElement: {
    clientHeight: height,
    classList: {toggle(name, value) { if (value) classes.add(name); else classes.delete(name); }},
    style: {setProperty: (name, value) => properties.set(name, value)},
  }});
  let frame = null;
  Object.assign(globalThis, {window, document,
    requestAnimationFrame: callback => { frame = callback; return 1; }});
  let resizes = 0;
  installConversationViewport(() => { resizes++; });
  const flush = () => { const callback = frame; frame = null; callback?.(); };
  return {
    window, document, properties,
    open: () => classes.has('conversation-keyboard-open'),
    focus(id = 'chat-input') { document.activeElement = {id}; document.dispatchEvent(new Event('focusin')); flush(); },
    blur() { document.activeElement = null; document.dispatchEvent(new Event('focusout')); flush(); },
    visual(values, event = 'resize') { Object.assign(window.visualViewport, values); window.visualViewport.dispatchEvent(new Event(event)); flush(); },
    layout(width, height) { Object.assign(window, {innerWidth: width, innerHeight: height}); document.documentElement.clientHeight = height; window.dispatchEvent(new Event('resize')); flush(); },
    resizes: () => resizes,
  };
}

test('phone typing suppresses workspace only for a keyboard-sized viewport loss; dismiss and reopen retain typing focus', () => {
  const f = fixture();
  f.focus();
  assert.equal(f.open(), false, 'hardware-keyboard focus must keep workspace');
  f.visual({height: 460, offsetTop: 24});
  assert.equal(f.open(), true, 'software keyboard should leave chat as the only panel');
  assert.equal(f.properties.get('--conversation-height'), '460px');
  assert.equal(f.properties.get('--conversation-top'), '24px');
  f.visual({height: 844, offsetTop: 0});
  assert.equal(f.open(), false, 'keyboard dismissal need not blur the textarea');
  f.visual({height: 460});
  assert.equal(f.open(), true);
  f.blur();
  assert.equal(f.open(), true, 'brief blur during a reply paint must not reveal workspace over the keyboard');
  f.visual({height: 844});
  assert.equal(f.open(), false);
});

test('handles keyboard viewport arriving before focus and rotation with the keyboard open', () => {
  const f = fixture();
  f.visual({height: 460});
  assert.equal(f.open(), false, 'viewport loss without typing is not enough');
  f.focus();
  assert.equal(f.open(), true);
  f.layout(844, 390);
  f.visual({height: 220});
  assert.equal(f.open(), true, 'landscape keyboard is still a software keyboard');
  f.visual({height: 390});
  assert.equal(f.open(), false);
});

test('toolbar, pinch zoom, other inputs, absent viewport and desktop do not suppress workspace', () => {
  for (const config of [{}, {touch: false}, {width: 1440}, {viewport: false}]) {
    const f = fixture(config);
    const beforeFocus = f.resizes();
    f.focus();
    assert.equal(f.open(), false);
    if (config.touch === false || config.width === 1440) assert.equal(f.resizes(), beforeFocus, 'desktop focus keeps its existing resize behavior');
    if (!f.window.visualViewport) continue;
    f.visual({height: 760});
    assert.equal(f.open(), false, 'toolbar changes are too small');
    f.visual({height: 400, scale: 2});
    assert.equal(f.open(), false, 'pinch zoom must stay available');
    assert.equal(f.properties.get('--conversation-height'), '844px');
    if (config.touch === false || config.width === 1440) {
      f.visual({height: 460, scale: 1});
      assert.equal(f.open(), false, 'desktop must keep its workspace');
    }
  }
  const f = fixture();
  f.focus('workspace-search');
  f.visual({height: 460});
  assert.equal(f.open(), false);
});
