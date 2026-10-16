"""Real weapon Lifesteal, opponent-turn Attack and native Taelan draw."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from .card_qualified_next import session

BLADE='CORE_BT_921';ASH='RLK_067';TAR='CORE_UNG_928';TAELAN='CS3_024';YETI='CORE_CS2_182';BLACK='CORE_YOP_034';FIRE='CORE_CS2_029'


def setup(hand,enemy_hand=(),deck=(YETI,)*8):
    return Scenario((PlayerSetup('HERO_08',hand=hand,deck=deck,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
        PlayerSetup('HERO_08',hand=enemy_hand,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=435)


def attack(send):
    def choose(listing):
        ps={p['id']:p for p in listing['observation']['players']}
        return next(a for a in listing['actions']if a['type']=='attack'and a['attacker']==ps[1]['hero']['ref']and a['defender']==ps[2]['hero']['ref'])
    send(1,choose)


def main():
    scenes=[]
    for cid,amount in((BLADE,2),(ASH,5)):
        def weapon(g,play,end,send,cid=cid,amount=amount):
            play(1,FIRE,target_player=1);play(1,cid);wid=g.state.players[1].weapon_id;attack(send)
            assert g.state.entities[g.state.players[1].hero_id].health==24+amount
            assert g.state.entities[wid].durability==1;end(1);end(2);attack(send)
            assert g.state.players[1].weapon_id is None
            assert g.state.entities[g.state.players[1].hero_id].health==min(30,24+2*amount)
        scenes.append(session(setup((FIRE,cid)),weapon))
    def tar(g,play,end,send):
        play(1,TAR);eid=g.state.players[1].board[0];assert g.state.entities[eid].attack==1
        end(1);assert g.state.entities[eid].attack==3;play(2,FIRE,target_card=TAR)
        assert g.state.death_history[-1].attack==3
    scenes.append(session(setup((TAR,),(FIRE,)),tar))
    def taelan(g,play,end,send):
        original=set(g.state.players[1].deck);play(1,TAELAN);end(1)
        play(2,FIRE,target_card=TAELAN);play(2,FIRE,target_card=TAELAN)
        record=g.state.draw_history[-1];assert record.player_id==1 and record.card_id==BLACK and record.entity_id in original
        assert record.entity_id in g.state.players[1].hand
    scenes.append(session(setup((TAELAN,),(FIRE,FIRE),(YETI,BLACK,TAR)),taelan))
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        new_roots=4,lab_fixture_definitions=0,actions=sum(s['actions']for s in scenes),
        checkpoints=sum(len(s['checkpoints'])for s in scenes),scenarios=scenes,formal_pool_complete=False,cn_calibrated=False,
        limit='Explicit mana, cross-class scenarios and short decks are internal experiments.')
    assert(result['actions'],result['checkpoints'])==(19,23)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
