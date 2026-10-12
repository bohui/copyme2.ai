-- Current source-backed controls are fenced before provider admission.
begin;
create function public.advance_lifetime_continuity_preferences() returns trigger
language plpgsql security definer set search_path='' as $$
begin
 if (tg_op<>'INSERT' and old.kind in ('excluded_topic','paused_topic')) or
    (tg_op<>'DELETE' and new.kind in ('excluded_topic','paused_topic')) then
   update public.user_lifetime_conversation set preference_revision=preference_revision+1
     where user_id=coalesce(new.user_id,old.user_id) and conversation_id=coalesce(new.conversation_id,old.conversation_id);
 end if;
 return coalesce(new,old);
end $$;
create trigger lifetime_continuity_preferences after insert or update or delete on public.user_lifetime_continuity
 for each row execute function public.advance_lifetime_continuity_preferences();
revoke all on function public.advance_lifetime_continuity_preferences() from public,anon,authenticated;

create function public.persist_lifetime_continuity_updates(p_fence jsonb,p_updates jsonb,p_literal_only boolean default false)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); conversation uuid:=(p_fence->'identity'->>'conversation_id')::uuid; project text;
 item jsonb; data jsonb; ref jsonb; existing public.user_lifetime_continuity%rowtype;
begin
 select project_id into project from public.user_lifetime_conversation where user_id=owner and conversation_id=conversation;
 if not found then raise exception 'conversation unavailable'; end if;
 perform 1 from public.user_memoir_project where user_id=owner and project_id=project for update;
 perform public.lock_lifetime_publication(p_fence);
 if jsonb_typeof(p_updates) is distinct from 'array' or jsonb_array_length(p_updates)>8 then raise exception 'bounded continuity updates required'; end if;
 for item in select value from jsonb_array_elements(p_updates) loop
   if jsonb_typeof(item)<>'object' or exists(select 1 from jsonb_object_keys(item) k where k not in ('record_id','kind','data'))
     or not (item ?& array['record_id','kind','data']) or item->>'kind' not in ('person','unresolved_reference','commitment','excluded_topic','paused_topic')
     then raise exception 'invalid continuity update'; end if;
   data:=item->'data';ref:=data->'source_refs'->0;
   if jsonb_typeof(data->'source_refs') is distinct from 'array' or jsonb_array_length(data->'source_refs')<>1
      or data->>'text' is distinct from ref->>'quote' then raise exception 'verbatim current continuity required'; end if;
   if not exists(select 1 from public.user_narrator_source where user_id=owner and project_id=project and id=(ref->>'source_id')::uuid
     and version=(ref->>'version')::bigint and sequence=(p_fence->>'source_revision')::bigint and status='active') then raise exception 'current source continuity required'; end if;
   if p_literal_only and item->>'kind' not in ('excluded_topic','paused_topic') then raise exception 'only current literal privacy controls allowed'; end if;
   if item->>'kind' in ('excluded_topic','paused_topic') and
     (data->>'assertion'<>'asserted' or not (case item->>'kind'
       when 'excluded_topic' then coalesce(data->>'text','') ~* $literal$^((please\s+)?(do not|don't|don’t|never)\s+(discuss|mention|ask (me )?about|bring up)\s+.+|I\s+(do not|don't|don’t)\s+want to\s+(discuss|talk about)\s+.+|(请|我)?(不要|别|不想)(再)?(讨论|谈|聊|提)(到|起)?[^，,：:；;]+)$literal$
       when 'paused_topic' then coalesce(data->>'text','') ~* $literal$^(((please|let's|let’s)\s+)?(set aside|pause discussing|pause talking about)\s+.+|(我们|咱们)?先(不聊|不谈|暂停讨论)[^，,：:；;]+)$literal$
       else false end)) then
     raise exception 'direct literal privacy instruction required'; end if;
   select * into existing from public.user_lifetime_continuity where user_id=owner and conversation_id=conversation and record_id=item->>'record_id';
   if found then
     if existing.data is distinct from data or existing.kind is distinct from item->>'kind' then raise exception 'continuity identity conflict'; end if;
   else
     perform public.save_lifetime_continuity(conversation,item->>'record_id',item->>'kind',0,(p_fence->>'policy_epoch')::bigint,(p_fence->>'lease_token')::uuid,data);
   end if;
 end loop;
 return public.capture_lifetime_fence(conversation,(p_fence->>'lease_token')::uuid);
end $$;
revoke all on function public.persist_lifetime_continuity_updates(jsonb,jsonb,boolean) from public,anon;
grant execute on function public.persist_lifetime_continuity_updates(jsonb,jsonb,boolean) to authenticated;
commit;
