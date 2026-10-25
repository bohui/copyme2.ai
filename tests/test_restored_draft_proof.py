"""The review must admit the host-restored candidate, including after resume."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api.canonical_composer import composer_request,restore_unchanged_sections
from apps.api.lifetime_memory_lane_engine import lane_artifact_digest
from apps.api.memoir_preview import compose_candidate,skill_operation
from controlled_composer_review import controlled_review
from test_canonical_composer_provenance import controlled_draft
from test_composer_review_regressions import unchanged_job


@pytest.mark.parametrize('resumed',[False,True])
def test_restored_candidate_has_current_page_proof_before_review(monkeypatch,resumed):
    async def scenario():
        request=composer_request(unchanged_job())
        plan=await skill_operation('plan',request)
        prior=controlled_draft({'request':request,'plan':plan},'I grew up in Chengde.','Childhood')
        request['context']['preserved_sections']=[dict(chapter_id='home-chapter',event_ids=['childhood'],
            block=deepcopy(prior['chapters'][0]['blocks'][0]))]
        plan=await skill_operation('plan',request)
        raw=controlled_draft({'request':request,'plan':plan},'Chengde was where I grew up.','Childhood')
        original_digest=lane_artifact_digest('draft',raw)
        proofs={original_digest};phases=[]
        page=dict(lane_id='owned-lane',token='current-token',page_number=0,page_digest='a'*64)
        class Broker:
            async def rpc(self,name,**payload):
                assert name=='record_lifetime_lane_output'
                assert payload==dict(p_lane_id=page['lane_id'],p_token=page['token'],p_page_number=0,
                    p_phase='draft',p_digest=payload['p_digest'],p_page_digest=page['page_digest'])
                proofs.add(payload['p_digest'])
                return True
        async def provider(runtime,storage,project,locale,phase,packet):
            phases.append(phase)
            if phase=='draft':return deepcopy(raw)
            assert phase=='review'
            candidate=packet['candidate']
            assert candidate['chapters'][0]['blocks'][0]['text']=='I grew up in Chengde.'
            assert lane_artifact_digest('draft',candidate) in proofs
            tampered=deepcopy(candidate);tampered['chapters'][0]['blocks'][0]['text']='Unapproved replacement.'
            assert lane_artifact_digest('draft',tampered) not in proofs
            return controlled_review(packet)
        async def progress(phase):pass
        monkeypatch.setattr('apps.api.memoir_preview.composer_call',provider)
        checkpoint={'request':deepcopy(request),'draft':restore_unchanged_sections(request,deepcopy(raw))} if resumed else {}
        runtime=SimpleNamespace(lifetime_bounded=True,lifetime_page=page,lane_broker=Broker())
        result=await compose_candidate(request,runtime,SimpleNamespace(),'project','en-AU',checkpoint=checkpoint,progress=progress)
        assert result['status']=='ready'
        assert phases==(['review'] if resumed else ['draft','review'])
        assert original_digest in proofs and len(proofs)==2
    asyncio.run(scenario())
