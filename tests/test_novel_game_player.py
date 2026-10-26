"""The actual app renderer loads trusted assets into its nonce-only opaque frame."""
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest
from playwright.sync_api import sync_playwright,expect

from apps.api.novel_game import confirmed_source,runner
from apps.api.novel_game_bundle import journey,validate_bundle
from test_story_game_runtime import build_packet


@pytest.mark.parametrize('width,touch',[(1280,False),(390,True)])
def test_app_frame_walks_both_ways_and_rereads_after_completion(width,touch,tmp_path):
    packet=build_packet()
    for event in packet['timeline']: event.update(life_stage='childhood',age={'minimum':8,'maximum':8})
    source=confirmed_source(packet)
    plan=dict(version=1,blend=180,segments=[dict(id='garden',scene='garden',title='Garden',start=0,end=1300)],
        stops=[dict(chapter='C1',segment='garden',x=700)])
    game=dict(novel_game=validate_bundle(dict(version=1,source=runner.public_source(source),plan=journey.bind_journey(plan,source),
        css='body{color:#243d33}',scene_bindings={'garden':'garden'}),[packet['scene_pool']['scenes'][0]]))
    root=Path(__file__).parents[1]
    (tmp_path/'game-package.json').write_text(json.dumps(dict(game=game)))
    server=subprocess.Popen([sys.executable,'-B',str(root/'experiments/novel-to-game/serve.py'),
        '--application','--no-metadata','--output',str(tmp_path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    info=json.loads(server.stdout.readline())
    errors=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            context=browser.new_context(viewport={'width':width,'height':1000},has_touch=touch,is_mobile=touch)
            page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(info['url'])
            frame=page.frame_locator('iframe')
            expect(frame.locator('#game')).to_have_attribute('data-x','80')
            assert page.locator('iframe').get_attribute('sandbox')=='allow-scripts'
            frame.locator('#game').focus()
            page.keyboard.down('ArrowRight')
            deadline=time.monotonic()+5
            while int(frame.locator('#game').get_attribute('data-x'))<680 and time.monotonic()<deadline: page.wait_for_timeout(20)
            page.keyboard.up('ArrowRight')
            expect(frame.locator('#interact')).to_be_enabled()
            frame.locator('#interact').click();expect(frame.locator('#passage')).to_have_text('My father tended the garden.')
            frame.locator('#continue').click()
            expect(frame.locator('#game')).to_have_attribute('data-phase','complete')
            expect(frame.locator('#interact')).to_have_text('Read again');expect(frame.locator('#interact')).to_be_enabled()
            frame.locator('#interact').click();expect(frame.locator('#memory-dialog')).to_be_visible()
            page.keyboard.press('Escape');expect(frame.locator('#memory-dialog')).not_to_be_visible()
            expect(page.locator('iframe')).to_be_visible()
            before=int(frame.locator('#game').get_attribute('data-x'))
            frame.locator('#game').focus();page.keyboard.down('ArrowLeft');page.wait_for_timeout(350);page.keyboard.up('ArrowLeft')
            assert int(frame.locator('#game').get_attribute('data-x'))<before-80
            expect(frame.locator('#game')).to_have_attribute('data-visited','1')
            assert frame.locator('#player').evaluate('el=>getComputedStyle(el,"::before").backgroundImage').startswith('url("http://127.0.0.1:')
            page.screenshot(path=str(tmp_path/'app-frame.png'))
            assert not errors
            context.close();browser.close()
    finally:
        server.terminate();server.wait(timeout=10);server.stdout.close();server.stderr.close()
