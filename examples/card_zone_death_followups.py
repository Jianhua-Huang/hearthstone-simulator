"""Real matching draws, simultaneous top-deck destruction and enemy hand costs."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session

YETI='CORE_CS2_182';DRAGON='EDR_890';OTHER='CORE_AT_123'


def setup(hand,deck=(),enemy_hand=(),seed=382):
    return Scenario((PlayerSetup('HERO_08',hand=hand,deck=deck,mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',hand=enemy_hand,deck=(YETI,)*5,mana=40,max_mana=40,mana_cap=40)),seed=seed)


def main():
    def dragons(g,play,end,submit):
        originals=tuple(g.state.players[1].deck)
        play(1,'EDR_572');play(1,'CORE_EX1_309',target_card='EDR_572')
        for eid in g.state.players[1].hand:
            entity=g.state.entities[eid];assert eid in originals
            assert quote_cost(g.state,g.registry,entity).amount==g.registry.card(entity.card_id).cost-1
        held=next(e for e in g.state.players[1].hand if g.state.entities[e].card_id==DRAGON)
        price=quote_cost(g.state,g.registry,g.state.entities[held]).amount;mana=g.state.players[1].mana
        play(1,DRAGON);assert held in g.state.players[1].board and g.state.players[1].mana==mana-price
    first=session(setup(('EDR_572','CORE_EX1_309'),(YETI,DRAGON,OTHER)),dragons)

    def destroy(g,play,end,submit):
        original=tuple(g.state.players[1].deck)
        play(1,'TLC_621');play(1,'CORE_EX1_309',target_card='TLC_621')
        assert g.state.players[1].deck==list(original[3:]) and not g.state.draw_history
        assert [x.card_id for x in g.state.death_history]==['TLC_621']
        assert g.state.players[1].weapon_id is None
        play(1,'CORE_CS2_023');assert g.state.players[1].hand==list(original[3:])
        assert g.state.entities[g.state.players[1].hero_id].health==30
    second=session(setup(('TLC_621','CORE_EX1_309','CORE_CS2_023'),(YETI,'EDR_572','END_002','CORE_CS2_029',YETI),seed=383),destroy)

    def enemy_cost(g,play,end,submit):
        held=g.state.players[2].hand[0]
        play(1,'TLC_244');play(1,'CORE_EX1_309',target_card='TLC_244')
        assert quote_cost(g.state,g.registry,g.state.entities[held]).amount==2
        end(1);mana=g.state.players[2].mana;play(2,YETI)
        assert held in g.state.players[2].board and g.state.players[2].mana==mana-2
    third=session(setup(('TLC_244','CORE_EX1_309'),enemy_hand=(YETI,),seed=384),enemy_cost)
    scenarios=[first,second,third];result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,
        snapshot_schema=SNAPSHOT_SCHEMA_VERSION,roots=3,new_dependencies=0,lab_fixture_definitions=0,
        actions=sum(x['actions']for x in scenarios),checkpoints=sum(len(x['checkpoints'])for x in scenarios),
        scenarios=scenarios,formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(10,13)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
