// A new revision owns the bubble; tokens from the cancelled revision stay ignored.
export function createReplyRevision({message, render, current,
  reducedMotion = () => globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches,
  schedule = callback => setTimeout(callback, 12), cancel = clearTimeout}) {
  const segmenter = typeof Intl.Segmenter === "function" ? new Intl.Segmenter(undefined, {granularity:"grapheme"}) : null;
  const characters = text => segmenter ? Array.from(segmenter.segment(text), item => item.segment) : Array.from(text);
  let revision = -1, target = "", timer = null, erasing = false, eraseStep = 1, settled = [];
  let disposed = false;

  function settle() {
    const waiting = settled;
    settled = [];
    for (const resolve of waiting) resolve();
  }

  function tick() {
    timer = null;
    if (disposed || !current()) { settle(); return; }
    if (reducedMotion()) {
      message.text = target;
      erasing = false;
    } else if (erasing) {
      const visible = characters(message.text);
      message.text = visible.slice(0, Math.max(0, visible.length - eraseStep)).join("");
      erasing = Boolean(message.text);
    } else {
      const visible = characters(message.text), desired = characters(target);
      message.text = desired.slice(0, Math.min(desired.length, visible.length + Math.max(1, Math.ceil(desired.length / 20)))).join("");
    }
    render(message);
    if (erasing || message.text !== target) timer = schedule(tick);
    else settle();
  }

  function animate() {
    if (timer === null) tick();
  }

  return {
    begin(next) {
      if (!Number.isSafeInteger(next) || next < 0 || next <= revision || disposed) return false;
      revision = next;
      target = "";
      erasing = Boolean(message.text);
      eraseStep = Math.max(1, Math.ceil(characters(message.text).length / 20));
      message.provisional = true;
      if (erasing) animate();
      return true;
    },
    append(text, at) {
      if (disposed || !current() || at !== revision || typeof text !== "string") return;
      target += text;
      if (!erasing && timer === null) {
        message.text = target;
        render(message);
      }
    },
    async finish(text) {
      if (disposed || !current()) return;
      if (target !== text) {
        target = text;
        erasing = Boolean(message.text) && !target.startsWith(message.text);
        eraseStep = Math.max(1, Math.ceil(characters(message.text).length / 20));
      }
      const done = new Promise(resolve => settled.push(resolve));
      animate();
      await done;
      if (!disposed && current()) message.provisional = false;
    },
    dispose() {
      disposed = true;
      if (timer !== null) cancel(timer);
      timer = null;
      settle();
    },
  };
}
