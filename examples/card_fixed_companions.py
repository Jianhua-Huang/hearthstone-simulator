"""Complete named family through actual player spell/minion/attack commands."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from .card_qualified_next import session

ANIMAL='CORE_NEW1_031';CALL='CORE_OG_211';HAL='CORE_TRL_900';LYNX='TRL_348t';YETI='CORE_CS2_182'
ORDER=('NEW1_034','NEW1_033','NEW1_032')


def setup(hand,enemy=()):
    return Scenario((PlayerSetup('HERO_08',hand=hand,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
        PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=436)


def attack(send,source,*,hero=False):
    def choose(listing):
        ps={p['id']:p for p in listing['observation']['players']}
        source_ref=next(c['ref']for c in ps[1]['board']if c['card_id']==source)
        target=ps[2]['hero']['ref']if hero else ps[2]['board'][0]['ref']
        return next(a for a in listing['actions']if a['type']=='attack'and a['attacker']==source_ref and a['defender']==target)
    send(1,choose)


def main():
    def animal(g,play,end,send):
        play(1,ANIMAL);assert len(g.state.players[1].board)==1
        assert g.state.entities[g.state.players[1].board[0]].card_id in ORDER
    first=session(setup((ANIMAL,)),animal)
    def call(g,play,end,send):
        play(1,CALL);assert[g.state.entities[i].card_id for i in g.state.players[1].board]==list(ORDER)
        assert[g.state.entities[i].attack for i in g.state.players[1].board]==[5,2,5]
        attack(send,ORDER[0],hero=True);assert g.state.entities[g.state.players[2].hero_id].health==25
    second=session(setup((CALL,)),call)
    def hal(g,play,end,send):
        play(1,HAL);assert[g.state.entities[i].card_id for i in g.state.players[1].hand]==[LYNX]*10
        play(1,LYNX);attack(send,LYNX);assert g.state.entities[g.state.players[2].board[0]].health==4
        attack(send,HAL);assert not g.state.players[2].board and not g.state.players[1].board
    third=session(setup((HAL,),(YETI,)),hal);scenes=[first,second,third]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        new_roots=3,new_dependencies=4,lab_fixture_definitions=0,actions=sum(s['actions']for s in scenes),
        checkpoints=sum(len(s['checkpoints'])for s in scenes),scenarios=scenes,formal_pool_complete=False,cn_calibrated=False,
        limit='Short decks, explicit mana and cross-class scenarios are internal experiments.')
    assert(result['actions'],result['checkpoints'])==(7,10)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
