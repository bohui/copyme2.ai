// Linear-space LCS keeps unchanged graphemes steady, including Chinese and emoji.
const graphemes = new Intl.Segmenter(undefined,{granularity:"grapheme"});
const parts = text => Array.from(graphemes.segment(text), part => part.segment);
function lengths(a,b) {
  let row = new Uint32Array(b.length+1);
  for (const value of a) {
    const next = new Uint32Array(b.length+1);
    for (let j=0;j<b.length;j++) next[j+1] = value === b[j] ? row[j]+1 : Math.max(row[j+1],next[j]);
    row = next;
  }
  return row;
}
function common(a,b) {
  if (!a.length || !b.length) return [];
  if (a.length === 1) return b.includes(a[0]) ? a : [];
  const middle = Math.floor(a.length/2), left = lengths(a.slice(0,middle),b);
  const right = lengths(a.slice(middle).reverse(),[...b].reverse());
  let split=0;
  for (let j=1;j<=b.length;j++) if (left[j]+right[b.length-j] > left[split]+right[b.length-split]) split=j;
  return [...common(a.slice(0,middle),b.slice(0,split)),...common(a.slice(middle),b.slice(split))];
}
export function textEdits(before,after) {
  const a=parts(before), b=parts(after);
  let prefix=0, suffix=0;
  while (prefix<a.length && prefix<b.length && a[prefix]===b[prefix]) prefix++;
  while (suffix<a.length-prefix && suffix<b.length-prefix && a.at(-suffix-1)===b.at(-suffix-1)) suffix++;
  const equal=common(a.slice(prefix,a.length-suffix),b.slice(prefix,b.length-suffix));
  let i=prefix,j=prefix,offset=a.slice(0,prefix).join("").length;
  const edits=[];
  for (const value of [...equal,null]) {
    const start=offset, added=[];
    while (i<a.length-suffix && (value===null || a[i]!==value)) offset+=a[i++].length;
    while (j<b.length-suffix && (value===null || b[j]!==value)) added.push(b[j++]);
    if (offset>start || added.length) edits.push({start,end:offset,text:added.join("")});
    if (value!==null) { offset+=value.length;i++;j++; }
  }
  return edits;
}

const pending = new WeakMap();
function boundary(element,offset) {
  const walker=element.ownerDocument.createTreeWalker(element,4);
  let node;
  while ((node=walker.nextNode())) {
    if (offset<=node.length) return [node,offset];
    offset-=node.length;
  }
  return [element,element.childNodes.length];
}
function updateText(element,text) {
  const previous=pending.get(element);
  if (previous?.text===text) return;
  previous?.finish();
  const before=element.textContent;
  if (before===text) return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { element.textContent=text;return; }
  const changes=[], animations=[];
  let live=true;
  const finish=() => {
    if (!live) return;
    live=false;
    for (const animation of animations) animation.cancel();
    for (const {removed,added} of changes) {
      removed?.remove();
      if (added) added.replaceWith(...added.childNodes);
    }
    element.normalize();
    pending.delete(element);
  };
  pending.set(element,{text,finish});
  for (const edit of textEdits(before,text).reverse()) {
    const range=element.ownerDocument.createRange();
    range.setStart(...boundary(element,edit.start));range.setEnd(...boundary(element,edit.end));
    const removed=edit.end>edit.start ? document.createElement("span") : null;
    if (removed) {
      removed.className="memory-text-change is-removed";removed.setAttribute("aria-hidden","true");
      removed.append(range.extractContents());
    }
    const added=edit.text ? document.createElement("span") : null;
    if (added) { added.className="memory-text-change is-added";added.textContent=edit.text;added.hidden=Boolean(removed); }
    const fragment=document.createDocumentFragment();
    if (removed) fragment.append(removed);
    if (added) fragment.append(added);
    range.insertNode(fragment);
    changes.push({removed,added});
    const fadeIn=() => {
      if (!live) return Promise.resolve();
      removed?.remove();
      if (!added) return Promise.resolve();
      added.hidden=false;
      const animation=added.animate([{opacity:0},{opacity:1}],{duration:220,easing:"ease-out",fill:"both"});
      animations.push(animation);
      return animation.finished.catch(()=>{});
    };
    if (removed) {
      const animation=removed.animate([{opacity:1},{opacity:0}],{duration:160,easing:"ease-in",fill:"forwards"});
      animations.push(animation);
      animation.finished.then(fadeIn,()=>{});
    } else void fadeIn();
  }
  // Finish all runs together; a newer revision settles them before rebasing its diff.
  setTimeout(finish,400);
}

function patch(current,next) {
  if (current.nodeType!==next.nodeType || current.nodeName!==next.nodeName) { current.replaceWith(next);return; }
  if (current.nodeType===3) { if (current.data!==next.data) current.data=next.data;return; }
  for (const attribute of [...current.attributes]) if (!next.hasAttribute(attribute.name)) current.removeAttribute(attribute.name);
  for (const attribute of next.attributes) if (current.getAttribute(attribute.name)!==attribute.value) current.setAttribute(attribute.name,attribute.value);
  if (next.hasAttribute("data-memory-text")) { updateText(current,next.textContent);return; }
  const children=[...current.childNodes], desired=[...next.childNodes];
  desired.forEach((child,index) => children[index] ? patch(children[index],child) : current.append(child));
  for (const child of children.slice(desired.length)) child.remove();
}

export function updateMemoryCards(container,markup) {
  const existing=new Map([...container.querySelectorAll(".map-memory-anchor")].map(anchor => [anchor.dataset.memoryKey,anchor]));
  if (!existing.size) { container.innerHTML=markup;return; }
  const template=document.createElement("template");template.innerHTML=markup;
  [...template.content.children].forEach((next,index) => {
    const current=existing.get(next.dataset.memoryKey);
    if (current) { existing.delete(next.dataset.memoryKey);patch(current,next); }
    const anchor=current || next;
    if (container.children[index]!==anchor) container.insertBefore(anchor,container.children[index] || null);
  });
  for (const anchor of existing.values()) anchor.remove();
}
