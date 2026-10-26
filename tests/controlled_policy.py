"""Explicit empty model proposals for neutral SQL seed fixtures only."""


def complete_seed_policy(sql, owner):
    # This models one known neutral proposal per seeded source. It does not
    # inspect source language and never stands in for semantic evaluation.
    sql(f"""do $fixture$
    declare identity record; lease uuid; created boolean; fence jsonb; source jsonb;
    begin
      perform set_config('request.jwt.claim.sub','{owner}',true);
      for identity in select * from public.user_lifetime_conversation where user_id='{owner}' loop
        if not exists(select 1 from public.user_lifetime_pending_policy where user_id='{owner}' and project_id=identity.project_id) then continue;end if;
        select lease_token into lease from public.user_agent_turn_lease where user_id='{owner}' and expires_at>clock_timestamp();
        created:=lease is null;
        if created then lease:=gen_random_uuid();perform public.acquire_user_agent_turn_lease(lease);end if;
        loop
          fence:=public.capture_lifetime_fence(identity.conversation_id,lease);
          source:=public.read_lifetime_policy_review(fence);
          exit when source is null;
          perform public.complete_lifetime_policy_review(fence,(source->>'id')::uuid,(source->>'version')::bigint,
            '{{"complete":true,"restrictions":[]}}','{{"response_id":"controlled-neutral-seed"}}');
        end loop;
        if created then perform public.release_user_agent_turn_lease(lease);end if;
      end loop;
    end $fixture$;""")


def install_policy_review_transport(monkeypatch, controls=()):
    """Fixed proposals at the real HTTP request seam for offline child processes."""
    import json
    import httpx
    from apps.api import policy_review

    original = policy_review.complete_json

    async def complete(name, payload, schema, **kwargs):
        source = payload['source']
        restrictions = []
        for kind, quote in controls:
            start = source['text'].index(quote)
            restrictions.append(dict(kind=kind, quote=quote, char_start=start, char_end=start + len(quote)))
        output = dict(complete=True, restrictions=restrictions)
        if payload.get('acknowledgement_requested'):
            output['acknowledgement']='We can keep following your memories at your pace.'

        def respond(request):
            return httpx.Response(200, json=dict(id='controlled-policy-response', status='completed',
                output=[dict(type='message', status='completed',
                    content=[dict(type='output_text', text=json.dumps(output))])]))

        kwargs.update(model=kwargs.get('model') or 'controlled-policy-model',
            base_url='http://127.0.0.1:1/v1', api_key='controlled-policy-key', transport=httpx.MockTransport(respond))
        return await original(name, payload, schema, **kwargs)

    monkeypatch.setattr(policy_review, 'complete_json', complete)
