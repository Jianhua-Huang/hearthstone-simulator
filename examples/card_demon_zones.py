"""Real discard/burn Deathrattles, named bottom cards and previous-turn Kindred."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session

YETI='CORE_CS2_182';IMP='JAIL_398';STOOGE='JAIL_399';GRANDMA='JAIL_399t1';RAZIDIR='TLC_463'


def setup(hand,*,deck=(YETI,)*8,enemy_hand=(),enemy=(),seed=393):
    return Scenario((PlayerSetup('HERO_08',hand=hand,deck=deck,mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40)),seed=seed)


def main():
    def discard(g,play,end,submit):
        play(1,'CORE_EX1_310')
        assert not g.state.players[1].hand
        assert [x.capture.origin for x in g.state.deathrattle_history]==['stored']
        assert [g.state.entities[g.state.players[p].hero_id].health for p in(1,2)]==[27,27]
        assert not g.state.death_history
    first=session(setup(('CORE_EX1_310',IMP),enemy=(YETI,)),discard)

    def bottom(g,play,end,submit):
        play(1,STOOGE);play(1,'CORE_EX1_309',target_card=STOOGE)
        original=tuple(g.state.players[1].deck)
        assert len(original)==2 and all(g.state.entities[e].card_id==GRANDMA for e in original)
        play(1,'CORE_CS2_023');assert g.state.players[1].hand==list(original)
        play(1,GRANDMA);assert original[0]in g.state.players[1].board
    second=session(setup((STOOGE,'CORE_EX1_309','CORE_CS2_023'),deck=(),seed=394),bottom)

    def kindred(g,play,end,submit):
        play(1,'CORE_ICC_023');end(1);play(2,YETI);end(2);play(1,RAZIDIR)
        assert g.state.discard_history[-1].card_id==IMP and g.state.discard_history[-1].player_id==2
        assert g.state.deathrattle_history[-1].capture.origin=='stored'and g.state.deathrattle_history[-1].capture.player_id==2
        assert [g.state.entities[g.state.players[p].hero_id].health for p in(1,2)]==[27,27]
    third=session(setup(('CORE_ICC_023',RAZIDIR,YETI),enemy_hand=(IMP,),seed=395),kindred)

    def burn(g,play,end,submit):
        play(1,'CORE_CS2_023')
        assert g.state.draw_history[-1].outcome=='burned'
        assert [x.capture.origin for x in g.state.deathrattle_history]==['stored']
        assert [g.state.entities[g.state.players[p].hero_id].health for p in(1,2)]==[27,27]
    fourth=session(setup(('CORE_CS2_023',)+(YETI,)*9,deck=(YETI,IMP),seed=396),burn)
    def diabolus(g,play,end,submit):
        play(1,'CORE_ICC_023');end(1);end(2);play(1,'DINO_138')
        assert not g.state.players[2].board
        rows=[x.health_result for x in g.state.damage_history if x.health_result.source_card_id=='DINO_138']
        assert len(rows)==2 and all(x.modified_amount==6 and x.spell_bonus==0 for x in rows)
    fifth=session(setup(('CORE_ICC_023','DINO_138'),enemy=('EDR_978',),seed=397),diabolus)
    scenarios=[first,second,third,fourth,fifth];result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,
        snapshot_schema=SNAPSHOT_SCHEMA_VERSION,roots=4,new_dependencies=1,lab_fixture_definitions=0,
        actions=sum(x['actions']for x in scenarios),checkpoints=sum(len(x['checkpoints'])for x in scenarios),
        scenarios=scenarios,formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(15,20)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
