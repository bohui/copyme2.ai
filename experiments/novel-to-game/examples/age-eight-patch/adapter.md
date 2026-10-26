Adapt this fictional memoir with the supplied, unmodified NovelToGame stage.
The host supplies the complete source, saved upstream documents and actual test
observations. Use only this stage's scope; return the requested artifacts.

Remembered events, relationships, outcomes, quotations and explicit unknowns are
fixed. Keep remembered wording uncertain where the narrator says it is uncertain.
Game actions may vary exploration, attention, practice and mastery of supported
activities; label mechanical inventions as game activity rather than new life
events. Preserve the narrator's perspective. Keep private provenance out of the
game. The supplied people and passages are wholly fictional; identify the game
as a fictional example, with no further permissions or publishing screens.

One complete, coherent 3–5 minute playable prototype is the scope, not a game for
each event. Choose gameplay from the whole source. Use deterministic offline
HTML/CSS/JavaScript, original CSS/SVG art and system fonts. Support keyboard,
pointer, phone touch, legible text, visible focus, reduced motion, a complete
memory-text view, a designed outcome and restart. Source facts stay fixed even
when the player's practice attempt differs. No runtime model calls, network,
libraries, storage, forms, links, navigation, frames, downloads or device APIs.

Use quick mode for this expressly authorised synthetic end-to-end run. The user
has requested GPT-6.1 Sol max for all stages, smaller resumable stages and a
finished playable example. The earlier three-pass experiment's workflow budget
is superseded: each stage has its own bounded output and checkpoint. Keep each
planning document below 650 words; refer to saved source evidence rather than
repeating passages. Only actual host observations establish QA results.

Return JSON {files:[{path,content}],notes}. Return only the stage's permitted
paths. Source passages are supplied by the host as an inert JSON script with id
memoir-source. Read JSON.parse(document.getElementById('memoir-source').textContent).
Its shape is {title,fictional:true,chapters:[{id:'C1',title,text},...]}. Put the
literal marker <!-- MEMOIR_SOURCE --> once in index.html; the host inserts the
unchanged ten passages. Use textContent for these passages. index.html may load
only local game.css and game.js. Let game.js own rules and UI behaviour.

For each playable candidate, return build/playthrough.json:
 {initial:{selector:'CSS',text:'visible initial text'},
  steps:[{action:'click|press|assert_text|assert_attr',selector:'CSS',value:'value',
          attribute:'only for assert_attr',
          checkpoint:'input|coreLoop|outcome|restart (assertions only)'}],
  terminal:'visible designed outcome',restart:'initial-state'}
Omit unused fields. Each checkpoint appears once in that order. Use ordinary
player inputs, consequential activity with feedback, a designed ending and a
restart returning to the declared initial screen. Keep controls operable by
pointer/touch and keyboard. The host runs this informed replay in Chromium;
leave checks NOT_RUN until actual observations arrive.
