"""Actual held-turn/accepted-spell cards, forms and player-only checkpoints."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import CardType,PlayerSetup,Scenario,Zone
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session

FOREST='EDR_843';BOTH='EDR_843t1';GROVE='FIR_911';FROST='JAIL_803';ELEMENTAL='JAIL_803t'
YETI='CORE_CS2_182';FIRE='CORE_CS2_029';INNERVATE='CORE_EX1_169'


def setup(hand,deck=(YETI,)*12,seed=961):
    return Scenario((PlayerSetup('HERO_08',hand=hand,deck=deck,mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',deck=(YETI,)*12,mana=40,max_mana=40,mana_cap=40)),seed=seed)


def main():
    def branch(g,play,end,submit):
        source=g.state.players[1].hand[0]
        submit(1,lambda x:next(a for a in x['actions']if a['type']=='play_card'and a.get('branch')=='EDR_843a'))
        rows=[d for d in g.state.draw_history if d.source_id==source]
        assert len(rows)==1 and rows[0].card_id==FIRE and g.state.players[1].mana==38
    a=session(setup((FOREST,),deck=(YETI,FIRE)),branch)
    def forest(g,play,end,submit):
        source=g.state.players[1].hand[0]
        for _ in range(3):end(1);end(2)
        assert g.state.entities[source].card_id==BOTH;play(1,BOTH)
        rows=[d for d in g.state.draw_history if d.source_id==source]
        assert len(rows)==2 and [g.registry.card(d.card_id).kind for d in rows]==[CardType.SPELL,CardType.MINION]
    b=session(setup((FOREST,),deck=(YETI,)*8+(FIRE,),seed=962),forest)
    def grove(g,play,end,submit):
        source=g.state.players[1].hand[0]
        for _ in range(2):end(1);end(2)
        play(1,GROVE);assert len([d for d in g.state.draw_history if d.source_id==source])==3
        assert not g.state.discard_history
    c=session(setup((GROVE,),seed=963),grove)
    def expire(g,play,end,submit):
        source=g.state.players[1].hand[0]
        end(1);end(2);end(1);end(2);end(1);s=g.state
        assert s.entities[source].zone==Zone.GRAVEYARD and len(s.discard_history)==1
        assert s.discard_history[0].entity_id==source and not s.death_history
    d=session(setup((GROVE,),seed=964),expire)
    def frost(g,play,end,submit):
        source=g.state.players[1].hand[0];play(1,FROST,target_player=2);s=g.state
        assert s.entities[s.players[2].hero_id].frozen and len([d for d in s.draw_history if d.source_id==source])==2
    e=session(setup((FROST,),seed=965),frost)
    def elemental(g,play,end,submit):
        source=g.state.players[1].hand[0]
        for _ in range(3):play(1,INNERVATE)
        assert g.state.entities[source].card_id==ELEMENTAL;play(1,ELEMENTAL,target_player=2);s=g.state
        assert s.entities[source].zone==Zone.BOARD and(s.entities[source].attack,s.entities[source].health)==(5,5)
        assert s.entities[s.players[2].hero_id].frozen and len([d for d in s.draw_history if d.source_id==source])==2
    f=session(setup((FROST,INNERVATE,INNERVATE,INNERVATE),seed=966),elemental)
    scenarios=[a,b,c,d,e,f];result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,
        snapshot_schema=SNAPSHOT_SCHEMA_VERSION,roots=3,new_dependencies=4,choice_only_dependencies=2,lab_fixture_definitions=0,
        actions=sum(x['actions']for x in scenarios),checkpoints=sum(len(x['checkpoints'])for x in scenarios),scenarios=scenarios,
        formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(23,29)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
