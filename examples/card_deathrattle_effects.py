"""Three real Deathrattle cards through ordinary player commands."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup, Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from .card_qualified_next import session

MASK='DINO_429';SERVANT='CORE_YOD_026';LAST='CATA_610'
YETI='CORE_CS2_182';SQUIRE='CORE_EX1_008';FISH='CORE_EX1_506';FIRE='CORE_CS2_029'


def setup(hand,board,enemy=()):
    return Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,
        mana=40,max_mana=40,mana_cap=40),PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8)),seed=440)


def main():
    def mask(g,play,end,submit):
        play(1,MASK,target_card=SQUIRE)
        play(1,FIRE,target_card=SQUIRE);assert len(g.state.players[2].board)==1
        play(1,FIRE,target_card=SQUIRE)
        assert not g.state.players[2].board and g.state.entities[g.state.players[1].board[0]].health==3
    first=session(setup((MASK,FIRE,FIRE),(YETI,),(SQUIRE,)),mask)
    def servant(g,play,end,submit):
        target=g.state.players[1].board[0];recipients=g.state.players[1].board[1:]
        before={i:g.state.entities[i].attack for i in recipients}
        play(1,FIRE,target_card=SERVANT)
        assert target not in g.state.players[1].board
        assert sum(g.state.entities[i].attack-before[i]for i in recipients)==2
    second=session(setup((FIRE,),(SERVANT,YETI,SQUIRE)),servant)
    def recruit(g,play,end,submit):
        held=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==FISH)
        play(1,LAST,target_card=SQUIRE)
        play(1,FIRE,target_card=SQUIRE);play(1,FIRE,target_card=SQUIRE)
        assert g.state.players[1].board==[held] and held not in g.state.players[1].hand
    third=session(setup((LAST,FIRE,FIRE,FISH),(SQUIRE,)),recruit)
    scenes=[first,second,third]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,
        snapshot_schema=SNAPSHOT_SCHEMA_VERSION,new_roots=3,new_dependencies=0,lab_fixture_definitions=0,
        actions=sum(x['actions']for x in scenes),checkpoints=sum(len(x['checkpoints'])for x in scenes),
        scenarios=scenes,formal_pool_complete=False,cn_calibrated=False,
        limit='Short decks, explicit mana and cross-class scenarios are internal experiments.')
    assert(result['actions'],result['checkpoints'])==(7,10)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
