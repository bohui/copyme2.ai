"""Small real-browser smoke of the production citation/control module."""
import json
import os
from pathlib import Path
import pytest
from test_historical_news import ready_context


@pytest.mark.skipif(not os.getenv("MEMOIR_RUN_HISTORICAL_BROWSER"), reason="Requires a permitted local Chromium launch; opt in with MEMOIR_RUN_HISTORICAL_BROWSER=1")
def test_citation_controls_and_saved_replay_in_browser():
    from playwright.sync_api import sync_playwright
    source=(Path(__file__).resolve().parents[1]/'apps/web/client/memoir/historical-news.mjs').read_text()
    clue=ready_context()['historical_news']['clues'][0]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=os.getenv('CHROMIUM_EXECUTABLE','/usr/bin/chromium'),args=['--no-sandbox'])
        try:
            page=browser.new_page()
            page.set_content('<main id="app"></main>')
            page.add_script_tag(type='module',content=source+'''
                window.news={historicalContext,historicalContextMarkup,bindHistoricalControls};
            ''')
            page.wait_for_function('window.news !== undefined')
            page.evaluate('''clue => {
              window.requests=[]; window.notices=[];
              const snapshot=window.news.historicalContext(clue);
              window.saved=JSON.stringify(snapshot);
              document.querySelector('#app').innerHTML=window.news.historicalContextMarkup(snapshot,'zh-CN');
              window.news.bindHistoricalControls(document, {scope:()=>({projectId:'project'}),current:()=>true,
                api:async(path,options)=>window.requests.push({path,body:JSON.parse(options.body)}),
                notify:text=>window.notices.push(text),locale:()=> 'zh-CN'});
            }''',clue)
            assert page.get_by_role('link',name='Town archive').get_attribute('href')=='https://archive.example/fair'
            assert '1970' in page.locator('aside').inner_text()
            page.get_by_role('button',name='关闭历史线索').click()
            page.wait_for_function('requests.length===1')
            page.get_by_role('button',name='跳过这条线索').click()
            page.wait_for_function('requests.length===2')
            requests=page.evaluate('requests')
            assert requests[0]['body']['enabled'] is False
            assert requests[1]['body']['enabled'] is None # skip cannot reenable
            page.evaluate("document.querySelector('#app').innerHTML=news.historicalContextMarkup(JSON.parse(saved),'en-AU')")
            assert page.get_by_role('link',name='Town archive').count()==1
            assert page.get_by_role('button',name='Skip this clue').count()==1
            assert 'receipt' not in page.evaluate('saved')
        finally:browser.close()
