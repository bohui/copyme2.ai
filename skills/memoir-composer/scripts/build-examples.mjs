// Developer utility: deterministic synthetic fixtures, not real customer content.
import {writeFile,mkdir} from 'node:fs/promises';
import {focusedFixture,broadFixture,formalFixture,progressiveFixture,chineseFixture} from '../tests/fixtures.mjs';
import {preparePlan,validateDraft,renderArtifacts} from './lib.mjs';
const cases={focused_trial:focusedFixture,broad_trial:broadFixture,formal_memoir:formalFixture,
 progressive_update:()=>progressiveFixture(false),protected_update:()=>progressiveFixture(true),chinese_preview:chineseFixture};
for(const [name,fn] of Object.entries(cases)) {
 const pair=fn(),dir=new URL(`../examples/${name}/`,import.meta.url);await mkdir(dir,{recursive:true});
 const report=validateDraft(pair.request,pair.draft);if(!report.ok)throw new Error(name+' '+JSON.stringify(report.errors));
 const files={'request.json':pair.request,'draft.json':pair.draft,'plan.json':preparePlan(pair.request),'validation.json':report};
 for(const [file,obj] of Object.entries(files)) await writeFile(new URL(file,dir),JSON.stringify(obj,null,2)+'\n');
 for(const [file,body] of Object.entries(renderArtifacts(pair.request,pair.draft))) await writeFile(new URL(file,dir),body);
 process.stdout.write(name+': '+report.chapter_counts.map(x=>x.words).join(', ')+' words\n');
}
