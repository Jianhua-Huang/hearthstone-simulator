"""Two actual native roots through player DTOs and portable game boundaries."""
import json
from examples.card_qualified_next import session
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.cards.kindred_hand_bonus_cards import TWISTED,TORGA
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.model import Keyword
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION

YETI='CORE_CS2_182';STORM='TLC_107';FROST='TLC_440';BOLT='CORE_CS2_024'


def setup(hand,deck=(YETI,)*8,seed=4979):
    return Scenario((PlayerSetup('HERO_08',hand=hand,deck=deck,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
        PlayerSetup('HERO_08',deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=seed)


def main():
    def held(g,play,end,submit):
        source=g.state.entities[g.state.players[1].hand[0]];assert source.keywords=={Keyword.TAUNT,Keyword.ELUSIVE}
        end(1);end(2);source=g.state.entities[source.id]
        printed=tuple(a.keyword for a in source.abilities if a.kind=='keyword'and a.origin=='printed'and not a.consumed)
        assert len(printed)==len(set(printed))==2;play(1,TWISTED)
        assert g.state.entities[source.id].keywords==set(printed)
    first=session(setup((TWISTED,)),held)
    def minion(g,play,end,submit):
        play(1,TORGA);rows=g.state.draw_history
        assert len(rows)==2 and all(row.card_id==STORM for row in rows)and rows[0].entity_id!=rows[1].entity_id
        assert not g.state.kindred_history
    second=session(setup((TORGA,),(STORM,STORM),seed=4980),minion)
    def spell(g,play,end,submit):
        play(1,TORGA);assert [row.card_id for row in g.state.draw_history]==[FROST,BOLT]
    third=session(setup((TORGA,),(FROST,BOLT,YETI),seed=4981),spell)
    cases=[first,second,third]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=2,fixed_dependencies=0,lab_fixture_definitions=0,scenarios=cases,
        actions=sum(case['actions']for case in cases),checkpoints=sum(len(case['checkpoints'])for case in cases),formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(5,8)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
