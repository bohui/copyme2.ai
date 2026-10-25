#!/usr/bin/env python3
"""Apply only recording-consent DDL from the fresh-install baseline; keep all data."""
import argparse
import os
from pathlib import Path
import re

import httpx
import psycopg

BUCKET = 'memoir-original-recordings'
BASELINE = Path(__file__).resolve().parents[1] / 'supabase/migrations/202610180001_initial_schema.sql'


def recording_schema(source):
    start = source.index('-- Consent is server-owned evidence')
    end = source.index('CREATE FUNCTION public.original_recording_descriptor', start)
    consent = source[start:end].replace('CREATE TABLE public.user_recording_consent',
        'CREATE TABLE IF NOT EXISTS public.user_recording_consent').replace('CREATE FUNCTION', 'CREATE OR REPLACE FUNCTION')
    for name in ('recording_server_operation','accept_recorded_interview_turn'):
        operation = re.search(r'CREATE FUNCTION public.' + name + r'\(.*?\$\$;', source, re.S)
        if operation is None:
            raise ValueError('Recording operation is missing from the baseline')
        consent += operation[0].replace('CREATE FUNCTION','CREATE OR REPLACE FUNCTION',1) + '\n'
    return consent


def ensure_private_bucket(client):
    response = client.get('bucket/' + BUCKET)
    if response.status_code == 404 or response.status_code == 400 and response.json().get('message') == 'Bucket not found':
        response = client.post('bucket', json={'id':BUCKET, 'name':BUCKET, 'public':False, 'file_size_limit':10485760})
        response.raise_for_status()
        response = client.get('bucket/' + BUCKET)
    response.raise_for_status()
    bucket = response.json()
    if bucket.get('id') != BUCKET or bucket.get('public') is not False:
        raise ValueError('The original-recording bucket must be private; existing public buckets are not modified')


def enable(configuration):
    dsn = configuration.get('MEMOIR_PUBLICATION_DATABASE_URL') or configuration.get('SUPABASE_DB_URL')
    key = configuration.get('SUPABASE_SECRET_KEY') or configuration.get('SUPABASE_SERVICE_ROLE_KEY')
    url = (configuration.get('SUPABASE_URL') or '').rstrip('/')
    if not dsn or not key or not url or configuration.get('MEMOIR_ORIGINAL_RECORDINGS') != '1':
        raise ValueError('Set the database, Supabase server credential and MEMOIR_ORIGINAL_RECORDINGS=1 first')
    ddl = recording_schema(BASELINE.read_text())
    with httpx.Client(base_url=url + '/storage/v1/', headers={'apikey':key,'Authorization':'Bearer ' + key}, timeout=30) as client:
        ensure_private_bucket(client)
    with psycopg.connect(dsn,connect_timeout=5) as connection:
        connection.execute("set local lock_timeout='5000ms'")
        connection.execute("set local statement_timeout='30000ms'")
        connection.execute(ddl)
        connection.execute('revoke all on function public.recording_server_operation(uuid,text,uuid,jsonb) from public,anon,authenticated,service_role')
        connection.execute('update public.original_recording_rollout set enabled=true where singleton')
        if connection.execute('select enabled from public.original_recording_rollout where singleton').fetchone() != (True,):
            raise ValueError('Recording rollout row is missing')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--enable',action='store_true',help='Provision the private bucket, apply consent DDL and enable this database rollout')
    args=parser.parse_args()
    if not args.enable:
        print('Plan: private original-recording bucket, server-owned consent authority, database rollout. Use --enable to apply.')
        return 0
    try:
        enable(os.environ)
    except (httpx.HTTPError, psycopg.Error, ValueError, OSError) as exc:
        # Database/HTTP errors may contain connection credentials or row data.
        print('Recording setup failed (' + type(exc).__name__ + '); verify the database rollout before retrying.')
        return 1
    print('Private recording storage and consent authorization configured; database rollout enabled. Each account must opt in.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
