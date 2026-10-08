"""Explicit socket-free PostgreSQL transport for restricted cloud test runners.

This runs the real PostgreSQL engine in a fresh /tmp cluster. SET ROLE tests
SQL grants and RPC authorization, but standalone PostgreSQL has implicit
superuser RLS bypass. It cannot prove RLS, concurrency, or Storage HTTP behavior;
those checks require the native socket transport and are explicitly skipped.
"""
import re
import subprocess
import tempfile
from pathlib import Path

from test_agent_commit_postgres import OWNER, OTHER


def frame_sql(query):
    """Escape literal line breaks before standalone's blank-line framing.

    PostgreSQL's -j input delimiter is not SQL-aware. Remove blank whitespace
    only after protecting quoted-string content, including literals in stored
    PL/pgSQL bodies. No narrator/JSON/reply character may be changed.
    """
    chunks=[]
    i=0
    while i<len(query):
        if query.startswith('--',i):
            end=query.find('\n',i)
            if end<0: end=len(query)
            chunks.append(query[i:end]); i=end
        elif query.startswith('/*',i):
            end=query.find('*/',i+2)
            end=len(query) if end<0 else end+2
            chunks.append(query[i:end]); i=end
        elif query[i]=="'":
            start=i; i+=1
            escaped=start>0 and query[start-1] in 'eE' and (start<2 or not (query[start-2].isalnum() or query[start-2]=='_'))
            while i<len(query):
                if escaped and query[i]=='\\': i+=2; continue
                if query[i]=="'":
                    if i+1<len(query) and query[i+1]=="'": i+=2; continue
                    i+=1; break
                i+=1
            token=query[start:i]
            if '\n' in token or '\r' in token:
                if not escaped: token='E'+token.replace('\\','\\\\')
                token=token.replace('\n','\\n').replace('\r','\\r')
            chunks.append(token)
        else:
            chunks.append(query[i]); i+=1
    return re.sub(r'\n(?:[ \t]*\n)+','\n',''.join(chunks))


def single_database():
    with tempfile.TemporaryDirectory(prefix='memoir-photo-single-',dir='/tmp') as directory:
        data=Path(directory)/'data'
        subprocess.run(['initdb','-D',str(data),'-A','trust','--no-locale'],check=True,capture_output=True)
        def sql(query, *, check=True):
            query=re.sub(r'^\\set[^\n]*\n','',query,flags=re.M)
            query=frame_sql(query)
            result=subprocess.run(['postgres','--single','-j','-D',str(data),'postgres'],
                input=query+'\n\n',capture_output=True,text=True,timeout=45)
            rows=re.findall(r'\t \d+: [^\n]*? = "(.*?)"\t\(typeid =',result.stdout,re.S)
            failed=bool(re.search(r'\b(?:ERROR|FATAL):',result.stderr))
            parsed=subprocess.CompletedProcess(result.args,result.returncode or int(failed),
                '\n'.join(rows)+'\n' if rows else '', result.stderr)
            if check: assert parsed.returncode==0,parsed.stderr
            return parsed
        sql('''create role anon; create role authenticated; create schema auth;
          create table auth.users(id uuid primary key);
          create function auth.uid() returns uuid language sql stable as
            $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
          grant usage on schema auth to authenticated;
          create schema storage;
          create table storage.buckets(id text primary key,name text,public boolean,file_size_limit bigint);
          create table storage.objects(bucket_id text,name text);
          create function storage.foldername(text) returns text[] language sql as $$select string_to_array($1,'/')$$;
        ''')
        root=Path(__file__).resolve().parents[1]/'supabase/legacy-migrations'
        for name in ('202609230001_user_agent_storage.sql','202609230002_agent_sessions.sql',
                     '202609250002_agent_turn_leases.sql','202609250004_fenced_agent_turn_commit.sql'):
            sql((root/name).read_text())
        sql(f"insert into auth.users values ('{OWNER}'),('{OTHER}');")
        yield sql
