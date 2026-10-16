"""Real player commands: next Kindred bodies and intrinsic price, no fixtures."""
import json
from examples.card_qualified_next import session,setup
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.costs import quote_cost


def main():
    def body(g,play,end,submit):
        play(1,'DINO_435');end(1);end(2);play(1,'TLC_251');play(1,'TLC_429')
        s=g.state;tokens=[s.entities[i]for i in s.players[1].board if s.entities[i].card_id=='TLC_429t']
        assert len(tokens)==4 and not s.players[1].player_effects
        row=s.kindred_history[-1]
        assert row.card_id=='TLC_429'and row.plan==row.started==('active','active')and row.finished==(0,1)and row.completed
    first=session(setup(('DINO_435','TLC_251','TLC_429'),seed=4168),body)

    def price(g,play,end,submit):
        play(1,'TLC_243');end(1);end(2);play(1,'TLC_251')
        s=g.state;whelp=next(s.entities[i]for i in s.players[1].hand if s.entities[i].card_id=='TLC_600')
        assert quote_cost(s,g.registry,whelp).amount==4
        before=s.players[1].mana;play(1,'TLC_600',target_player=2);s=g.state
        assert before-s.players[1].mana==4 and s.entities[s.players[1].hero_id].armor==5
        assert s.entities[s.players[2].hero_id].health==25 and not s.players[1].player_effects
        assert len(s.cost_use_history[-1].kindred_sources)==1
    second=session(setup(('TLC_243','TLC_251','TLC_600'),seed=4169),price)
    scenarios=[first,second]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        actions=sum(x['actions']for x in scenarios),checkpoints=sum(len(x['checkpoints'])for x in scenarios),
        lab_fixture_definitions=0,scenarios=scenarios,formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(10,12)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
