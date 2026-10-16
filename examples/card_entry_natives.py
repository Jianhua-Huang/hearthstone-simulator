"""Three real roots and their actual dependencies through player DTOs."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.cards.entry_native_cards import FEL_BEASTS
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session

def setup(hand):
    return Scenario((PlayerSetup('HERO_08',hand=hand,deck=('CORE_CS2_182',)*8,mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*8)),seed=1051)

def main():
    def scout(g,play,end,submit):
        play(1,'CORE_NEW1_023');s=g.state
        assert any(s.entities[i].card_id=='CATA_552t'for i in s.players[1].hand)
        play(1,'CATA_552t',target_player=2);s=g.state;assert s.entities[s.players[2].hero_id].health==22
    a=session(setup(('CATA_552','CORE_NEW1_023')),scout)
    def parasite(g,play,end,submit):
        submit(1,lambda listing:next(a for a in listing['actions']if a['type']=='use_hand_action'and a['action_id']=='prepare'))
        end(1);end(2);before=g.state.players[1].mana;play(1,'JAIL_721');assert g.state.players[1].mana==before
        play(1,'TLC_479');play(1,'CORE_CS2_029',target_card='TLC_479');play(1,'CORE_CS2_029',target_card='TLC_479');s=g.state
        demon=next(s.entities[i]for i in s.players[1].board if s.entities[i].card_id in FEL_BEASTS)
        source=next(s.entities[i]for i in s.players[1].board if s.entities[i].card_id=='JAIL_721')
        assert(source.attack,source.max_health)==(3+demon.attack,3+demon.max_health)
    b=session(setup(('JAIL_721','TLC_479','CORE_CS2_029','CORE_CS2_029')),parasite)
    rows=[a,b];result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        new_roots=3,new_dependencies=4,lab_fixture_definitions=0,actions=sum(x['actions']for x in rows),checkpoints=sum(len(x['checkpoints'])for x in rows),
        scenarios=rows,formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(9,11)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result

if __name__=='__main__':main()
