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
