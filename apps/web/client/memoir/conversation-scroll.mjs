// One controller per mounted history. Follow layout growth while reading the
// latest reply; retain the reader's position when they deliberately scroll up.
export function createConversationScroll() {
  let node = null;
  let following = true;
  let lastTop = 0;
  let lastHeight = 0;
  let lastClientHeight = 0;
  let frame = null;
  let layoutPending = false;
  let dispose = () => {};
  const atBottom = () => !node || node.scrollHeight - node.scrollTop - node.clientHeight <= 2;
  const bottom = () => {
    if (!node || !following) return;
    // Instant movement avoids competing animations during streaming, and also
    // respects reduced motion. Never scroll the page or focus another element.
    node.scrollTop = node.scrollHeight;
    lastTop = node.scrollTop;
    lastHeight = node.scrollHeight;
    lastClientHeight = node.clientHeight;
  };
  const schedule = () => {
    layoutPending = true;
    if (frame !== null) return;
    frame = requestAnimationFrame(() => { frame = null; bottom(); layoutPending = false; });
  };
  return {
    following: () => following,
    follow() { following = true; bottom(); },
    pause() { following = false; },
    refresh: schedule,
    mount(next) {
      dispose();
      node = next;
      if (!node) return;
      lastTop = node.scrollTop;
      lastHeight = node.scrollHeight;
      lastClientHeight = node.clientHeight;
      const scroll = () => {
        // Hiding thinking steps can shrink content and clamp scrollTop. That
        // browser adjustment must not be mistaken for a reader scrolling up.
        const geometryChanged = node.scrollHeight !== lastHeight || node.clientHeight !== lastClientHeight;
        const upward = lastTop - node.scrollTop;
        const clampRange = Math.max(0, lastHeight - node.scrollHeight) + Math.max(0, node.clientHeight - lastClientHeight);
        if (upward > clampRange + 48 || (!layoutPending && !geometryChanged && upward > 1)) following = false;
        const gap = node.scrollHeight - node.scrollTop - node.clientHeight;
        if (atBottom() || (node.scrollTop > lastTop + 1 && gap < 48)) following = true;
        lastTop = node.scrollTop;
        lastHeight = node.scrollHeight;
        lastClientHeight = node.clientHeight;
      };
      const wheel = event => { if (event.deltaY < 0) following = false; };
      const key = event => {
        if (['ArrowUp', 'PageUp', 'Home'].includes(event.key) && event.target === node) following = false;
      };
      const pointer = event => {
        if (event.target === node && event.clientX >= node.getBoundingClientRect().right - 18) following = false;
      };
      let touchY = 0;
      const touchStart = event => { touchY = event.touches[0]?.clientY || 0; };
      const touchMove = event => { if ((event.touches[0]?.clientY || 0) > touchY + 2) following = false; };
      const resize = new ResizeObserver(schedule);
      const observeChildren = () => {
        resize.disconnect();
        resize.observe(node);
        for (const child of node.children) resize.observe(child);
      };
      observeChildren();
      const mutation = new MutationObserver(() => { observeChildren(); schedule(); });
      mutation.observe(node, { childList: true, subtree: true, characterData: true });
      const events = {scroll, wheel, keydown:key, pointerdown:pointer, touchstart:touchStart, touchmove:touchMove};
      for (const [name, handler] of Object.entries(events)) node.addEventListener(name, handler, {passive:true});
      const mounted = node;
      dispose = () => {
        resize.disconnect(); mutation.disconnect();
        for (const [name, handler] of Object.entries(events)) mounted.removeEventListener(name, handler);
        if (frame !== null) cancelAnimationFrame(frame);
        frame = null;
        layoutPending = false;
      };
      schedule();
    },
  };
}

export function installConversationViewport(onResize) {
  let frame = null;
  const update = () => {
    frame = null;
    const viewport = window.visualViewport;
    // Preserve browser pinch zoom. Keyboard and toolbar changes use scale 1.
    const normalScale = viewport && Math.abs(viewport.scale - 1) < 0.01;
    const height = normalScale ? viewport.height : window.innerHeight;
    const top = normalScale ? viewport.offsetTop : 0;
    document.documentElement.style.setProperty('--conversation-height', `${height}px`);
    document.documentElement.style.setProperty('--conversation-top', `${top}px`);
    onResize();
  };
  const schedule = () => {
    if (frame === null) frame = requestAnimationFrame(update);
  };
  window.addEventListener('resize', schedule);
  window.visualViewport?.addEventListener('resize', schedule);
  window.visualViewport?.addEventListener('scroll', schedule);
  update();
}
