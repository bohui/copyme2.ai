"""Canonical collection browser proof; synthetic pages only, no live model."""
import argparse
import json
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

FIRST='11111111-1111-4111-8111-111111111101'
SECOND='11111111-1111-4111-8111-111111111102'
JOB='11111111-1111-4111-8111-111111111199'
OLDER='11111111-1111-4111-8111-111111111198'
ROOT='22222222-2222-4222-8222-222222222222:1'
STAGES=['baby','toddler','childhood','adolescence','young_adulthood','midlife','later_life']


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--base-url',default='http://127.0.0.1:3010');args=parser.parse_args()
    output=Path(__file__).resolve().parents[1]/'output/playwright';output.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True)
        for locale in ['en-AU','zh-CN']:
            context=browser.new_context(viewport={'width':1280,'height':900},locale=locale,accept_downloads=True)
            page=context.new_page();page.add_init_script(f"localStorage.setItem('copyme2_ui_locale','{locale}')")
            page.route('**/agent/config',lambda route:route.fulfill(json={'auth_mode':'test'}))
            profile={'preferred_language':locale,'conversation_language':{'locale':locale,'source':'explicit','revision':1}}
            for path in ['**/agent/profile','**/user/profile']:page.route(path,lambda route:route.fulfill(json=profile))
            state={'revision':0,'loads':0,'task_loads':0,'results':0,'writes':[],'organise':[],'retries':0}
            periods={stage:{'status':'skipped','memory_ids':[],'note':'Skip this stage'} for stage in STAGES}
            periods['childhood']={'status':'recorded','memory_ids':[SECOND],'note':''}
            def collection(route):
                if route.request.method=='PUT':
                    payload=route.request.post_data_json;state['writes'].append(payload);state['revision']+=1
                    route.fulfill(json={'revision':state['revision'],'periods':payload['periods'],'ready':payload['confirm_ready'],'source_fingerprint':'frozen'})
                else:
                    query=parse_qs(urlparse(route.request.url).query);later='cursor' in query;older='task_cursor' in query
                    state['task_loads' if older else 'loads']+=1
                    route.fulfill(json={'revision':state['revision'],'periods':periods,'ready':False,
                        'tasks':[{'id':OLDER if older else JOB,'kind':'BuildOutline','status':'STALE' if older else 'FAILED','error':None if older else 'BOUNDED_JOB_RETRY','result':None}],
                        'tasks_complete':older,'tasks_next_cursor':None if older else JOB,
                        'source_fingerprint':'frozen','complete':later,'next_cursor':None if later else 'source-next',
                        'sources':[{'id':SECOND if later else FIRST,'content':'Second original' if later else 'First <script>not executable</script> original'}]})
            page.route('**/agent/collection/*',collection)
            def organise(route):
                state['organise'].append(route.request.post_data_json)
                route.fulfill(json={'id':JOB,'kind':'BuildOutline','status':'QUEUED','result':None})
            page.route('**/agent/collection/*/organise',organise)
            def result(route):
                later='cursor=' in route.request.url;state['results']+=1
                route.fulfill(json={'id':JOB,'kind':'BuildOutline','status':'SUCCEEDED','root_digest':'root-digest',
                    'complete':later,'next_cursor':None if later else 'result-next','result':{'title':'Selected book title',
                    'suggested_title':'A global theme','proposed':True,'publication_approved':False,'source_references_paginated':True,
                    'coverage':{'complete':True,'scope':'selected_sources'},'sections':[{'id':ROOT,'title':'Cross-page theme'}],
                    'sources':[{'id':SECOND if later else FIRST,'version':1,'content':'Second original' if later else 'First original',
                                'char_start':0,'char_end':15 if later else 14,'root_section_id':ROOT}]}})
            page.route('**/agent/tasks/*',result)
            def retry(route):
                state['retries']+=1
                assert route.request.method=='POST'
                route.fulfill(json={'id':JOB,'kind':'BuildOutline','status':'QUEUED','error':None})
            page.route('**/agent/tasks/*/retry',retry)
            page.goto(args.base_url,wait_until='networkidle')
            page.get_by_role('button',name='Begin my story' if locale=='en-AU' else '开始讲我的故事').click()
            page.locator('[data-profile-trigger]').click();page.locator('[data-profile-action="collection"]').click()
            dialog=page.get_by_role('dialog');expect(dialog).to_be_visible()
            expect(dialog.locator('[data-more-sources]')).to_be_visible()
            dialog.locator('[data-retry]').evaluate('button => { button.click(); button.click(); }')
            expect(dialog.locator('[data-retry]')).to_have_count(0)
            assert state['retries']==1
            dialog.locator('[data-more-tasks]').click()
            expect(dialog.locator('[data-more-tasks]')).to_be_hidden()
            expect(dialog.locator('.collection-task')).to_have_count(2)
            assert state['task_loads']==1
            school=dialog.locator('[data-stage=childhood]');expect(school.locator('option[value="'+SECOND+'"]')).to_have_count(0)
            # Saving page one must preserve the previously selected unseen ID.
            dialog.locator('[data-save]').click()
            expect(dialog.locator('[data-save]')).to_be_enabled()
            assert state['writes'][0]['periods']['childhood']['memory_ids']==[SECOND]
            dialog.locator('[data-more-sources]').click()
            expect(dialog.locator('[data-more-sources]')).to_be_hidden()
            assert state['loads']==2
            expect(school.locator('[data-memories]')).to_have_values([SECOND])
            # Loading page two does not auto-select the first, previously unchosen source.
            school.locator('[data-memories]').select_option([SECOND,FIRST])
            dialog.locator('[data-confirm]').check();dialog.locator('[type=submit]').click()
            expect(dialog.locator(f'.collection-task:has([data-task="{JOB}"]) h3')).to_have_text('Selected book title',timeout=15000)
            assert state['writes'][-1]['periods']['childhood']['memory_ids']==[SECOND,FIRST]
            assert state['organise'][0]['expected_revision']==2 and state['organise'][0]['language']==locale
            assert 'Collection.' not in dialog.inner_text()
            with page.expect_download() as download:dialog.locator('[data-download]').click()
            with open(download.value.path()) as artifact:export=json.load(artifact)
            assert [row['content'] for row in export['sources']]==['First original','Second original']
            assert export['title']=='Selected book title' and export['publication_approved'] is False
            assert {row['root_section_id'] for row in export['sources']}=={ROOT}
            assert state['results']>=3
            page.screenshot(path=str(output/f'collection-pagination-{locale}.png'),full_page=True)
            dialog.locator('[data-close]').click();expect(dialog).to_have_count(0)
            print(f'PASS {locale}: partial source pages, unseen selections, selected order, proposed hierarchy, complete paginated download')
            context.close()
        browser.close()


if __name__=='__main__':main()
