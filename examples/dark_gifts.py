"""Two real Dark Gift sources driven through player JSON commands."""
import json
from hs_sim.engine import Game, Scenario, PlayerSetup, GenerationContext
from hs_sim.engine.dark_gifts import DARK_GIFTS
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import load_baseline


def run_source(source):
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_08', hand=(source,), deck=('CS2_118',)*8, mana=10, max_mana=10),
        PlayerSetup('HERO_08', deck=('CS2_118',)*8, mana=10, max_mana=10)), seed=12,
        generation_context=GenerationContext(load_baseline().target['target_id'], 'experimental')), build_registry())
    checkpoints = []
    def check():
        saved = game.snapshot()
        assert Game.from_snapshot(saved, build_registry()).snapshot() == saved
        assert game.clone().snapshot() == saved
        assert replay(build_replay(game), build_registry()).snapshot() == saved
        checkpoints.append('waiting' if game.state.pending_choice else 'ready')
    def submit(listing, action):
        reply = game.for_player(1).submit({'revision': listing['revision'], 'action': action})
        assert reply['accepted'], reply['error']
    check()
    listing = game.for_player(1).legal_actions()
    submit(listing, next(a for a in listing['actions'] if a['type'] == 'play_card'))
    check()
    listing = game.for_player(1).legal_actions()
    pending = listing['observation']['pending_choice']
    selected = next(o for o in pending['options'] if '活体梦魇' in o['label'])
    submit(listing, next(a for a in listing['actions'] if a['type'] == 'select_choice' and a['options'] == [selected['ref']]))
    check()
    listing = game.for_player(1).legal_actions()
    own = next(p for p in listing['observation']['players'] if p['id'] == 1)
    card = next(c for c in own['hand'] if c.get('dark_gifts'))
    submit(listing, next(a for a in listing['actions'] if a['type'] == 'play_card' and a['card'] == card['ref']))
    check()
    return {'source': source, 'gift': 'EDR_100t5', 'checkpoints': checkpoints,
            'actions': len(game.history), 'events': len(game.events),
            'board': [(game.state.entities[i].card_id, game.state.entities[i].attack,
                       game.state.entities[i].health) for i in game.state.players[1].board],
            'mana': game.state.players[1].mana}


def main():
    result = {'gift_count': len(DARK_GIFTS), 'formal_minion_pool': False,
              'sources': [run_source(source) for source in ('EDR_105', 'FIR_900')]}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


if __name__ == '__main__':
    main()
