-- Issue 60: bounded owner-only source/event pages and context-volume projection.
-- No model calls, historical mapping, commercial changes or publication approval.
begin;
create table public.user_lifetime_read_cursor (
 id uuid primary key default gen_random_uuid(), user_id uuid not null, project_id text not null,
 conversation_id uuid not null references public.user_lifetime_conversation(conversation_id) on delete cascade,
 kind text not null, event_id text, policy_epoch bigint not null, preference_revision bigint not null,
 source_revision bigint not null, event_revision bigint not null, after_sequence bigint not null default 0,
 after_key text not null default '', created_at timestamptz not null default clock_timestamp()
);
alter table public.user_lifetime_read_cursor enable row level security;
revoke all on public.user_lifetime_read_cursor from public,anon,authenticated;

create function public.read_lifetime_collection_page(p_project_id text,p_kind text,p_after uuid default null,
 p_limit integer default 8,p_event_id text default null) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); identity public.user_lifetime_conversation%rowtype; project public.user_memoir_project%rowtype;
 cursor_row public.user_lifetime_read_cursor%rowtype; records jsonb; extra boolean; cursor_id uuid;
 boundary_sequence bigint:=0; boundary_key text:=''; row_key text; row_sequence bigint;
 source_key text; event_record public.user_memory_event%rowtype; evidence_page jsonb;
begin
 if owner is null or p_limit is null or p_limit not between 1 and 8 or p_kind not in ('sources','events','event_sources','event_details') or
   (p_kind in ('event_sources','event_details') and (p_event_id is null or length(p_event_id)>128)) or (p_kind not in ('event_sources','event_details') and p_event_id is not null)
   then raise exception 'invalid canonical page' using errcode='22023';end if;
 select * into identity from public.user_lifetime_conversation where user_id=owner and project_id=p_project_id;
 if not found then raise exception 'canonical conversation unavailable' using errcode='42501';end if;
 select * into project from public.user_memoir_project where user_id=owner and project_id=p_project_id for share;
 perform 1 from public.user_profile where user_id=owner for share;
 select * into identity from public.user_lifetime_conversation where conversation_id=identity.conversation_id for share;
 if p_after is not null then
   select * into cursor_row from public.user_lifetime_read_cursor where id=p_after and user_id=owner and project_id=p_project_id
     and conversation_id=identity.conversation_id and kind=p_kind and event_id is not distinct from p_event_id;
   if not found then raise exception 'page cursor scope mismatch' using errcode='22023';end if;
   if cursor_row.policy_epoch<>project.policy_epoch or cursor_row.preference_revision<>identity.preference_revision or
     cursor_row.source_revision<>project.source_sequence or cursor_row.event_revision<>project.event_sequence then
     raise exception 'page changed; restart from the first page' using errcode='40001';end if;
   boundary_sequence:=cursor_row.after_sequence;boundary_key:=cursor_row.after_key;
 end if;
 if p_kind='sources' then
   select coalesce(jsonb_agg(public.narrator_source_record(s) order by s.sequence,s.id),'[]') into records from
     (select n.* from public.user_narrator_source n where user_id=owner and project_id=p_project_id and status='active'
       and sequence>boundary_sequence order by sequence,id limit p_limit+1) s;
 elsif p_kind='event_details' then
   select * into event_record from public.user_memory_event where user_id=owner and project_id=p_project_id and id=p_event_id and status<>'withdrawn';
   if not found then raise exception 'event unavailable' using errcode='42501';end if;
   select coalesce(jsonb_agg(item order by key),'[]') into records from (
     select kind||':'||lpad(ordinal::text,20,'0') key,jsonb_build_object('detail_key',kind||':'||lpad(ordinal::text,20,'0'),
       'kind',kind,'value',case kind when 'temporal_accounts' then (value->'temporal')-'basis'
         when 'relations' then value-'source_refs' else value end,'evidence_available_separately',true) item
     from unnest(array['temporal_accounts','relations','candidate_ids','supersedes','contradicts']) kind,
       lateral jsonb_array_elements(case when jsonb_typeof(event_record.data->kind)='array' then event_record.data->kind else '[]'::jsonb end)
         with ordinality detail(value,ordinal)
     where kind||':'||lpad(ordinal::text,20,'0')>boundary_key order by key limit p_limit+1) selected;
 elsif p_kind='event_sources' then
   if not exists(select 1 from public.user_memory_event where user_id=owner and project_id=p_project_id and id=p_event_id and status<>'withdrawn')
     then raise exception 'event unavailable' using errcode='42501';end if;
   select coalesce(jsonb_agg(item order by key),'[]') into records from (
     select s.source_id::text||':'||s.source_version::text||':'||s.evidence_hash key,
       s.evidence||jsonb_build_object('evidence_key',s.source_id::text||':'||s.source_version::text||':'||s.evidence_hash) item
     from public.user_memory_event_source s join public.user_narrator_source n
       on n.user_id=s.user_id and n.project_id=s.project_id and n.id=s.source_id and n.version=s.source_version and n.status='active'
     where s.user_id=owner and s.project_id=p_project_id and s.event_id=p_event_id
       and s.source_id::text||':'||s.source_version::text||':'||s.evidence_hash>boundary_key
     order by key limit p_limit+1) selected;
 else
   records:='[]';
   for event_record in select e.* from public.user_memory_event e where user_id=owner and project_id=p_project_id and status<>'withdrawn'
     and (change_sequence,id)>(boundary_sequence,boundary_key) order by change_sequence,id limit p_limit+1 loop
     -- The complete evidence set is separately paginated; never aggregate all
     -- source_refs or embed accumulated relationship/basis arrays in a list.
     evidence_page:=public.read_lifetime_collection_page(p_project_id,'event_sources',null,1,event_record.id);
     records:=records||jsonb_build_array(jsonb_build_object('id',event_record.id,'revision',event_record.revision,
       'kind',event_record.kind,'life_stage',event_record.life_stage,'status',event_record.status,
       'change_sequence',event_record.change_sequence,'title',event_record.data->'title',
       'temporal',jsonb_build_object('expression',event_record.data->'temporal'->'expression',
         'precision',event_record.data->'temporal'->'precision','year_start',event_record.data->'temporal'->'year_start',
         'year_end',event_record.data->'temporal'->'year_end'),
       'uncertainty',event_record.data->'uncertainty','assertion',event_record.data->'assertion',
       'timing_conflict',coalesce(event_record.data->'timing_conflict','false'),
       'details_complete',not exists(select 1 from unnest(array['temporal_accounts','relations','candidate_ids','supersedes','contradicts']) k
         where jsonb_typeof(event_record.data->k)='array' and jsonb_array_length(event_record.data->k)>0),
       'visibility',event_record.data->'visibility',
       'include_in_print',event_record.data->'include_in_print','source_refs',evidence_page->'source_refs',
       'evidence_complete',evidence_page->'complete','evidence_next_cursor',evidence_page->'next_cursor'));
   end loop;
 end if;
 extra:=jsonb_array_length(records)>p_limit;
 if extra then
   records:=records-p_limit;
   row_key:=case p_kind when 'event_details' then records->-1->>'detail_key' when 'event_sources' then records->-1->>'evidence_key' when 'events' then records->-1->>'id' else '' end;
   row_sequence:=case p_kind when 'sources' then (records->-1->>'sequence')::bigint when 'events' then (records->-1->>'change_sequence')::bigint else 0 end;
   insert into public.user_lifetime_read_cursor(user_id,project_id,conversation_id,kind,event_id,policy_epoch,preference_revision,
     source_revision,event_revision,after_sequence,after_key) values(owner,p_project_id,identity.conversation_id,p_kind,p_event_id,
     project.policy_epoch,identity.preference_revision,project.source_sequence,project.event_sequence,row_sequence,row_key) returning id into cursor_id;
 end if;
 return jsonb_build_object('schema_version',1,'project_id',p_project_id,'conversation_id',identity.conversation_id,
   'source_revision',project.source_sequence,'event_revision',project.event_sequence,'policy_epoch',project.policy_epoch,
   'coverage_scope','current_revision_page','complete',not extra,'next_cursor',cursor_id,
   case p_kind when 'event_details' then 'details' when 'event_sources' then 'source_refs' else p_kind end,records,
   'processing',jsonb_build_object('extracted_through',project.extraction_cursor,'pending_inputs',
     (select count(*) from public.user_narrator_source where user_id=owner and project_id=p_project_id and status='active' and processing_status<>'succeeded')));
end $$;
revoke all on function public.read_lifetime_collection_page(text,text,uuid,integer,text) from public,anon;
grant execute on function public.read_lifetime_collection_page(text,text,uuid,integer,text) to authenticated;

-- Compact projection of the existing narrator_context_volume_v1 heuristic.
-- This is context volume, capped at 50%, never memoir completeness or quality.
-- The explicit Unicode ranges freeze Python 3.12 re.UNICODE's alphanumeric
-- definition and are independent of the database's C/ICU installation locale.
create function public.lifetime_narrator_word_equivalents(p_kind text,p_content text) returns bigint
language plpgsql immutable set search_path='' as $body$
declare narrator text; boundary integer; instruction text; cut integer; han text; total bigint;
begin
 if p_kind<>'agent' or p_content not like 'Storyteller: %' then return 0;end if;
 boundary:=strpos(substring(p_content from 14),E'\nMemory Spark: ');
 if boundary=0 or length(btrim(substring(substring(p_content from 14) from boundary+15)))=0 then return 0;end if;
 narrator:=substring(substring(p_content from 14) from 1 for boundary-1);
 if narrator like 'The storyteller said: %' then
   cut:=length(narrator)+1;
   foreach instruction in array array[
     'This is the storyteller''s first answer to the shared profile-intake opening.',
     'Acknowledge the storyteller naturally, then ask one gentle open-ended follow-up question.',
     'Acknowledge the storyteller briefly, then ask one gentle follow-up question about their memory.'] loop
     boundary:=strpos(narrator,E'\n'||instruction);
     if boundary>0 then cut:=least(cut,boundary);end if;
   end loop;
   if cut<=length(narrator) then narrator:=substring(narrator from 23 for cut-23);end if;
 end if;
 han:='[㐀-䶿一-鿿𠀀-𯨟]';
 select count(*) into total from pg_catalog.regexp_matches(narrator,han,'g');
 narrator:=pg_catalog.regexp_replace(narrator,han,' ','g');
 return total+(select count(*) from pg_catalog.regexp_matches(narrator,$words$[0-9A-Za-zª²-³µ¹-º¼-¾À-ÖØ-öø-ˁˆ-ˑˠ-ˤˬˮͰ-ʹͶ-ͷͺ-ͽͿΆΈ-ΊΌΎ-ΡΣ-ϵϷ-ҁҊ-ԯԱ-Ֆՙՠ-ֈא-תׯ-ײؠ-ي٠-٩ٮ-ٯٱ-ۓەۥ-ۦۮ-ۼۿܐܒ-ܯݍ-ޥޱ߀-ߪߴ-ߵߺࠀ-ࠕࠚࠤࠨࡀ-ࡘࡠ-ࡪࡰ-ࢇࢉ-ࢎࢠ-ࣉऄ-हऽॐक़-ॡ०-९ॱ-ঀঅ-ঌএ-ঐও-নপ-রলশ-হঽৎড়-ঢ়য়-ৡ০-ৱ৴-৹ৼਅ-ਊਏ-ਐਓ-ਨਪ-ਰਲ-ਲ਼ਵ-ਸ਼ਸ-ਹਖ਼-ੜਫ਼੦-੯ੲ-ੴઅ-ઍએ-ઑઓ-નપ-રલ-ળવ-હઽૐૠ-ૡ૦-૯ૹଅ-ଌଏ-ଐଓ-ନପ-ରଲ-ଳଵ-ହଽଡ଼-ଢ଼ୟ-ୡ୦-୯ୱ-୷ஃஅ-ஊஎ-ஐஒ-கங-சஜஞ-டண-தந-பம-ஹௐ௦-௲అ-ఌఎ-ఐఒ-నప-హఽౘ-ౚౝౠ-ౡ౦-౯౸-౾ಀಅ-ಌಎ-ಐಒ-ನಪ-ಳವ-ಹಽೝ-ೞೠ-ೡ೦-೯ೱ-ೲഄ-ഌഎ-ഐഒ-ഺഽൎൔ-ൖ൘-ൡ൦-൸ൺ-ൿඅ-ඖක-නඳ-රලව-ෆ෦-෯ก-ะา-ำเ-ๆ๐-๙ກ-ຂຄຆ-ຊຌ-ຣລວ-ະາ-ຳຽເ-ໄໆ໐-໙ໜ-ໟༀ༠-༳ཀ-ཇཉ-ཬྈ-ྌက-ဪဿ-၉ၐ-ၕၚ-ၝၡၥ-ၦၮ-ၰၵ-ႁႎ႐-႙Ⴀ-ჅჇჍა-ჺჼ-ቈቊ-ቍቐ-ቖቘቚ-ቝበ-ኈኊ-ኍነ-ኰኲ-ኵኸ-ኾዀዂ-ዅወ-ዖዘ-ጐጒ-ጕጘ-ፚ፩-፼ᎀ-ᎏᎠ-Ᏽᏸ-ᏽᐁ-ᙬᙯ-ᙿᚁ-ᚚᚠ-ᛪᛮ-ᛸᜀ-ᜑᜟ-ᜱᝀ-ᝑᝠ-ᝬᝮ-ᝰក-ឳៗៜ០-៩៰-៹᠐-᠙ᠠ-ᡸᢀ-ᢄᢇ-ᢨᢪᢰ-ᣵᤀ-ᤞ᥆-ᥭᥰ-ᥴᦀ-ᦫᦰ-ᧉ᧐-᧚ᨀ-ᨖᨠ-ᩔ᪀-᪉᪐-᪙ᪧᬅ-ᬳᭅ-ᭌ᭐-᭙ᮃ-ᮠᮮ-ᯥᰀ-ᰣ᱀-᱉ᱍ-ᱽᲀ-ᲈᲐ-ᲺᲽ-Ჿᳩ-ᳬᳮ-ᳳᳵ-ᳶᳺᴀ-ᶿḀ-ἕἘ-Ἕἠ-ὅὈ-Ὅὐ-ὗὙὛὝὟ-ώᾀ-ᾴᾶ-ᾼιῂ-ῄῆ-ῌῐ-ΐῖ-Ίῠ-Ῥῲ-ῴῶ-ῼ⁰-ⁱ⁴-⁹ⁿ-₉ₐ-ₜℂℇℊ-ℓℕℙ-ℝℤΩℨK-ℭℯ-ℹℼ-ℿⅅ-ⅉⅎ⅐-↉①-⒛⓪-⓿❶-➓Ⰰ-ⳤⳫ-ⳮⳲ-ⳳ⳽ⴀ-ⴥⴧⴭⴰ-ⵧⵯⶀ-ⶖⶠ-ⶦⶨ-ⶮⶰ-ⶶⶸ-ⶾⷀ-ⷆⷈ-ⷎⷐ-ⷖⷘ-ⷞⸯ々-〇〡-〩〱-〵〸-〼ぁ-ゖゝ-ゟァ-ヺー-ヿㄅ-ㄯㄱ-ㆎ㆒-㆕ㆠ-ㆿㇰ-ㇿ㈠-㈩㉈-㉏㉑-㉟㊀-㊉㊱-㊿㐀-䶿一-ꒌꓐ-ꓽꔀ-ꘌꘐ-ꘫꙀ-ꙮꙿ-ꚝꚠ-ꛯꜗ-ꜟꜢ-ꞈꞋ-ꟊꟐ-ꟑꟓꟕ-ꟙꟲ-ꠁꠃ-ꠅꠇ-ꠊꠌ-ꠢ꠰-꠵ꡀ-ꡳꢂ-ꢳ꣐-꣙ꣲ-ꣷꣻꣽ-ꣾ꤀-ꤥꤰ-ꥆꥠ-ꥼꦄ-ꦲꧏ-꧙ꧠ-ꧤꧦ-ꧾꨀ-ꨨꩀ-ꩂꩄ-ꩋ꩐-꩙ꩠ-ꩶꩺꩾ-ꪯꪱꪵ-ꪶꪹ-ꪽꫀꫂꫛ-ꫝꫠ-ꫪꫲ-ꫴꬁ-ꬆꬉ-ꬎꬑ-ꬖꬠ-ꬦꬨ-ꬮꬰ-ꭚꭜ-ꭩꭰ-ꯢ꯰-꯹가-힣ힰ-ퟆퟋ-ퟻ豈-舘並-龎ﬀ-ﬆﬓ-ﬗיִײַ-ﬨשׁ-זּטּ-לּמּנּ-סּףּ-פּצּ-ﮱﯓ-ﴽﵐ-ﶏﶒ-ﷇﷰ-ﷻﹰ-ﹴﹶ-ﻼ０-９Ａ-Ｚａ-ｚｦ-ﾾￂ-ￇￊ-ￏￒ-ￗￚ-ￜ𐀀-𐀋𐀍-𐀦𐀨-𐀺𐀼-𐀽𐀿-𐁍𐁐-𐁝𐂀-𐃺𐄇-𐄳𐅀-𐅸𐆊-𐆋𐊀-𐊜𐊠-𐋐𐋡-𐋻𐌀-𐌣𐌭-𐍊𐍐-𐍵𐎀-𐎝𐎠-𐏃𐏈-𐏏𐏑-𐏕𐐀-𐒝𐒠-𐒩𐒰-𐓓𐓘-𐓻𐔀-𐔧𐔰-𐕣𐕰-𐕺𐕼-𐖊𐖌-𐖒𐖔-𐖕𐖗-𐖡𐖣-𐖱𐖳-𐖹𐖻-𐖼𐘀-𐜶𐝀-𐝕𐝠-𐝧𐞀-𐞅𐞇-𐞰𐞲-𐞺𐠀-𐠅𐠈𐠊-𐠵𐠷-𐠸𐠼𐠿-𐡕𐡘-𐡶𐡹-𐢞𐢧-𐢯𐣠-𐣲𐣴-𐣵𐣻-𐤛𐤠-𐤹𐦀-𐦷𐦼-𐧏𐧒-𐨀𐨐-𐨓𐨕-𐨗𐨙-𐨵𐩀-𐩈𐩠-𐩾𐪀-𐪟𐫀-𐫇𐫉-𐫤𐫫-𐫯𐬀-𐬵𐭀-𐭕𐭘-𐭲𐭸-𐮑𐮩-𐮯𐰀-𐱈𐲀-𐲲𐳀-𐳲𐳺-𐴣𐴰-𐴹𐹠-𐹾𐺀-𐺩𐺰-𐺱𐼀-𐼧𐼰-𐽅𐽑-𐽔𐽰-𐾁𐾰-𐿋𐿠-𐿶𑀃-𑀷𑁒-𑁯𑁱-𑁲𑁵𑂃-𑂯𑃐-𑃨𑃰-𑃹𑄃-𑄦𑄶-𑄿𑅄𑅇𑅐-𑅲𑅶𑆃-𑆲𑇁-𑇄𑇐-𑇚𑇜𑇡-𑇴𑈀-𑈑𑈓-𑈫𑈿-𑉀𑊀-𑊆𑊈𑊊-𑊍𑊏-𑊝𑊟-𑊨𑊰-𑋞𑋰-𑋹𑌅-𑌌𑌏-𑌐𑌓-𑌨𑌪-𑌰𑌲-𑌳𑌵-𑌹𑌽𑍐𑍝-𑍡𑐀-𑐴𑑇-𑑊𑑐-𑑙𑑟-𑑡𑒀-𑒯𑓄-𑓅𑓇𑓐-𑓙𑖀-𑖮𑗘-𑗛𑘀-𑘯𑙄𑙐-𑙙𑚀-𑚪𑚸𑛀-𑛉𑜀-𑜚𑜰-𑜻𑝀-𑝆𑠀-𑠫𑢠-𑣲𑣿-𑤆𑤉𑤌-𑤓𑤕-𑤖𑤘-𑤯𑤿𑥁𑥐-𑥙𑦠-𑦧𑦪-𑧐𑧡𑧣𑨀𑨋-𑨲𑨺𑩐𑩜-𑪉𑪝𑪰-𑫸𑰀-𑰈𑰊-𑰮𑱀𑱐-𑱬𑱲-𑲏𑴀-𑴆𑴈-𑴉𑴋-𑴰𑵆𑵐-𑵙𑵠-𑵥𑵧-𑵨𑵪-𑶉𑶘𑶠-𑶩𑻠-𑻲𑼂𑼄-𑼐𑼒-𑼳𑽐-𑽙𑾰𑿀-𑿔𒀀-𒎙𒐀-𒑮𒒀-𒕃𒾐-𒿰𓀀-𓐯𓑁-𓑆𔐀-𔙆𖠀-𖨸𖩀-𖩞𖩠-𖩩𖩰-𖪾𖫀-𖫉𖫐-𖫭𖬀-𖬯𖭀-𖭃𖭐-𖭙𖭛-𖭡𖭣-𖭷𖭽-𖮏𖹀-𖺖𖼀-𖽊𖽐𖾓-𖾟𖿠-𖿡𖿣𗀀-𘟷𘠀-𘳕𘴀-𘴈𚿰-𚿳𚿵-𚿻𚿽-𚿾𛀀-𛄢𛄲𛅐-𛅒𛅕𛅤-𛅧𛅰-𛋻𛰀-𛱪𛱰-𛱼𛲀-𛲈𛲐-𛲙𝋀-𝋓𝋠-𝋳𝍠-𝍸𝐀-𝑔𝑖-𝒜𝒞-𝒟𝒢𝒥-𝒦𝒩-𝒬𝒮-𝒹𝒻𝒽-𝓃𝓅-𝔅𝔇-𝔊𝔍-𝔔𝔖-𝔜𝔞-𝔹𝔻-𝔾𝕀-𝕄𝕆𝕊-𝕐𝕒-𝚥𝚨-𝛀𝛂-𝛚𝛜-𝛺𝛼-𝜔𝜖-𝜴𝜶-𝝎𝝐-𝝮𝝰-𝞈𝞊-𝞨𝞪-𝟂𝟄-𝟋𝟎-𝟿𝼀-𝼞𝼥-𝼪𞀰-𞁭𞄀-𞄬𞄷-𞄽𞅀-𞅉𞅎𞊐-𞊭𞋀-𞋫𞋰-𞋹𞓐-𞓫𞓰-𞓹𞟠-𞟦𞟨-𞟫𞟭-𞟮𞟰-𞟾𞠀-𞣄𞣇-𞣏𞤀-𞥃𞥋𞥐-𞥙𞱱-𞲫𞲭-𞲯𞲱-𞲴𞴁-𞴭𞴯-𞴽𞸀-𞸃𞸅-𞸟𞸡-𞸢𞸤𞸧𞸩-𞸲𞸴-𞸷𞸹𞸻𞹂𞹇𞹉𞹋𞹍-𞹏𞹑-𞹒𞹔𞹗𞹙𞹛𞹝𞹟𞹡-𞹢𞹤𞹧-𞹪𞹬-𞹲𞹴-𞹷𞹹-𞹼𞹾𞺀-𞺉𞺋-𞺛𞺡-𞺣𞺥-𞺩𞺫-𞺻🄀-🄌🯰-🯹𠀀-𪛟𪜀-𫜹𫝀-𫠝𫠠-𬺡𬺰-𮯠丽-𪘀𰀀-𱍊𱍐-𲎯]+(?:['’\-][0-9A-Za-zª²-³µ¹-º¼-¾À-ÖØ-öø-ˁˆ-ˑˠ-ˤˬˮͰ-ʹͶ-ͷͺ-ͽͿΆΈ-ΊΌΎ-ΡΣ-ϵϷ-ҁҊ-ԯԱ-Ֆՙՠ-ֈא-תׯ-ײؠ-ي٠-٩ٮ-ٯٱ-ۓەۥ-ۦۮ-ۼۿܐܒ-ܯݍ-ޥޱ߀-ߪߴ-ߵߺࠀ-ࠕࠚࠤࠨࡀ-ࡘࡠ-ࡪࡰ-ࢇࢉ-ࢎࢠ-ࣉऄ-हऽॐक़-ॡ०-९ॱ-ঀঅ-ঌএ-ঐও-নপ-রলশ-হঽৎড়-ঢ়য়-ৡ০-ৱ৴-৹ৼਅ-ਊਏ-ਐਓ-ਨਪ-ਰਲ-ਲ਼ਵ-ਸ਼ਸ-ਹਖ਼-ੜਫ਼੦-੯ੲ-ੴઅ-ઍએ-ઑઓ-નપ-રલ-ળવ-હઽૐૠ-ૡ૦-૯ૹଅ-ଌଏ-ଐଓ-ନପ-ରଲ-ଳଵ-ହଽଡ଼-ଢ଼ୟ-ୡ୦-୯ୱ-୷ஃஅ-ஊஎ-ஐஒ-கங-சஜஞ-டண-தந-பம-ஹௐ௦-௲అ-ఌఎ-ఐఒ-నప-హఽౘ-ౚౝౠ-ౡ౦-౯౸-౾ಀಅ-ಌಎ-ಐಒ-ನಪ-ಳವ-ಹಽೝ-ೞೠ-ೡ೦-೯ೱ-ೲഄ-ഌഎ-ഐഒ-ഺഽൎൔ-ൖ൘-ൡ൦-൸ൺ-ൿඅ-ඖක-නඳ-රලව-ෆ෦-෯ก-ะา-ำเ-ๆ๐-๙ກ-ຂຄຆ-ຊຌ-ຣລວ-ະາ-ຳຽເ-ໄໆ໐-໙ໜ-ໟༀ༠-༳ཀ-ཇཉ-ཬྈ-ྌက-ဪဿ-၉ၐ-ၕၚ-ၝၡၥ-ၦၮ-ၰၵ-ႁႎ႐-႙Ⴀ-ჅჇჍა-ჺჼ-ቈቊ-ቍቐ-ቖቘቚ-ቝበ-ኈኊ-ኍነ-ኰኲ-ኵኸ-ኾዀዂ-ዅወ-ዖዘ-ጐጒ-ጕጘ-ፚ፩-፼ᎀ-ᎏᎠ-Ᏽᏸ-ᏽᐁ-ᙬᙯ-ᙿᚁ-ᚚᚠ-ᛪᛮ-ᛸᜀ-ᜑᜟ-ᜱᝀ-ᝑᝠ-ᝬᝮ-ᝰក-ឳៗៜ០-៩៰-៹᠐-᠙ᠠ-ᡸᢀ-ᢄᢇ-ᢨᢪᢰ-ᣵᤀ-ᤞ᥆-ᥭᥰ-ᥴᦀ-ᦫᦰ-ᧉ᧐-᧚ᨀ-ᨖᨠ-ᩔ᪀-᪉᪐-᪙ᪧᬅ-ᬳᭅ-ᭌ᭐-᭙ᮃ-ᮠᮮ-ᯥᰀ-ᰣ᱀-᱉ᱍ-ᱽᲀ-ᲈᲐ-ᲺᲽ-Ჿᳩ-ᳬᳮ-ᳳᳵ-ᳶᳺᴀ-ᶿḀ-ἕἘ-Ἕἠ-ὅὈ-Ὅὐ-ὗὙὛὝὟ-ώᾀ-ᾴᾶ-ᾼιῂ-ῄῆ-ῌῐ-ΐῖ-Ίῠ-Ῥῲ-ῴῶ-ῼ⁰-ⁱ⁴-⁹ⁿ-₉ₐ-ₜℂℇℊ-ℓℕℙ-ℝℤΩℨK-ℭℯ-ℹℼ-ℿⅅ-ⅉⅎ⅐-↉①-⒛⓪-⓿❶-➓Ⰰ-ⳤⳫ-ⳮⳲ-ⳳ⳽ⴀ-ⴥⴧⴭⴰ-ⵧⵯⶀ-ⶖⶠ-ⶦⶨ-ⶮⶰ-ⶶⶸ-ⶾⷀ-ⷆⷈ-ⷎⷐ-ⷖⷘ-ⷞⸯ々-〇〡-〩〱-〵〸-〼ぁ-ゖゝ-ゟァ-ヺー-ヿㄅ-ㄯㄱ-ㆎ㆒-㆕ㆠ-ㆿㇰ-ㇿ㈠-㈩㉈-㉏㉑-㉟㊀-㊉㊱-㊿㐀-䶿一-ꒌꓐ-ꓽꔀ-ꘌꘐ-ꘫꙀ-ꙮꙿ-ꚝꚠ-ꛯꜗ-ꜟꜢ-ꞈꞋ-ꟊꟐ-ꟑꟓꟕ-ꟙꟲ-ꠁꠃ-ꠅꠇ-ꠊꠌ-ꠢ꠰-꠵ꡀ-ꡳꢂ-ꢳ꣐-꣙ꣲ-ꣷꣻꣽ-ꣾ꤀-ꤥꤰ-ꥆꥠ-ꥼꦄ-ꦲꧏ-꧙ꧠ-ꧤꧦ-ꧾꨀ-ꨨꩀ-ꩂꩄ-ꩋ꩐-꩙ꩠ-ꩶꩺꩾ-ꪯꪱꪵ-ꪶꪹ-ꪽꫀꫂꫛ-ꫝꫠ-ꫪꫲ-ꫴꬁ-ꬆꬉ-ꬎꬑ-ꬖꬠ-ꬦꬨ-ꬮꬰ-ꭚꭜ-ꭩꭰ-ꯢ꯰-꯹가-힣ힰ-ퟆퟋ-ퟻ豈-舘並-龎ﬀ-ﬆﬓ-ﬗיִײַ-ﬨשׁ-זּטּ-לּמּנּ-סּףּ-פּצּ-ﮱﯓ-ﴽﵐ-ﶏﶒ-ﷇﷰ-ﷻﹰ-ﹴﹶ-ﻼ０-９Ａ-Ｚａ-ｚｦ-ﾾￂ-ￇￊ-ￏￒ-ￗￚ-ￜ𐀀-𐀋𐀍-𐀦𐀨-𐀺𐀼-𐀽𐀿-𐁍𐁐-𐁝𐂀-𐃺𐄇-𐄳𐅀-𐅸𐆊-𐆋𐊀-𐊜𐊠-𐋐𐋡-𐋻𐌀-𐌣𐌭-𐍊𐍐-𐍵𐎀-𐎝𐎠-𐏃𐏈-𐏏𐏑-𐏕𐐀-𐒝𐒠-𐒩𐒰-𐓓𐓘-𐓻𐔀-𐔧𐔰-𐕣𐕰-𐕺𐕼-𐖊𐖌-𐖒𐖔-𐖕𐖗-𐖡𐖣-𐖱𐖳-𐖹𐖻-𐖼𐘀-𐜶𐝀-𐝕𐝠-𐝧𐞀-𐞅𐞇-𐞰𐞲-𐞺𐠀-𐠅𐠈𐠊-𐠵𐠷-𐠸𐠼𐠿-𐡕𐡘-𐡶𐡹-𐢞𐢧-𐢯𐣠-𐣲𐣴-𐣵𐣻-𐤛𐤠-𐤹𐦀-𐦷𐦼-𐧏𐧒-𐨀𐨐-𐨓𐨕-𐨗𐨙-𐨵𐩀-𐩈𐩠-𐩾𐪀-𐪟𐫀-𐫇𐫉-𐫤𐫫-𐫯𐬀-𐬵𐭀-𐭕𐭘-𐭲𐭸-𐮑𐮩-𐮯𐰀-𐱈𐲀-𐲲𐳀-𐳲𐳺-𐴣𐴰-𐴹𐹠-𐹾𐺀-𐺩𐺰-𐺱𐼀-𐼧𐼰-𐽅𐽑-𐽔𐽰-𐾁𐾰-𐿋𐿠-𐿶𑀃-𑀷𑁒-𑁯𑁱-𑁲𑁵𑂃-𑂯𑃐-𑃨𑃰-𑃹𑄃-𑄦𑄶-𑄿𑅄𑅇𑅐-𑅲𑅶𑆃-𑆲𑇁-𑇄𑇐-𑇚𑇜𑇡-𑇴𑈀-𑈑𑈓-𑈫𑈿-𑉀𑊀-𑊆𑊈𑊊-𑊍𑊏-𑊝𑊟-𑊨𑊰-𑋞𑋰-𑋹𑌅-𑌌𑌏-𑌐𑌓-𑌨𑌪-𑌰𑌲-𑌳𑌵-𑌹𑌽𑍐𑍝-𑍡𑐀-𑐴𑑇-𑑊𑑐-𑑙𑑟-𑑡𑒀-𑒯𑓄-𑓅𑓇𑓐-𑓙𑖀-𑖮𑗘-𑗛𑘀-𑘯𑙄𑙐-𑙙𑚀-𑚪𑚸𑛀-𑛉𑜀-𑜚𑜰-𑜻𑝀-𑝆𑠀-𑠫𑢠-𑣲𑣿-𑤆𑤉𑤌-𑤓𑤕-𑤖𑤘-𑤯𑤿𑥁𑥐-𑥙𑦠-𑦧𑦪-𑧐𑧡𑧣𑨀𑨋-𑨲𑨺𑩐𑩜-𑪉𑪝𑪰-𑫸𑰀-𑰈𑰊-𑰮𑱀𑱐-𑱬𑱲-𑲏𑴀-𑴆𑴈-𑴉𑴋-𑴰𑵆𑵐-𑵙𑵠-𑵥𑵧-𑵨𑵪-𑶉𑶘𑶠-𑶩𑻠-𑻲𑼂𑼄-𑼐𑼒-𑼳𑽐-𑽙𑾰𑿀-𑿔𒀀-𒎙𒐀-𒑮𒒀-𒕃𒾐-𒿰𓀀-𓐯𓑁-𓑆𔐀-𔙆𖠀-𖨸𖩀-𖩞𖩠-𖩩𖩰-𖪾𖫀-𖫉𖫐-𖫭𖬀-𖬯𖭀-𖭃𖭐-𖭙𖭛-𖭡𖭣-𖭷𖭽-𖮏𖹀-𖺖𖼀-𖽊𖽐𖾓-𖾟𖿠-𖿡𖿣𗀀-𘟷𘠀-𘳕𘴀-𘴈𚿰-𚿳𚿵-𚿻𚿽-𚿾𛀀-𛄢𛄲𛅐-𛅒𛅕𛅤-𛅧𛅰-𛋻𛰀-𛱪𛱰-𛱼𛲀-𛲈𛲐-𛲙𝋀-𝋓𝋠-𝋳𝍠-𝍸𝐀-𝑔𝑖-𝒜𝒞-𝒟𝒢𝒥-𝒦𝒩-𝒬𝒮-𝒹𝒻𝒽-𝓃𝓅-𝔅𝔇-𝔊𝔍-𝔔𝔖-𝔜𝔞-𝔹𝔻-𝔾𝕀-𝕄𝕆𝕊-𝕐𝕒-𝚥𝚨-𝛀𝛂-𝛚𝛜-𝛺𝛼-𝜔𝜖-𝜴𝜶-𝝎𝝐-𝝮𝝰-𝞈𝞊-𝞨𝞪-𝟂𝟄-𝟋𝟎-𝟿𝼀-𝼞𝼥-𝼪𞀰-𞁭𞄀-𞄬𞄷-𞄽𞅀-𞅉𞅎𞊐-𞊭𞋀-𞋫𞋰-𞋹𞓐-𞓫𞓰-𞓹𞟠-𞟦𞟨-𞟫𞟭-𞟮𞟰-𞟾𞠀-𞣄𞣇-𞣏𞤀-𞥃𞥋𞥐-𞥙𞱱-𞲫𞲭-𞲯𞲱-𞲴𞴁-𞴭𞴯-𞴽𞸀-𞸃𞸅-𞸟𞸡-𞸢𞸤𞸧𞸩-𞸲𞸴-𞸷𞸹𞸻𞹂𞹇𞹉𞹋𞹍-𞹏𞹑-𞹒𞹔𞹗𞹙𞹛𞹝𞹟𞹡-𞹢𞹤𞹧-𞹪𞹬-𞹲𞹴-𞹷𞹹-𞹼𞹾𞺀-𞺉𞺋-𞺛𞺡-𞺣𞺥-𞺩𞺫-𞺻🄀-🄌🯰-🯹𠀀-𪛟𪜀-𫜹𫝀-𫠝𫠠-𬺡𬺰-𮯠丽-𪘀𰀀-𱍊𱍐-𲎯]+)*$words$,'g'));
end $body$;
revoke all on function public.lifetime_narrator_word_equivalents(text,text) from public,anon,authenticated;
create table public.user_lifetime_stage_volume (
 memory_id uuid primary key references public.user_memory(id) on delete cascade,
 user_id uuid not null,project_id text not null,client_turn_id uuid,life_stage text not null,word_equivalents bigint not null check(word_equivalents>=0)
);
create index lifetime_stage_volume_project on public.user_lifetime_stage_volume(user_id,project_id,life_stage);
alter table public.user_lifetime_stage_volume enable row level security;
revoke all on public.user_lifetime_stage_volume from public,anon,authenticated;
create function public.update_lifetime_stage_volume() returns trigger
language plpgsql security definer set search_path='' as $$
begin
 if tg_op='DELETE' then delete from public.user_lifetime_stage_volume where memory_id=old.id;return old;end if;
 if new.kind='agent' and new.project_id is not null then
   insert into public.user_lifetime_stage_volume(memory_id,user_id,project_id,client_turn_id,life_stage,word_equivalents)
     values(new.id,new.user_id,new.project_id,new.client_turn_id,new.life_stage,public.lifetime_narrator_word_equivalents(new.kind,new.content))
     on conflict(memory_id) do update set user_id=excluded.user_id,project_id=excluded.project_id,client_turn_id=excluded.client_turn_id,
       life_stage=excluded.life_stage,word_equivalents=excluded.word_equivalents;
 else delete from public.user_lifetime_stage_volume where memory_id=new.id;end if;
 return new;
end $$;
revoke all on function public.update_lifetime_stage_volume() from public,anon,authenticated;
create trigger lifetime_stage_volume after insert or update or delete on public.user_memory
 for each row execute function public.update_lifetime_stage_volume();
-- Additive metadata only: do not UPDATE evidence rows or fire historical jobs.
insert into public.user_lifetime_stage_volume select id,user_id,project_id,client_turn_id,life_stage,
 public.lifetime_narrator_word_equivalents(kind,content) from public.user_memory where kind='agent' and project_id is not null;
create function public.read_lifetime_stage_readiness(p_project_id text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb;
begin
 if auth.uid() is null or not exists(select 1 from public.user_lifetime_conversation where user_id=auth.uid() and project_id=p_project_id)
   then raise exception 'canonical conversation unavailable' using errcode='42501';end if;
 select jsonb_object_agg(stage,jsonb_build_object('word_equivalents',words,
   'percent',round(least(case when words<=300 then words::numeric/10 else 30+least(words-300,700)::numeric*20/700 end,50),1),
   'color',case when words<300 then 'red' when words<1000 then 'amber' else 'green' end)) into result
 from (select stage,coalesce(sum(v.word_equivalents),0) words from unnest(array['baby','toddler','childhood','adolescence','young_adulthood','midlife','later_life']) stage
   left join public.user_lifetime_stage_volume v on v.user_id=auth.uid() and v.project_id=p_project_id and v.life_stage=stage
     and not exists(select 1 from public.user_narrator_source n where n.user_id=v.user_id and n.project_id=v.project_id
       and n.client_turn_id=v.client_turn_id and n.status='withdrawn') group by stage) counts;
 return jsonb_build_object('project_id',p_project_id,'stages',result,'heuristic','narrator_context_volume_v1','maximum_percent',50,'complete',true);
end $$;
revoke all on function public.read_lifetime_stage_readiness(text) from public,anon;
grant execute on function public.read_lifetime_stage_readiness(text) to authenticated;

-- Preserve legacy callers while letting a mapped explicit correction avoid
-- constructing an entire read_user_memory_events response inside its RPC.
alter function public.read_user_memory_events(text) rename to read_user_memory_events_before_lifetime_read_api;
revoke all on function public.read_user_memory_events_before_lifetime_read_api(text) from public,anon,authenticated;
create function public.read_user_memory_events(p_project_id text) returns jsonb
language plpgsql security definer set search_path='' as $$
begin
 if current_setting('memoir.bounded_correction',true)='true' and exists(select 1 from public.user_lifetime_conversation where user_id=auth.uid() and project_id=p_project_id)
   then return jsonb_build_object('changed',true);end if;
 return public.read_user_memory_events_before_lifetime_read_api(p_project_id);
end $$;
revoke all on function public.read_user_memory_events(text) from public,anon;
grant execute on function public.read_user_memory_events(text) to authenticated;
create function public.set_lifetime_event_correction(p_project_id text,p_event_id text,p_expected_revision bigint,p_patch jsonb,p_statement text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare previous text;
begin
 if not exists(select 1 from public.user_lifetime_conversation where user_id=auth.uid() and project_id=p_project_id)
   then raise exception 'canonical conversation unavailable' using errcode='42501';end if;
 previous:=current_setting('memoir.bounded_correction',true);
 perform set_config('memoir.bounded_correction','true',true);
 perform public.correct_user_memory_event(p_project_id,p_event_id,p_expected_revision,p_patch,p_statement);
 perform set_config('memoir.bounded_correction',coalesce(previous,''),true);
 return jsonb_build_object('changed',true);
end $$;
revoke all on function public.set_lifetime_event_correction(text,text,bigint,jsonb,text) from public,anon;
grant execute on function public.set_lifetime_event_correction(text,text,bigint,jsonb,text) to authenticated;
commit;
