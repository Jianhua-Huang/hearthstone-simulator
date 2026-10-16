"""Real Xavius, original deck cards and both delivery destinations via DTOs."""
import json
from examples.card_qualified_next import session
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.cards.stored_dark_gift_source import XAVIUS
from hs_sim.engine import PlayerSetup, Scenario
from hs_sim.engine.dark_gifts import public_gifts
from hs_sim.engine.model import Keyword, Zone
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION

YETI = 'CORE_CS2_182'; FIREBALL = 'CORE_CS2_029'


def setup(deck, seed):
    return Scenario((
        PlayerSetup('HERO_08', hand=(XAVIUS,), deck=deck, mana=40, max_mana=40,
                    mana_cap=40, hero_power_card_id='HERO_08bp'),
        PlayerSetup('HERO_08', deck=(YETI,)*4, mana=40, max_mana=40,
                    mana_cap=40, hero_power_card_id='HERO_08bp'),
    ), seed=seed)


def choose(submit, label):
    def action(listing):
        choice = listing['observation']['pending_choice']
        option = next(o for o in choice['options'] if label in o['label'])
        return next(a for a in listing['actions'] if a['type'] == 'select_choice' and a['options'] == [option['ref']])
    submit(1, action)


def main():
    def hand(g, play, end, submit):
        old, = g.state.players[1].deck
        play(1, XAVIUS); assert g.state.pending_choice is not None
        choose(submit, '衣甲厚实')
        assert g.state.players[1].hand == [old] and not g.state.draw_history
        assert public_gifts(g.state.entities[old])[0]['id'] == 'EDR_100t3'
        play(1, YETI); assert old in g.state.players[1].board
        assert (g.state.entities[old].attack, g.state.entities[old].health) == (4,9)
        assert Keyword.TAUNT in g.state.entities[old].keywords
    first = session(setup((YETI,), 4), hand)

    def top(g, play, end, submit):
        old = g.state.players[1].deck[1]
        play(1, XAVIUS); choose(submit, '甜美梦境')
        assert g.state.players[1].deck[0] == old and g.state.entities[old].zone == Zone.DECK
        assert not g.state.players[1].hand and not g.state.draw_history
        end(1); end(2); assert old in g.state.players[1].hand
        play(1, YETI); assert old in g.state.players[1].board
        assert (g.state.entities[old].attack, g.state.entities[old].health) == (8,10)
    second = session(setup((FIREBALL,YETI), 6), top)
    cases = [first,second]
    result = dict(content_version=CONTENT_VERSION, core_effects_version=CORE_EFFECTS_VERSION,
        snapshot_schema=SNAPSHOT_SCHEMA_VERSION, roots=1, reused_gift_recipes=10,
        lab_fixture_definitions=0, scenarios=cases, actions=sum(c['actions'] for c in cases),
        checkpoints=sum(len(c['checkpoints']) for c in cases), formal_pool_complete=False, cn_calibrated=False)
    assert (result['actions'],result['checkpoints']) == (8,10)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True)); return result


if __name__=='__main__':main()
