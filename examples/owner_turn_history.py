"""Native owner-turn history and frozen hand-face queries.

Synthetic cards combine existing public effects. No CN calibration or intrinsic
cost implementation is implied. A played Dragon becomes a Beast before natural
handoff, but its immutable submitted face remains Dragon. On the opponent's
turn a board trigger uses the owner's recently closed interval; a paid Spell on
the next own turn queries the same interval and waits for a public choice.
"""
import argparse
import json
from pathlib import Path

from hs_sim.engine import (
    CardClass, CardDefinition, CardMetadata, CardType, Game, PlayCard, PlayedTypeQuery,
    PlayerSetup, Registry, ResolutionError, Scenario, SpellSchool, TriggerSpec,
    query_previous_owner_turn,
)
from hs_sim.engine.effects import ChoiceOption, GainArmor, RequestChoice, Transform
from hs_sim.engine.replay import build_replay, replay


DRAGON = 'example.owner-history.dragon'
BEAST = 'example.owner-history.beast-form'
ARCANE = 'example.owner-history.arcane'
UNSCHOOLED = 'example.owner-history.unschooled'
QUERY = 'example.owner-history.query'
UNKNOWN = 'example.owner-history.unknown-query'
WATCHER = 'example.owner-history.opponent-watcher'
FILLER = 'example.owner-history.filler'
HIDDEN = 'example.owner-history.private-enemy-card'


def queries(state, player_id):
    """A pure consumer retaining every true/false row of the public query."""
    subjects = {
        'dragon': PlayedTypeQuery(CardType.MINION, ('dragon',)),
        'beast': PlayedTypeQuery(CardType.MINION, ('beast',)),
        'empty_tribes': PlayedTypeQuery(CardType.MINION, ()),
        'arcane': PlayedTypeQuery(CardType.SPELL, spell_school=SpellSchool.ARCANE),
        'fire': PlayedTypeQuery(CardType.SPELL, spell_school=SpellSchool.FIRE),
        'unschooled': PlayedTypeQuery(CardType.SPELL),
    }
    return {name: query_previous_owner_turn(state, player_id, query)
            for name, query in subjects.items()}


def query_summary(state, player_id):
    return {name: {
        'owner_turn_id': None if match.owner_turn is None else match.owner_turn.id,
        'owner_turn_number': None if match.owner_turn is None else match.owner_turn.turn,
        'matched': match.matched,
        'rows': [{'card_id': row.face.card_id, 'matched': row.matched,
                  'source_id': row.face.source_id, 'play_id': row.face.play_id}
                 for row in match.rows],
    } for name, match in queries(state, player_id).items()}


def build_registry():
    registry = Registry('owner-turn-history-native-example-v1')
    mage = CardMetadata(False, (CardClass.MAGE,), None, tribes=())
    dragon = CardMetadata(False, (CardClass.MAGE,), None, tribes=('dragon',))
    beast = CardMetadata(False, (CardClass.MAGE,), None, tribes=('beast',))
    registry.register_card(CardDefinition('hero.one', 'Owner hero', CardType.HERO,
        health=30, metadata=mage))
    registry.register_card(CardDefinition('hero.two', 'Opponent hero', CardType.HERO,
        health=30, metadata=mage))

    def transform(context):
        return [Transform(context.source_id, BEAST)]

    def arcane(context):
        # The first current interval has no closed own predecessor yet.
        matches = queries(context.state, context.player_id)
        assert all(not value.matched and value.owner_turn is None
                   for value in matches.values())
        return [RequestChoice(context.player_id, (
            ChoiceOption('resolve', 'Resolve the first paid Spell',
                         (GainArmor(context.player_id, 1),)),),
            source_id=context.source_id)]

    def query(context):
        matches = queries(context.state, context.player_id)
        armor = sum(matches[key].matched for key in ('dragon', 'arcane'))
        return [RequestChoice(context.player_id, (
            ChoiceOption('resolve', 'Resolve the historical query',
                         (GainArmor(context.player_id, armor),)),),
            source_id=context.source_id)]

    def unknown(context):
        # Known metadata with unknown tribes is not an empty tribe declaration.
        query_previous_owner_turn(context.state, context.player_id,
                                  PlayedTypeQuery(CardType.MINION))
        return []

    def opponent_started(context):
        if context.event.player_id != 2:
            return []
        matches = queries(context.state, 1)
        assert context.state.active_player == 2
        armor = sum(matches[key].matched for key in ('dragon', 'arcane'))
        return [GainArmor(1, armor)]

    registry.register_behavior('example.owner-history.transform', transform)
    registry.register_behavior('example.owner-history.arcane', arcane)
    registry.register_behavior('example.owner-history.query', query)
    registry.register_behavior('example.owner-history.unknown', unknown)
    registry.register_behavior('example.owner-history.opponent-started', opponent_started)
    registry.register_behavior('example.owner-history.nothing', lambda context: [])
    registry.register_card(CardDefinition(DRAGON, 'Dragon with a changing live face',
        CardType.MINION, cost=1, attack=1, health=4, metadata=dragon,
        battlecry='example.owner-history.transform'))
    registry.register_card(CardDefinition(BEAST, 'Changed Beast face', CardType.MINION,
        attack=2, health=4, metadata=beast))
    registry.register_card(CardDefinition(ARCANE, 'First paid Arcane Spell', CardType.SPELL,
        cost=2, spell_school=SpellSchool.ARCANE, metadata=mage,
        on_play='example.owner-history.arcane'))
    registry.register_card(CardDefinition(UNSCHOOLED, 'Explicitly unschooled Spell',
        CardType.SPELL, cost=0, metadata=mage, on_play='example.owner-history.nothing'))
    registry.register_card(CardDefinition(QUERY, 'Paid history query Spell', CardType.SPELL,
        cost=1, spell_school=SpellSchool.FIRE, metadata=mage,
        on_play='example.owner-history.query'))
    registry.register_card(CardDefinition(UNKNOWN, 'Unknown subject query control',
        CardType.SPELL, cost=1, metadata=mage, on_play='example.owner-history.unknown'))
    registry.register_card(CardDefinition(WATCHER, 'Opponent start-history observer',
        CardType.MINION, attack=1, health=5, metadata=mage,
        triggers=(TriggerSpec('turn_started', 'example.owner-history.opponent-started'),)))
    for card_id in (FILLER, HIDDEN):
        registry.register_card(CardDefinition(card_id, card_id, CardType.MINION,
            attack=1, health=1, metadata=mage))
    return registry


def submit(game, kind, card_id=None, *, position=None, expect_accepted=True):
    port = game.for_player(game.state.active_player)
    listing = port.legal_actions()
    assert listing['error'] is None, listing
    actions = [action for action in listing['actions'] if action['type'] == kind]
    if card_id is not None:
        own = next(player for player in listing['observation']['players']
                   if player['id'] == game.state.active_player)
        reference = next(card['ref'] for card in own['hand'] if card['card_id'] == card_id)
        actions = [action for action in actions if action['card'] == reference]
    if position is not None:
        actions = [action for action in actions if action.get('position') == position]
    assert len(actions) == 1, (kind, card_id, actions)
    result = port.submit({'revision': listing['revision'], 'action': actions[0]})
    assert result['accepted'] is expect_accepted, result
    return result


def assert_player_information(game):
    forbidden = (
        'owner_turn_history', 'played_face', 'owner_turn_id', 'opening_first_player',
        'start_interruption', 'cost_use_history', 'spell_submission', 'spell_payload',
        'resolution_frame', 'rng_state', 'FinishSpellAcceptance',
    )
    for player_id in (1, 2):
        port = game.for_player(player_id)
        observation = port.observe()
        value = {'observation': observation, 'actions': port.legal_actions(),
                 'events': port.events()}
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
        assert all('"' + field + '"' not in encoded for field in forbidden)
        if player_id == 1:
            assert HIDDEN not in encoded
        if player_id == 2:
            assert UNKNOWN not in encoded
            if any(game.state.entities[value].card_id == QUERY
                   for value in game.state.players[1].hand):
                assert QUERY not in encoded
        detached = port.observe()
        detached.clear()
        assert port.observe() == observation


def portable(game):
    snapshot = json.loads(json.dumps(game.snapshot(), ensure_ascii=False))
    branches = (Game.from_snapshot(snapshot, build_registry()), game.clone(),
                replay(build_replay(game), build_registry()))
    for branch in branches:
        assert branch.snapshot() == snapshot
        for player_id in (1, 2):
            assert branch.for_player(player_id).observe() == game.for_player(player_id).observe()
        assert_player_information(branch)
    return snapshot, list(branches)


def run():
    game = Game.from_scenario(Scenario((
        PlayerSetup('hero.one', hand=(DRAGON, UNSCHOOLED, ARCANE, QUERY, UNKNOWN),
            deck=(FILLER,) * 6, mana=10, max_mana=10),
        PlayerSetup('hero.two', hand=(HIDDEN,), board=(WATCHER,),
            deck=(FILLER,) * 6, mana=10, max_mana=10)),
        seed=158, name='synthetic-real-owner-turn-history'), build_registry())
    waiting, positions, branches = [], [], []
    observations = {'before_first_close': query_summary(game.state, 1)}
    rng_state = game.snapshot()['rng_state']

    def step(kind, card_id=None, *, position=None):
        nonlocal branches
        submit(game, kind, card_id, position=position)
        for branch in branches:
            submit(branch, kind, card_id, position=position)
            assert branch.snapshot() == game.snapshot()
        branches = []
        assert game.snapshot()['rng_state'] == rng_state
        assert_player_information(game)
        if game.state.pending_choice is not None:
            snapshot, branches = portable(game)
            root = game.state.play_history[-1]
            assert root.card_id in (ARCANE, QUERY)
            assert root.cost == {ARCANE: 2, QUERY: 1}[root.card_id]
            assert root.submitted_cost.quote.amount == root.cost
            assert root.spell_submission is not None and root.spell_payload is not None
            assert not root.completed
            assert root.played_face.owner_turn_id == {ARCANE: 1, QUERY: 3}[root.card_id]
            waiting.append(snapshot)
            positions.append({'card_id': root.card_id, 'paid': root.cost,
                'owner_turn_id': root.played_face.owner_turn_id,
                'query': query_summary(game.state, 1)})

    step('play_card', DRAGON, position=0)
    face = game.state.play_history[0].played_face
    assert face.card_id == DRAGON and face.metadata.tribes == ('dragon',)
    assert game.state.entities[face.source_id].card_id == BEAST
    step('play_card', UNSCHOOLED)
    step('play_card', ARCANE)
    step('select_choice')
    assert game.state.entities[game.state.players[1].hero_id].armor == 1
    before_query = game.snapshot()
    assert all(not match.matched for match in queries(game.state, 1).values())
    assert game.snapshot() == before_query
    step('end_turn')
    observations['opponent_active'] = query_summary(game.state, 1)
    assert game.state.active_player == 2
    assert game.state.entities[game.state.players[1].hero_id].armor == 3
    step('end_turn')
    observations['next_own_active'] = query_summary(game.state, 1)
    observations['other_owner_closed_empty'] = query_summary(game.state, 2)
    assert game.state.active_player == 1
    assert observations['opponent_active'] == observations['next_own_active']
    matches = queries(game.state, 1)
    assert matches['dragon'].matched and matches['arcane'].matched
    assert not any(matches[key].matched for key in ('beast', 'empty_tribes', 'fire', 'unschooled'))
    assert [row.matched for row in matches['arcane'].rows] == [False, True]
    assert [row.face.card_id for row in matches['arcane'].rows] == [UNSCHOOLED, ARCANE]
    assert all(match.owner_turn.id == 1 for match in matches.values())
    assert all(match.owner_turn.id == 2 and not match.rows and not match.matched
               for match in queries(game.state, 2).values())
    step('play_card', QUERY)
    step('select_choice')
    assert game.state.entities[game.state.players[1].hero_id].armor == 5
    assert game.state.play_history[0].played_face == face
    snapshot, _ = portable(game)
    # A genuine public paid-hand attempt reaches the unknown query and rolls
    # back payment, root/fact/event/action allocation and the full state.
    history_before = list(game.history)
    failed = submit(game, 'play_card', UNKNOWN, expect_accepted=False)
    assert failed['error'] == 'resolution_failed' and failed['events'] == [], failed
    assert game.snapshot() == snapshot and game.history == history_before
    # Player-facing errors are deliberately generic. A separate engine action
    # against a clone proves the exact unknown-fact cause without exporting it.
    diagnostic = game.clone()
    source = next(value for value in diagnostic.state.players[1].hand
                  if diagnostic.state.entities[value].card_id == UNKNOWN)
    try:
        diagnostic.apply(PlayCard(1, source))
    except ResolutionError as error:
        assert 'unknown Minion tribes' in str(error), str(error)
    else:
        raise AssertionError('Unknown historical subject must be rejected explicitly')
    assert diagnostic.snapshot() == snapshot and diagnostic.history == history_before
    assert_player_information(game)
    observations['unknown_query_rolled_back'] = True
    assert len(waiting) == 2 and len(game.history) == 8
    assert [play.cost for play in game.state.play_history] == [1, 0, 2, 1]
    assert all(play.completed for play in game.state.play_history)
    return game, waiting, positions, observations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--replay')
    parser.add_argument('--output-dir', default=str(Path(__file__).resolve().parents[1] / 'outputs/v117-h1-native'))
    args = parser.parse_args()
    if args.replay:
        game = replay(json.loads(Path(args.replay).read_text(encoding='utf-8')), build_registry())
        print(json.dumps({'replayed': True, 'actions': len(game.history), 'state_hash': game.state_hash()}))
        return
    game, waiting, positions, observations = run()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    summary = {
        'actions': len(game.history), 'events': len(game.events),
        'state_hash': game.state_hash(), 'schema': game.snapshot()['schema_version'],
        'paid_amounts': [play.cost for play in game.state.play_history],
        'intervals': [{'id': value.id, 'owner': value.player_id,
                       'owner_index': value.owner_index, 'closed': value.closed}
                      for value in game.state.owner_turn_history],
        'armor': game.state.entities[game.state.players[1].hero_id].armor,
        'mana_remaining': game.state.players[1].mana,
        'choices': len(waiting), 'positions': positions, 'queries': observations,
        'restored_cloned_and_replayed': True, 'both_player_DTO': True,
        'synthetic_scenario': True, 'representative_cards_added': 0,
        'cn_calibrated': False,
    }
    for name, value in (
        ('summary', summary), ('snapshot', game.snapshot()), ('waiting', waiting),
        ('replay', build_replay(game)), ('view1', game.observe(1)), ('view2', game.observe(2)),
    ):
        with (output / (name + '.json')).open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
