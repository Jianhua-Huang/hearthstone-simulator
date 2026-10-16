"""Nine real roots via player commands, with independent portable checkpoints."""
import json
from examples.card_qualified_next import session
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.cards.public_effect_consumer_cards import GEOMANCER,LANCER,AMARA,STAFF,DOUBLE,ARACHNATHID,SUPPLIER,GALVADON,CAUSALITY
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.model import Keyword
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION

YETI='CORE_CS2_182';FIREBALL='CORE_CS2_029';BOLT='CORE_CS2_024'


def setup(hand,*,board=(),enemy=(),deck=(YETI,)*10,seed=5080):
    return Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
        PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*10,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=seed)


def attack(submit,cid,*,hero=False):
    def choose(listing):
        own,enemy=listing['observation']['players'];source=next(c['ref']for c in own['board']if c['card_id']==cid)
        target=enemy['hero']['ref']if hero else enemy['board'][0]['ref']
        return next(a for a in listing['actions']if a['type']=='attack'and a['attacker']==source and a['defender']==target)
    submit(1,choose)


def main():
    def prepare(g,play,end,submit):
        def choose(listing):
            card=next(c['ref']for c in listing['observation']['players'][0]['hand']if c['card_id']==GEOMANCER)
            return next(a for a in listing['actions']if a['type']=='use_hand_action'and a['card']==card and a['action_id']=='prepare')
        submit(1,choose);end(1);end(2);play(1,GEOMANCER);play(1,FIREBALL,target_player=2)
        assert g.state.entities[g.state.players[2].hero_id].health==23
    first=session(setup((GEOMANCER,FIREBALL)),prepare)
    def enemy_aura(g,play,end,submit):
        play(1,LANCER);assert Keyword.TAUNT in g.state.entities[g.state.players[2].board[0]].keywords
    second=session(setup((LANCER,),enemy=(YETI,),seed=5081),enemy_aura)
    def health(g,play,end,submit):
        play(1,AMARA);hero=g.state.entities[g.state.players[1].hero_id];assert(hero.health,hero.max_health)==(40,40)
    third=session(setup((AMARA,),seed=5082),health)
    def weapon(g,play,end,submit):
        play(1,STAFF);play(1,'EDR_253');assert not g.state.players[1].board and not g.state.players[2].board
    fourth=session(setup((STAFF,'EDR_253'),board=(YETI,),enemy=(YETI,),seed=5083),weapon)
    def combo(g,play,end,submit):
        play(1,FIREBALL,target_player=2);play(1,DOUBLE)
        assert len(g.state.players[1].board)==2 and len(g.state.combo_history)==1
    fifth=session(setup((FIREBALL,DOUBLE),seed=5084),combo)
    def poison(g,play,end,submit):
        play(1,ARACHNATHID);attack(submit,ARACHNATHID);assert not g.state.players[2].board
    sixth=session(setup((ARACHNATHID,),enemy=(YETI,),seed=5085),poison)
    def draw(g,play,end,submit):
        play(1,SUPPLIER);end(1);end(2);before=len(g.state.draw_history);attack(submit,SUPPLIER,hero=True)
        assert len(g.state.draw_history)==before+1
    seventh=session(setup((SUPPLIER,),seed=5086),draw)
    def bonus(g,play,end,submit):
        play(1,GALVADON,target_card=YETI);source=g.state.entities[g.state.players[1].board[0]]
        assert len(source.keywords)==3 and Keyword.RUSH not in source.keywords
    eighth=session(setup((GALVADON,),board=(YETI,),seed=5087),bonus)
    def reverse(g,play,end,submit):
        before=g.state.players[1].deck;play(1,CAUSALITY);assert g.state.players[1].deck==list(reversed(before))
    ninth=session(setup((CAUSALITY,),deck=(YETI,BOLT,FIREBALL),seed=5088),reverse)
    cases=[first,second,third,fourth,fifth,sixth,seventh,eighth,ninth]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=9,fixed_dependencies=0,lab_fixture_definitions=0,scenarios=cases,
        actions=sum(case['actions']for case in cases),checkpoints=sum(len(case['checkpoints'])for case in cases),formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(19,28)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
