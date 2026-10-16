"""Four real Dragon roots via player DTOs, including an actual Rewind retry."""
import json
from examples.card_qualified_next import session
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.cards.dragon_native_effect_cards import FLOWER,TURTLE,CRUMBLE,CONFLUX
from hs_sim.cards.stored_dark_gift_source import XAVIUS
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.model import Zone
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION

YETI='CORE_CS2_182';LOC='CORE_REV_990';AXE='TLC_478'


def setup(hand,*,board=(),enemy=(),enemy_weapon=None,deck=(YETI,)*8,seed=85):
    return Scenario((
        PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
        PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,weapon_card_id=enemy_weapon,
                    mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
    ),seed=seed)


def select(submit,label):
    def choose(listing):
        option=next(o for o in listing['observation']['pending_choice']['options']if label in o['label'])
        return next(a for a in listing['actions']if a['type']=='select_choice'and a['options']==[option['ref']])
    submit(1,choose)


def main():
    def flower(g,play,end,submit):
        friend=g.state.players[1].board[0];play(1,FLOWER);end(1)
        assert(g.state.entities[friend].attack,g.state.entities[friend].health)==(4,7)
        end(2);end(1);assert(g.state.entities[friend].attack,g.state.entities[friend].health)==(5,8)
    first=session(setup((FLOWER,),board=(TURTLE,)),flower)
    def turtle(g,play,end,submit):
        play(1,XAVIUS);select(submit,'衣甲厚实');play(1,TURTLE)
        hero=g.state.players[1].hero_id;assert(g.state.entities[hero].attack,g.state.entities[hero].armor)==(3,6)
        def attack(listing):
            players={p['id']:p for p in listing['observation']['players']}
            return next(a for a in listing['actions']if a['type']=='attack'and a['attacker']==players[1]['hero']['ref']and a['defender']==players[2]['hero']['ref'])
        submit(1,attack);assert g.state.entities[g.state.players[2].hero_id].health==27
        end(1);assert(g.state.entities[hero].attack,g.state.entities[hero].armor)==(0,6)
    second=session(setup((XAVIUS,TURTLE),deck=(YETI,),seed=4),turtle)
    def crumble(g,play,end,submit):
        old=tuple(g.state.players[2].board)+(g.state.players[2].weapon_id,)
        play(1,CRUMBLE);assert all(g.state.entities[i].zone==Zone.GRAVEYARD for i in old)
    third=session(setup((CRUMBLE,),enemy=(YETI,LOC),enemy_weapon=AXE),crumble)
    def conflux(g,play,end,submit):
        victim=g.state.players[2].board[0];play(1,CONFLUX)
        assert g.state.entities[victim].zone==Zone.GRAVEYARD and g.state.pending_choice is not None
        select(submit,'回溯并重试')
        assert g.state.entities[victim].zone==Zone.BOARD and g.state.entities[victim].health==5
        assert g.state.entities[g.state.players[2].hero_id].health==23 and g.state.players[1].mana==33
    fourth=session(setup((CONFLUX,),enemy=(YETI,),seed=7),conflux)
    cases=[first,second,third,fourth]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=4,fixed_dependencies=0,existing_prerequisite_source=XAVIUS,lab_fixture_definitions=0,scenarios=cases,
        actions=sum(c['actions']for c in cases),checkpoints=sum(len(c['checkpoints'])for c in cases),formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(12,16)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
