-- Preserve pre-source-fence evidence without asserting that its basis is current.
-- The sentinel makes it eligible for local hypothesis revalidation, never direct selection.
begin;
update public.user_historical_news_clue set context_revision=context_revision || ':legacy'
 where status='ready' and context_revision ~ '^[0-9]+:[0-9]+:[0-9]+$';
commit;
