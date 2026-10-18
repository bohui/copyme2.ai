begin;

-- Add the independently verified same-model collector alias while preserving
-- the checkpoint function's evidence, policy, lease, ownership and grant rules.
do $migration$
declare
  definition text;
  old_models constant text := '(''gpt-5.6-luna-pooled'',''gpt-5.6-luna-memoir-low'',''memoir-luna-low'',''legal2ai-luna-low'',''synthetic-byte-bpe'')';
  new_models constant text := '(''gpt-5.6-luna-pooled'',''gpt-5.6-luna-memoir-low'',''gpt-5.6-luna-memoir-high'',''memoir-luna-low'',''legal2ai-luna-low'',''synthetic-byte-bpe'')';
begin
  definition := pg_catalog.pg_get_functiondef(
    'public.advance_two_lane_checkpoint(uuid,uuid,integer,text)'::regprocedure);
  if position(new_models in definition) > 0 then
    return;
  end if;
  if length(definition) - length(replace(definition, old_models, '')) <> length(old_models) then
    raise exception 'Expected reviewed checkpoint model allowlist exactly once';
  end if;
  execute replace(definition, old_models, new_models);
end
$migration$;

notify pgrst, 'reload schema';
commit;
