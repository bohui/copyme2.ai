"""Worker-built views must actually paint a shared generated background."""
import asyncio
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import time

from PIL import Image
from playwright.sync_api import sync_playwright,expect
import pytest

from apps.api import novel_game_art as art
from apps.api.novel_game import confirmed_source,runner
from apps.api.novel_game_bundle import journey,scene_library
from test_novel_game_art import png,broken_pixel_png,short_scanline_png,fence
from test_story_game_runtime import build_packet


@pytest.fixture
def worker_game(tmp_path,fence):
    packet=build_packet();packet['selection']['scene_ids']=['scene-1','scene-2']
    source=confirmed_source(packet)
    plan=dict(version=1,blend=180,segments=[
        dict(id='first',scene='observatory',title='Observatory',start=0,end=640),
        dict(id='later',scene='observatory-later',title='Observatory later',start=640,end=1280)],
        stops=[dict(chapter='C1',segment='first',x=420),dict(chapter='C2',segment='later',x=1060)])
    art.assets.write_json(tmp_path,'design/JOURNEY_PLAN.json',plan)
    async def generate(*_):return png(),{}
    asyncio.run(art.prepare_backgrounds(tmp_path,{'observatory':{'prompt':'Observatory.'},
        'observatory-later':{'prompt':'Observatory.'}},scene_library(),fence,generator=generate))
    art.assets.write_json(tmp_path,'source/input.json',dict(input=source))
    journey.materialise(tmp_path,source,runner.public_source(source),require_art=True)
    return tmp_path


@pytest.mark.parametrize('width',[1280,390])
def test_worker_build_paints_the_same_generated_background_in_both_scenes(worker_game,width):
    tmp_path=worker_game
    root=Path(__file__).parents[1]
    server=subprocess.Popen([sys.executable,'-B',str(root/'experiments/novel-to-game/serve.py'),
        '--no-metadata','--output',str(tmp_path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    info=json.loads(server.stdout.readline())
    try:
        with sync_playwright() as runtime:
            browser=runtime.chromium.launch(headless=True);page=browser.new_page(viewport={'width':width,'height':1000})
            page.goto(info['url']);expect(page.locator('#game')).to_have_attribute('data-x','80')
            for target in [420,1060]:
                page.locator('#game').focus();page.keyboard.down('ArrowRight');deadline=time.monotonic()+5
                try:
                    while int(page.locator('#game').get_attribute('data-x'))<target-20 and time.monotonic()<deadline:
                        page.wait_for_timeout(20)
                finally:page.keyboard.up('ArrowRight')
                assert abs(int(page.locator('#game').get_attribute('data-x'))-target)<=65, 'Reach the memory before checking its pixels'
                pixels=Image.open(BytesIO(page.locator('#viewport').screenshot())).convert('RGB')
                assert pixels.getpixel((50,40))==(81,119,105), f'The shared background must paint at x={target}, not turn blank'
            browser.close()
    finally:
        server.terminate();server.wait(timeout=10);server.stdout.close();server.stderr.close()


@pytest.mark.parametrize('damage,phone',[('pixel_stream',False),('short_scanlines',False),('cell_mapping',True)])
def test_verifier_replaces_pass_with_render_failure_for_broken_scene_art(worker_game,damage,phone):
    catalog_path=worker_game/'build/asset-catalog.json';catalog=json.loads(catalog_path.read_text())
    catalog['scenes'][0]['cells']={'observatory':0,'observatory-later':0}
    catalog_path.write_text(json.dumps(catalog))
    source=json.loads((worker_game/'source/input.json').read_text())['input']
    journey.materialise(worker_game,source,runner.public_source(source),require_art=True)
    command=[sys.executable,'-B',str(Path(__file__).parents[1]/'experiments/novel-to-game/verify.py'),
        '--output',str(worker_game),'--stage','production']
    if phone:command.append('--phone')
    first=subprocess.run(command,capture_output=True,text=True,timeout=60)
    assert first.returncode==0,first.stdout+first.stderr
    if damage in ('pixel_stream','short_scanlines'):
        (worker_game/'build/app'/catalog['scenes'][0]['url']).write_bytes(
            broken_pixel_png() if damage=='pixel_stream' else short_scanline_png())
    else:
        del catalog['scenes'][0]['cells'];catalog_path.write_text(json.dumps(catalog))
        journey.materialise(worker_game,source,runner.public_source(source),require_art=True)
    failed=subprocess.run(command,capture_output=True,text=True,timeout=60)
    result=json.loads((worker_game/('qa/phone/verification.json' if phone else 'qa/verification.json')).read_text())
    assert failed.returncode==1 and result['status']=='FAIL', 'Broken scene art must not retain or produce PASS'
    assert result['checks']['render']=='FAIL'
