"""Experimental 30-card matches exercising hand actions through player DTOs."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine import Game, MatchSetup
from hs_sim.engine.cli import summary
from hs_sim.engine.replay import build_replay, replay, save_replay
from hs_sim.engine.representative import build_registry
from examples.play_as_players import choose_action


def match_setup(seed):
    root = Path(__file__).resolve().parents[1]
    base = MatchSetup.from_dict(json.loads((root/'examples/matches/constructed.json').read_text(encoding='utf-8')))
    mage = ('TTN_042', 'TTN_724', 'LOE_029', 'CS2_182', 'CS2_179', 'EX1_096', 'FP1_007',
            'CS2_122', 'ULD_205', 'ULD_208', 'CS2_188', 'EX1_019', 'CS2_029', 'CS2_024', 'EX1_608')
    warrior = ('TTN_042', 'TTN_724', 'SW_094', 'ICC_091', 'LOE_029', 'CS2_182', 'CS2_179',
               'EX1_096', 'FP1_007', 'CS2_122', 'ULD_205', 'ULD_208', 'CS2_188', 'CS2_106', 'FP1_021')
    decks = tuple(replace(deck, cards=tuple(card for card in cards for _ in range(2)))
                  for deck, cards in zip(base.decks, (mage, warrior)))
    policy = replace(base.policy, id='representative-hand-actions-v1',
                     allowed_card_ids=tuple(sorted(set(mage + warrior))))
    return replace(base, decks=decks, policy=policy, seed=seed)


class ExercisePolicy:
    """Finite demonstration preference; all decisions use only this seat's view."""
    def __init__(self):
        self.forged = set()
        self.traded_turns = set()

    def choose(self, listing):
        observation = listing['observation']
        if observation['pending_choice'] is None and listing['error'] is None:
            # One forge per visible hand slot and one trade per turn keep this
            # fixture moving. These are policy preferences, not game limits.
            for action in listing['actions']:
                if action['type'] != 'use_hand_action':
                    continue
                if action['action_id'] == 'forge' and action['card'] not in self.forged:
                    self.forged.add(action['card'])
                    return action
                if action['action_id'] == 'trade' and observation['turn'] not in self.traded_turns:
                    self.traded_turns.add(observation['turn'])
                    return action
        return choose_action(listing)


def play_match(seed=73):
    game = Game.from_decks(match_setup(seed), build_registry())
    policies = {i: ExercisePolicy() for i in (1, 2)}
    # Persist and recover a pending mulligan before the first player command.
    game = Game.from_snapshot(json.loads(json.dumps(game.snapshot())), build_registry())
    restored_at = []
    for _ in range(500):
        routing = game.for_player(1).observe()['observation']
        if routing['status'] != 'playing':
            break
        actor = routing['pending_choice']['player_id'] if routing['pending_choice'] else routing['active_player']
        port = game.for_player(actor)
        listing = port.legal_actions()
        action = policies[actor].choose(listing)
        reply = port.submit({'revision': listing['revision'], 'action': action})
        if not reply['accepted']:
            raise RuntimeError(f'Player command failed: {reply["error"]}')
        # Restore a live random choice and the first hand operation using only
        # JSON; the independent policy retains its own public decision history.
        category = ('choice' if game.state.pending_choice is not None else
                    'hand' if action['type'] == 'use_hand_action' else None)
        if category is not None and category not in restored_at:
            snapshot = json.loads(json.dumps(game.snapshot()))
            assert replay(build_replay(game), build_registry()).snapshot() == snapshot
            game = Game.from_snapshot(snapshot, build_registry())
            restored_at.append(category)
    if game.state.status == 'playing':
        raise RuntimeError('Exercise match exceeded the action budget')
    restored = replay(build_replay(game), build_registry())
    assert restored.snapshot() == game.snapshot()
    for viewer in (1, 2):
        assert restored.for_player(viewer).observe() == game.for_player(viewer).observe()
        assert restored.for_player(viewer).events() == game.for_player(viewer).events()
    return game


def main():
    game = play_match()
    output = Path(__file__).resolve().parents[1]/'outputs'
    output.mkdir(exist_ok=True)
    save_replay(game, output/'hand-actions-complete-replay.json')
    (output/'hand-actions-complete-snapshot.json').write_text(
        json.dumps(game.snapshot(), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(summary(game), ensure_ascii=False, indent=2))
    print(json.dumps({'trades': sum(e.kind=='card_traded' for e in game.events),
        'forges': sum(e.kind=='card_forged' for e in game.events),
        'choices': sum(e.kind=='choice_requested' for e in game.events),
        'player_events': {i:len(game.for_player(i).events()) for i in (1, 2)}}, indent=2))


if __name__ == '__main__':
    main()
