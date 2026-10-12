"""Tenant-scoped incremental optional artifacts, never canonical recovery.

This uploader prepares a candidate manifest. Linking it requires a separately
validated live policy/lease/source fence. Unknown provenance is excluded.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import PurePosixPath
from uuid import UUID


@dataclass(frozen=True)
class ArtifactFile:
    path: str
    content: bytes
    authorized: bool = False


def upload_incremental(owner, files, put_if_absent, *, conversation_id, policy_epoch, execution_generation, chunk_bytes=1024*1024,
                       file_limit=64*1024*1024, job_limit=128*1024*1024, previous=None):
    owner=str(UUID(str(owner)))
    if not 1<=chunk_bytes<=1024*1024 or not chunk_bytes<=file_limit<=128*1024*1024 or not file_limit<=job_limit<=256*1024*1024:
        raise ValueError('invalid bounded artifact configuration')
    scope={'owner_id':owner,'conversation_id':str(UUID(str(conversation_id))),
           'policy_epoch':policy_epoch,'execution_generation':execution_generation}
    if any(type(scope[k]) is not int or scope[k]<0 for k in ('policy_epoch','execution_generation')):
        raise ValueError('invalid artifact scope')
    if previous is not None and any(previous.get(k)!=v for k,v in scope.items()):
        raise ValueError('artifact predecessor scope mismatch')
    prior_state=previous.get('_state',{}) if previous else {}
    state={}
    manifest={'schema_version':3,**scope,'snapshot_semantics':'full_authorized_snapshot','files':[],'removed_paths':[],'omissions':[],'complete':True,
              'canonical_recovery_required':False,'status':'unlinked_candidate',
              'predecessor':previous.get('manifest_id') if previous else None}
    uploaded=0; read=0; seen=set()
    for index,file in enumerate(files):
        path=PurePosixPath(file.path)
        reason=None
        if index>=256: reason='job_file_limit'
        elif not file.authorized: reason='unprovenanced'
        elif path.is_absolute() or '..' in path.parts or len(path.parts)<2 or path.parts[0] not in {'sessions','archived_sessions'} or any(part.startswith('.') for part in path.parts): reason='unsafe_path'
        elif file.path in seen: reason='duplicate_path'
        elif len(file.content)>file_limit: reason='file_resource_limit'
        elif read+len(file.content)>job_limit: reason='job_resource_limit'
        if reason:
            # Do not retain an unsafe filename or content in omission metadata.
            manifest['omissions'].append({'index':index,'reason':reason});manifest['complete']=False
            if index>=256: break
            continue
        read+=len(file.content);seen.add(file.path)
        item={'path':file.path,'bytes':len(file.content),'chunks':[]}
        full_chunks=[]
        prior=prior_state.get(file.path,{})
        old_chunks={chunk['offset']:chunk for chunk in prior.get('chunks',[])}
        for offset in range(0,len(file.content),chunk_bytes):
            data=file.content[offset:offset+chunk_bytes]
            digest=sha256(owner.encode('ascii')+b'\0'+data).hexdigest()
            key=f'{owner}/agent/chunks/v1/{digest}'
            if put_if_absent(key,data): uploaded+=len(data)
            chunk={'key':key,'sha256':sha256(data).hexdigest(),'offset':offset,'bytes':len(data)}
            full_chunks.append(chunk)
            if old_chunks.get(offset)!=chunk: item['chunks'].append(chunk)
        state[file.path]={'bytes':len(file.content),'chunks':full_chunks}
        if item['chunks'] or prior.get('bytes')!=len(file.content): manifest['files'].append(item)
    manifest['removed_paths']=sorted(set(prior_state)-set(state))
    serialized=json.dumps(manifest,sort_keys=True,separators=(',',':')).encode('utf-8')
    unchanged=previous is not None and not manifest['files'] and not manifest['omissions'] and not manifest['removed_paths']
    manifest_bytes=0 if unchanged else len(serialized)
    manifest_id=previous['manifest_id'] if unchanged else sha256(serialized).hexdigest()
    # _state is local resumable bookkeeping, excluded from the uploaded delta.
    return {**manifest,'uploaded_content_bytes':uploaded,'manifest_bytes':manifest_bytes,'manifest_id':manifest_id,'_state':state}
