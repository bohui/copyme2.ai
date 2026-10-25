"""Run the real consent dialog and recorder boundary with controlled API/media."""
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1] / 'apps/web'


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for locale in ['en-AU','zh-CN']:
            page = browser.new_page()
            errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            def serve(route):
                path=urlsplit(route.request.url).path
                if path=='/':return route.fulfill(body=f'<html lang="{locale}"><body></body></html>',content_type='text/html')
                file=ROOT/path.lstrip('/')
                return route.fulfill(body=file.read_text(),content_type='application/json' if file.suffix=='.json' else 'text/javascript')
            page.route('http://consent.test/**',serve)
            page.goto('http://consent.test/')
            page.wait_for_load_state('networkidle')
            page.evaluate('''async () => {
              const {createRecordingConsent}=await import('/client/memoir/recording-consent.mjs');
              const {createConversationAudio}=await import('/client/memoir/conversation-audio.mjs');
              window.owner='first'; window.captures=0; window.links=0; window.writes=[];
              window.consentStatus={enabled:true,recoverable_identity:true,consented:false,revision:0,policy_version:'original-recordings-v1'};
              const scope=()=>({owner}); const current=s=>s.owner===owner;
              const api=async(path,options)=>{
                if(options?.method==='PUT'){
                  const body=JSON.parse(options.body); writes.push(body);
                  consentStatus={...consentStatus,consented:body.action==='grant',revision:consentStatus.revision+1};
                }
                return {...consentStatus};
              };
              window.consent=createRecordingConsent({storyApi:api,captureProjectScope:scope,isCurrentProjectScope:current,
                openIdentity:()=>links++,toast(){}});
              Object.defineProperty(navigator,'mediaDevices',{value:{getUserMedia:async()=>{captures++;throw new Error('fixture');}}});
              window.MediaRecorder=class {};
              window.audioState={voiceMode:false,dictationStatus:'off',dictationId:0};
              window.audio=createConversationAudio({captureProjectScope:scope,isCurrentProjectScope:current,
                state:audioState,storyApi:api,toast(){},render(){},
                ensureRecordingConsent:consent.ensure});
            }''')
            page.evaluate('window.recordResult=audio.startAudioRecorder(); void 0')
            dialog=page.locator('dialog[open]')
            expect(dialog).to_be_visible()
            assert page.evaluate('captures')==0
            dialog.locator('[data-close]').click()
            expect(dialog).to_have_count(0)
            page.evaluate('recordResult')
            assert page.evaluate('writes.length')==0 and page.evaluate('captures')==0
            page.evaluate('window.recordResult=audio.startAudioRecorder(); void 0')
            expect(dialog).to_be_visible()
            dialog.locator('[name=retain]').check()
            dialog.locator('[data-save]').click()
            assert page.evaluate('writes.length')==0  # Both separate purposes are required.
            dialog.locator('[name=processing]').check()
            dialog.locator('[data-save]').click()
            expect(dialog).to_have_count(0)
            page.evaluate('recordResult')
            page.wait_for_function('captures===1 && audioState.dictationStatus==="off"')
            assert page.evaluate('writes[0].retain_originals && writes[0].ai_processing')
            assert page.evaluate('writes[0].locale')==locale
            page.evaluate('window.reviewResult=consent.open(); void 0')
            expect(dialog).to_be_visible()
            dialog.locator('[data-revoke]').click()
            expect(dialog).to_have_count(0)
            page.evaluate('reviewResult')
            assert page.evaluate('consentStatus.consented') is False
            page.evaluate('window.recordResult=audio.startAudioRecorder(); void 0')
            expect(dialog).to_be_visible()
            page.evaluate("owner='second'")
            dialog.locator('[name=retain]').check()
            dialog.locator('[name=processing]').check()
            dialog.locator('[data-save]').click()
            expect(dialog).to_have_count(0)
            page.evaluate('recordResult')
            assert page.evaluate('captures')==1 and page.evaluate('writes.length')==2
            page.evaluate('consentStatus.recoverable_identity=false; void audio.startAudioRecorder()')
            page.wait_for_function('links===1')
            assert page.evaluate('captures')==1
            assert not errors,errors
            page.close()
        browser.close()
    print('Consent dialog: English/Chinese opt-in, cancellation, withdrawal, identity and account-switch checks passed')


if __name__=='__main__':main()
