"""Five actual native providers through player commands and portable states."""
import json
from examples.card_qualified_next import session
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.cards.native_health_attack_provider_cards import QUANTUM,BRALMA,GOLDRINN,KAYN,SURVIVALIST
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.model import Keyword,Zone
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION

YETI='CORE_CS2_182';BOLT='CORE_CS2_024';FIREFLY='CORE_UNG_809';CULTIST='TLC_101'


def setup(hand,*,board=(),enemy=(),enemy_hand=(),seed=5282):
    return Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*10,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
        PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*10,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=seed)


def attack(submit,cid,target_card=None):
    def choose(listing):
        players={p['id']:p for p in listing['observation']['players']};source=next(c['ref']for c in players[1]['board']if c['card_id']==cid)
        target=players[2]['hero']['ref']if target_card is None else next(c['ref']for c in players[2]['board']if c['card_id']==target_card)
        return next(a for a in listing['actions']if a['type']=='attack'and a['attacker']==source and a['defender']==target)
    submit(1,choose)


def main():
    def quantum(g,play,end,submit):
        play(1,QUANTUM);source=g.state.players[1].board[0];play(1,BOLT,target_card=QUANTUM);assert g.state.entities[source].health==3
    first=session(setup((QUANTUM,BOLT)),quantum)
    def bralma(g,play,end,submit):
        play(1,BRALMA);attack(submit,FIREFLY);assert g.state.entities[g.state.players[2].hero_id].health==28
    second=session(setup((BRALMA,),board=(FIREFLY,),seed=5283),bralma)
    def goldrinn(g,play,end,submit):
        target=g.state.players[2].board[0];play(1,GOLDRINN);attack(submit,GOLDRINN,YETI)
        assert g.state.entities[target].zone==Zone.GRAVEYARD and g.state.entities[g.state.players[1].board[0]].attack==9
    third=session(setup((GOLDRINN,),enemy=(YETI,),seed=5284),goldrinn)
    def kayn(g,play,end,submit):
        play(1,KAYN);attack(submit,YETI);attack(submit,KAYN);assert g.state.entities[g.state.players[2].hero_id].health==23
    fourth=session(setup((KAYN,),board=(YETI,),enemy=(CULTIST,),seed=5285),kayn)
    def survivalist(g,play,end,submit):
        play(1,SURVIVALIST);source=g.state.players[1].board[0];assert Keyword.IMMUNE in g.state.entities[source].keywords
        play(1,FIREFLY);assert Keyword.IMMUNE not in g.state.entities[source].keywords;end(1);play(2,BOLT,target_card=FIREFLY)
        assert Keyword.IMMUNE in g.state.entities[source].keywords
    fifth=session(setup((SURVIVALIST,FIREFLY),enemy_hand=(BOLT,),seed=5286),survivalist)
    cases=[first,second,third,fourth,fifth];result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=5,fixed_dependencies=0,unimplemented_root='CATA_432',lab_fixture_definitions=0,scenarios=cases,
        actions=sum(c['actions']for c in cases),checkpoints=sum(len(c['checkpoints'])for c in cases),formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(13,18)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
