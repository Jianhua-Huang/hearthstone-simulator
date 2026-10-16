"""Actual Goldpetal -> Imbue power -> Portal draw, through player commands."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario,GenerationContext
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from .card_qualified_next import session


def main():
    setup=Scenario((PlayerSetup('HERO_04',hand=('CORE_DAL_575','EDR_451','CORE_CS2_023'),
        hero_power_card_id='HERO_04bp',mana=20,max_mana=20,mana_cap=20),PlayerSetup('HERO_08')),
        seed=4262,generation_context=GenerationContext('local-2026-09-23','experimental'))
    result_details={}
    def run(g,play,end,submit):
        play(1,'CORE_DAL_575');play(1,'EDR_451')
        assert g.state.entities[g.state.players[1].hero_power_id].card_id=='EDR_445p'
        submit(1,lambda listing:next(a for a in listing['actions']if a['type']=='use_hero_power'))
        assert [g.state.entities[i].card_id for i in g.state.players[1].deck]==['EDR_445pt3']*2
        play(1,'CORE_CS2_023');roots=g.state.card_summon_history
        assert len(roots)==2 and [r.plan.total for r in roots]==[2,2]
        assert len(g.state.players[1].board)==6
        assert all(r.request.cause.source.card_id=='EDR_445pt3'and r.request.cause.origin=='spell_cast'for r in roots)
        result_details.update(portal_roots=2,quantities=[2,2],dragons=4,standard_root='EDR_451')
    scene=session(setup,run)
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        actions=scene['actions'],checkpoints=len(scene['checkpoints']),scenario=scene,lab_fixture_definitions=0,
        generation_context_mode='experimental',formal_pool_complete=False,cn_calibrated=False,**result_details)
    assert (result['actions'],result['checkpoints'])==(4,5)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
