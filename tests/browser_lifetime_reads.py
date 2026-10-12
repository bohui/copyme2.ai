"""Actual client UI, deterministic private-read fixtures; no account/model/network data.

Run against the pinned Next.js checkout: python tests/browser_lifetime_reads.py
--base-url http://127.0.0.1:3010. All API/auth/provider destinations are intercepted.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright
from browser_supabase_fixture import install_supabase_fixture

ROOT=Path(__file__).resolve().parents[1]
OWNER='11111111-1111-4111-8111-111111111111'
SNAPSHOT='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
CURSOR='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'


def run(base, output):
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        for ui_locale in ['en-AU','zh-CN']:
            for width,height in [(1440,1000),(390,844)]:
                context=browser.new_context(viewport={'width':width,'height':height},reduced_motion='reduce')
                context.add_cookies([{'name':'copyme2_ui_locale','value':ui_locale,'url':base},
                    {'name':'copyme2_ui_locale_source','value':'fixed','url':base}])
                install_supabase_fixture(context,f'''const session={{access_token:'fixture-owner',refresh_token:'fixture-refresh',user:{{id:'{OWNER}',is_anonymous:false}}}};
                window.supabase={{createClient:()=>({{auth:{{getSession:async()=>({{data:{{session}}}}),getUser:async()=>({{data:{{user:session.user}}}}),onAuthStateChange:()=>({{data:{{subscription:{{unsubscribe(){{}}}}}}}})}}}})}};''')
                decisions=[];editions=[];rejected=[False];pages=[0];errors=[]
                profile={'name':'Fixture narrator','preferred_language':'en-AU',
                    'conversation_language':{'locale':'en-AU','source':'explicit','revision':1},
                    'profile_intake':{'status':'complete','complete':True}}
                def draft(locale):
                    preview={'title':'Saved original','text':'Protected English original.' if locale=='en-AU' else '受保护的中文原稿。'}
                    proposal={'title':'Proposed revision','text':'Unapproved proposed words.' if locale=='en-AU' else '尚未批准的建议文字。'}
                    record={'id':'first-partition','preview':preview,'proposed_preview':None if rejected[0] else proposal,
                        'proposal_digest':None if rejected[0] else 'c'*64,'approved':True,'human_locked':True}
                    return {'status':'ready','locale':locale,'preview':preview,'first_record':record,
                        'proposed_preview':record['proposed_preview'],'snapshot_id':SNAPSHOT,'root_digest':'b'*64 if rejected[0] else 'a'*64,
                        'coverage_round':5,'page_complete':False,'next_cursor':CURSOR,'updating':False,'error':None,
                        'approval_required':not rejected[0],'publication_approved':False}
                def event(identifier='first-event'):
                    return {'id':identifier,'revision':1,'title':'Ming at school' if identifier=='first-event' else 'Later memory',
                        'kind':'event','life_stage':'unplaced','status':'unresolved','assertion':'inferred',
                        'uncertainty':'Name and year uncertain','timing_conflict':True,'temporal':{'expression':'unknown','precision':'unknown'},
                        'source_refs':[{'source_id':'source-one','version':1,'quote':'Maybe 1963'}],
                        'evidence_next_cursor':CURSOR,'evidence_complete':False,'details_complete':False}
                def api(route):
                    parsed=urlparse(route.request.url);path=parsed.path.split('/api/v1/memoir')[-1];query=parse_qs(parsed.query)
                    body={};method=route.request.method
                    if path=='/agent/config': body={'supabase_url':'https://auth.test','supabase_publishable_key':'public','auth_mode':'supabase'}
                    elif path in ['/user/profile','/agent/profile']: body=profile
                    elif path=='/user/conversations': body={'items':[],'resume_project_id':'lifetime-fixture'}
                    elif path=='/story/state': body={'family_features_enabled':True,'payment_status':'paid','payment_plan':'family_memoir_v1','payment_features':['family_tree','timeline'],
                        'recall_status':{'rounds_completed':20,'free_rounds':20,'paid':True,'payment_required':False}}
                    elif path in ['/projects','/projects/lifetime-fixture']: body={'id':'lifetime-fixture','mode':'self','profile':profile,'composition_stage':3,'workspace_unlocked':True}
                    elif path.endswith('/journey'): body={'active_session':None,'composition_stage':3,'workspace_unlocked':True}
                    elif path.endswith('/history'): body={'items':[],'next_cursor':None,'project_id':'lifetime-fixture'}
                    elif path=='/story/private-draft':
                        locale=query.get('language',['en-AU'])[0];editions.append(locale);body=draft(locale)
                    elif path=='/story/private-draft/page':
                        pages[0]+=1;body={'snapshot_id':SNAPSHOT,'complete':True,'next_cursor':None,
                            'records':[{'id':'second-partition','preview':{'title':'Later section','text':'Later saved draft section.'}}]}
                    elif path=='/story/private-draft/proposal':
                        payload=route.request.post_data_json;decisions.append(payload);assert payload['accept'] is False
                        assert payload['root_digest']=='a'*64 and payload['expected_proposal_digest']=='c'*64
                        rejected[0]=True;body=draft(editions[-1])
                    elif path=='/story/events': body={'events':[event('second-event') if query.get('cursor') else event()],
                        'next_cursor':None if query.get('cursor') else CURSOR,'complete':bool(query.get('cursor')),'processing':{'pending_inputs':0}}
                    elif path.endswith('/first-event/sources'): body={'source_refs':[{'quote':'Possibly 1964'}],'complete':True,'next_cursor':None}
                    elif path.endswith('/first-event/details'): body={'details':[{'kind':'temporal_accounts','value':{'expression':'1964','precision':'year'}}],'complete':True,'next_cursor':None}
                    elif path=='/agent/family-context': body={'family_features_enabled':True,'family_context':{'project_id':'lifetime-fixture','revision':1,'people':[],'relationships':[],'timeline':[]}}
                    elif path=='/story/readiness': body={'stages':{},'heuristic':'narrator_context_volume_v1','maximum_percent':50}
                    elif path=='/agent/place-journey': body={'place_journey':None}
                    elif path=='/agent/turn': body={'reply':'Synthetic fixture opening.','conversation_saved':True}
                    elif path.endswith('/conversation-phase'): body={'conversation_phase':{'schema_version':1,'phase':'shape','selection':'explicit','preferred_phase':'shape','revision':1,'reason':'narrator_choice','source_turn_id':None}}
                    elif path.endswith(('/memories','/sources','/chapters','/people','/relationships','/timeline')): body={'items':[],'next_cursor':None}
                    route.fulfill(status=200,content_type='application/json',body=json.dumps(body))
                context.route('**/api/v1/memoir/**',api)
                context.route('https://**',lambda route:route.fallback() if 'auth.test/' in route.request.url else route.abort())
                page=context.new_page()
                page.on('pageerror',lambda error:errors.append({'message':str(error),
                    'stack':error.stack,'page_url':page.url,
                    'frame_urls':[frame.url for frame in page.frames]}))
                page.goto(base+'/memoir/interview/lifetime-fixture',wait_until='networkidle')
                expect(page.locator('[data-draft-locale]')).to_be_visible(timeout=30000)
                expect(page.locator('.private-draft-status')).to_contain_text('Protected English original.')
                page.locator('.private-draft-status details').first.locator('summary').click()
                page.locator('[data-action=load-more-private-draft]').click()
                expect(page.locator('.private-draft-status')).to_contain_text('Later saved draft section.')
                expect(page.locator('[data-action=load-more-private-draft]')).to_have_count(0)
                page.locator('[data-draft-locale]').select_option('zh-CN')
                expect(page.locator('.private-draft-status')).to_contain_text('受保护的中文原稿。')
                assert profile['preferred_language']=='en-AU'
                page.locator('[data-draft-locale]').select_option('en-AU')
                page.locator('.private-draft-status details').filter(has=page.locator('[data-proposal-accept="false"]')).locator('summary').click()
                page.locator('[data-proposal-accept="false"]').click()
                expect(page.locator('[data-proposal-accept]')).to_have_count(0)
                assert len(decisions)==1 and pages[0]==1 and 'zh-CN' in editions
                page.locator('[data-workspace-tab="timeline"]').click()
                expect(page.locator('.timeline-list')).to_contain_text('Name and year uncertain')
                page.locator('[data-action=load-more-memory-events]').click()
                expect(page.locator('.timeline-list')).to_contain_text('Later memory')
                page.locator('[data-more-event-details="first-event"]').click()
                expect(page.locator('.timeline-list')).to_contain_text('1964')
                page.locator('.timeline-row').first.locator('details summary').click()
                page.locator('[data-more-event-evidence="first-event"]').click()
                expect(page.locator('.timeline-row').first).to_contain_text('Possibly 1964')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(output/f'lifetime-read-{ui_locale}-{width}.png'),full_page=True)
                assert not errors,errors
                print(f'PASS {ui_locale}/{width}: actual client draft/event/evidence pages, uncertainty, EN/ZH editions, protected rejection')
                context.close()
        browser.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:3010')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'output/lifetime-read-browser')
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    run(args.base_url.rstrip('/'),args.output_dir)

if __name__=='__main__':main()
