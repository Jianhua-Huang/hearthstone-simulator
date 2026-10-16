"""Five real native Undead faces through normal player commands; no lab cards."""
import json
from examples.card_qualified_next import session
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.cards.undead_native_cards import ASCENDANT,TOWER,SPECTER,LIFERENDER,SPIRIT,GHOUL
from hs_sim.engine import Keyword,PlayerSetup,Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION


def setup(hand,*,board=(),enemy=(),seed=4776):
    return Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=('CORE_CS2_182',)*8,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
        PlayerSetup('HERO_08',board=enemy,deck=('CORE_CS2_182',)*8,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=seed)


def power_hero(g,submit):
    def choose(listing):
        own=listing['observation']['players'][0]
        return next(a for a in listing['actions']if a['type']=='use_hero_power'and a['power']==own['hero_power']['ref']and a['target']==own['hero']['ref'])
    submit(1,choose)


def main():
    def native(g,play,end,submit):
        play(1,ASCENDANT);play(1,TOWER);play(1,'CORE_CS2_029',target_card=TOWER)
        s=g.state;assert sum(s.entities[i].card_id==GHOUL for i in s.players[1].board)==2
        power_hero(g,submit);play(1,LIFERENDER,target_card='CORE_CS2_182');assert not g.state.players[2].board
        end(1);s=g.state;assert all(s.entities[i].card_id!=GHOUL for i in s.players[1].board)
    first=session(setup((ASCENDANT,TOWER,'CORE_CS2_029',LIFERENDER),enemy=('CORE_CS2_182',)),native)
    def restriction(g,play,end,submit):
        play(1,SPECTER);end(1);end(2)
        listing=g.for_player(1).legal_actions();ref=listing['observation']['players'][0]['board'][0]['ref']
        assert not any(a['type']=='attack'and a.get('attacker')==ref for a in listing['actions'])
        play(1,'EX1_332',target_card=SPECTER)
        submit(1,lambda listing:next(a for a in listing['actions']if a['type']=='attack'and a['defender']==listing['observation']['players'][1]['hero']['ref']))
        assert g.state.entities[g.state.players[2].hero_id].health==28
    second=session(setup((SPECTER,'EX1_332'),seed=4777),restriction)
    def excess(g,play,end,submit):
        power_hero(g,submit);play(1,'CORE_CS2_029',target_card=SPIRIT)
        s=g.state;e=s.entities[s.players[1].board[0]];assert e.card_id==SPIRIT and e.health==1 and Keyword.REBORN not in e.keywords
        assert s.entities[s.players[1].hero_id].health==30 and s.entities[s.players[2].hero_id].health==28
        play(1,'CORE_CS2_029',target_card=SPIRIT);assert not g.state.players[1].board
        assert g.state.entities[g.state.players[2].hero_id].health==25
    third=session(setup(('CORE_CS2_029','CORE_CS2_029'),board=(SPIRIT,),seed=4778),excess)
    def inactive(g,play,end,submit):
        play(1,LIFERENDER);s=g.state;assert s.entities[s.players[2].board[0]].health==5
    fourth=session(setup((LIFERENDER,),enemy=('CORE_CS2_182',),seed=4779),inactive)
    scenarios=[first,second,third,fourth]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=5,existing_fixed_dependencies=1,lab_fixture_definitions=0,scenarios=scenarios,
        actions=sum(x['actions']for x in scenarios),checkpoints=sum(len(x['checkpoints'])for x in scenarios),formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(15,19)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
