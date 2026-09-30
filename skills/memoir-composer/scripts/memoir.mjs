#!/usr/bin/env node
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {preparePlan,validateDraft,renderArtifacts,countWords,counter} from './lib.mjs';

function args(argv) {
  const result={command:argv[0]};
  for(let i=1;i<argv.length;i+=2){if(!argv[i].startsWith('--')||argv[i+1]===undefined) throw new Error('Expected --name value arguments');result[argv[i].slice(2)]=argv[i+1];}
  return result;
}
async function json(path) {
  if(!path) throw new Error('Missing required file argument');
  const data=await readFile(resolve(path));
  if(data.length>25*1024*1024) throw new Error('Input exceeds 25 MiB; use scoped snapshots and chapter packets');
  return JSON.parse(data.toString('utf8'));
}
async function save(path,body){
  if(!path) return process.stdout.write(body);
  // No implicit overwrite of other work. Repeating identical output is harmless.
  try {await writeFile(resolve(path),body,{encoding:'utf8',flag:'wx'});}
  catch(e) {if(e.code==='EEXIST'&&(await readFile(resolve(path),'utf8'))===body) return;throw e;}
}
try {
  const a=args(process.argv.slice(2));
  let result;
  if(a.command==='count') result={words:countWords(await readFile(resolve(a.file),'utf8'),a.locale??'en-AU'),counter:counter()};
  else if(a.command==='plan') result=preparePlan(await json(a.request));
  else if(a.command==='validate') result=validateDraft(await json(a.request),await json(a.draft));
  else if(a.command==='render') {
    if(!a['out-dir']) throw new Error('render requires --out-dir');
    const artifacts=renderArtifacts(await json(a.request),await json(a.draft));
    const out=resolve(a['out-dir']);await mkdir(out,{recursive:true});
    // On interruption, files are review-only staging outputs; host commits only a complete manifest.
    for(const [name,body] of Object.entries(artifacts)) await save(join(out,name),body);
    result={status:'rendered_review_only',directory:out,files:Object.keys(artifacts),publication_authorized:false};
  } else throw new Error('Usage: memoir.mjs plan --request file [--out file] | validate --request file --draft file [--out file] | render --request file --draft file --out-dir directory | count --file text.txt --locale en-AU');
  await save(a.out,JSON.stringify(result,null,2)+'\n');
  if(result.ok===false||result.ready===false) process.exitCode=2;
} catch(e) {process.stderr.write(JSON.stringify({error:e.code??'COMMAND_FAILED',message:e.message})+'\n');process.exitCode=1;}
