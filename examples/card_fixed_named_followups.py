"""Two real roots and their named followups through player commands."""
import json
from examples.card_qualified_next import session
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.cards.fixed_named_followup_cards import BLOODPETAL, SEEDLING, THUNDERQUAKE, STATIC_SHOCK
from hs_sim.engine import PlayerSetup, Scenario
from hs_sim.engine.model import Zone
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION

YETI = 'CORE_CS2_182'


def setup(hand, *, board=(), enemy=(), seed=5383):
    return Scenario((
        PlayerSetup('HERO_08', hand=hand, board=board, deck=(YETI,)*8, mana=40,
                    max_mana=40, mana_cap=40, hero_power_card_id='HERO_08bp'),
        PlayerSetup('HERO_08', board=enemy, deck=(YETI,)*8, mana=40,
                    max_mana=40, mana_cap=40, hero_power_card_id='HERO_08bp'),
    ), seed=seed)


def main():
    def loop(g, play, end, submit):
        play(1, BLOODPETAL); old, = g.state.players[1].board
        play(1, THUNDERQUAKE); seed, = g.state.players[1].board
        assert g.state.entities[old].zone == Zone.GRAVEYARD
        assert g.state.entities[seed].card_id == SEEDLING
        play(1, STATIC_SHOCK, target_card=SEEDLING); fresh, = g.state.players[1].board
        assert len({old, seed, fresh}) == 3
        assert (g.state.entities[fresh].card_id, g.state.entities[fresh].attack,
                g.state.entities[fresh].health) == (BLOODPETAL, 5, 1)
        assert g.state.entities[g.state.players[2].board[0]].health == 4
    first = session(setup((BLOODPETAL, THUNDERQUAKE), enemy=(YETI,)), loop)

    def both_sides(g, play, end, submit):
        play(1, THUNDERQUAKE)
        assert all(g.state.entities[g.state.players[p].board[0]].card_id == SEEDLING for p in (1, 2))
        def choose(listing):
            players = {p['id']: p for p in listing['observation']['players']}
            card = next(c['ref'] for c in players[1]['hand'] if c['card_id'] == STATIC_SHOCK)
            target = players[2]['board'][0]['ref']
            return next(a for a in listing['actions'] if a['type'] == 'play_card' and a['card'] == card and a.get('target') == target)
        submit(1, choose)
        assert g.state.entities[g.state.players[2].board[0]].card_id == BLOODPETAL
        hero = g.state.players[1].hero_id; assert g.state.entities[hero].attack == 1
        end(1); assert g.state.entities[hero].attack == 0; end(2)
    second = session(setup((THUNDERQUAKE,), board=(BLOODPETAL,), enemy=(BLOODPETAL,), seed=5384), both_sides)
    cases = [first, second]
    result = dict(content_version=CONTENT_VERSION, core_effects_version=CORE_EFFECTS_VERSION,
        snapshot_schema=SNAPSHOT_SCHEMA_VERSION, roots=2, fixed_dependencies=1, reused_dependencies=1,
        lab_fixture_definitions=0, scenarios=cases, actions=sum(c['actions'] for c in cases),
        checkpoints=sum(len(c['checkpoints']) for c in cases), formal_pool_complete=False, cn_calibrated=False)
    assert (result['actions'], result['checkpoints']) == (7, 9)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True)); return result


if __name__ == '__main__': main()
