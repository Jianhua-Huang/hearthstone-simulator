"""Real rune predecessor and four Necronurses through ordinary player DTOs."""
import json
from examples.card_qualified_next import session
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.cards.blood_rune_native_cards import BLADE,SURGERY,NURSE
from hs_sim.engine import Keyword,PlayerSetup,Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION


def setup(hand,*,enemy=(),enemy_hand=(),seed=4675):
    return Scenario((PlayerSetup('HERO_08',hand=hand,deck=('CORE_CS2_182',)*8,mana=10,max_mana=10,hero_power_card_id='HERO_08bp'),
        PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=('CORE_CS2_182',)*8,mana=10,max_mana=10,hero_power_card_id='HERO_08bp')),seed=seed)


def main():
    def runes(g,play,end,submit):
        play(1,'EDR_813');play(1,BLADE)
        weapon=g.state.entities[g.state.players[1].weapon_id]
        assert(weapon.attack,weapon.durability)==(3,3)
    first=session(setup(('EDR_813',BLADE)),runes)
    def surgery(g,play,end,submit):
        end(1);play(2,'CORE_CS2_029',target_player=1);end(2)
        play(1,SURGERY,target_card='CORE_CS2_182')
        s=g.state;remaining=[s.entities[i]for i in s.players[1].board]
        assert len(remaining)==2 and all((e.card_id,e.attack,e.health)==(NURSE,3,1)and Keyword.LIFESTEAL in e.keywords for e in remaining)
        assert not s.players[2].board and len(s.character_attack_history)==2
        assert s.entities[s.players[1].hero_id].health==30
    second=session(setup((SURGERY,),enemy=('CORE_CS2_182',),enemy_hand=('CORE_CS2_029',),seed=4676),surgery)
    scenarios=[first,second]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=2,fixed_dependencies=1,lab_fixture_definitions=0,scenarios=scenarios,actions=sum(x['actions']for x in scenarios),
        checkpoints=sum(len(x['checkpoints'])for x in scenarios),formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(6,8)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
