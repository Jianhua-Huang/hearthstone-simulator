"""Synthetic callers and real end-turn consumers; no Inspiring Maul adapter.

This public scenario is not a legal constructed deck. The factory extends the
representative registry with clearly named synthetic declarations, and the
module's own replay CLI reconstructs that complete registry.
"""
import argparse
import json
from pathlib import Path

from hs_sim.engine import (CardDefinition, CardType, EndTurnActivationProfile,
    EndTurnRequest, EndTurnSelector, EndTurnSpec, Game, LimitedTriggerSpec,
    PlayerSetup, Scenario, TriggerEndTurnEffects, TriggerSpec, Zone)
from hs_sim.engine.effects import ChoiceOption, Damage, GainArmor, RequestChoice, Silence
from hs_sim.engine.representative import build_registry as representative_registry
from hs_sim.engine.replay import build_replay, replay
from examples.colossal_appendages import submit


FINITE_ID = 'demo.end_turn_finite'
PHASE_ID = 'demo.end_turn_phase_source'
BOTH_ID = 'demo.end_turn_both_caller'
ENEMY_ID = 'demo.end_turn_enemy_caller'
PHASE_PROFILE = 'demo.real_turn_started'


def request(players, *, mode='owner', entities=(), profile='end_turn.effect'):
    return EndTurnRequest(EndTurnSelector(mode, players, ('minion',), entities), profile)


def finite_body(context):
    """One real finite use, with a choice changing the next callback's state."""
    capture = context.end_turn
    group = context.state.end_turn_batches[capture.batch_id - 1]
    effects = []
    for entity_id in context.state.players[context.player_id].board:
        entity = context.state.entities[entity_id]
        if entity.card_id == 'ICC_901' and any(a.kind == 'end_turn_repeat' for a in entity.abilities):
            effects.append(Silence(entity_id))
    effects.append(Damage(context.source_id, 1, context.source_id))
    if group.activation.kind == 'effect' and capture.repeat_index == 0:
        enemy = 3 - context.player_id
        targets = tuple(i for i in context.state.players[enemy].board
                        if context.state.entities[i].card_id == 'BOT_107')
        effects.append(TriggerEndTurnEffects(context.player_id,
            request((enemy,), mode='selected', entities=targets), context.source_id))
    return [GainArmor(context.player_id, context.source.damage + 1),
        RequestChoice(context.player_id,
            (ChoiceOption('continue', 'Change state, then continue the accepted plan', tuple(effects)),),
            source_id=context.source_id, prompt='Synthetic end-turn body: advance one damage step')]


def phase_body(context):
    """Forward the actual turn_started fact without ending or starting a turn."""
    if context.event.player_id != context.player_id:
        return []
    return [TriggerEndTurnEffects(context.player_id,
        request((3 - context.player_id,), profile=PHASE_PROFILE), context.source_id, context.event)]


def build_registry():
    registry = representative_registry()
    registry.register_end_turn_profile(EndTurnActivationProfile(PHASE_PROFILE,
        kind='phase', turn_scope='ignore', target_policy='none', cause_events=('turn_started',)))
    registry.register_behavior('demo.end_turn_both', lambda c: [TriggerEndTurnEffects(
        c.player_id, request((1, 2)), c.source_id)])
    registry.register_behavior('demo.end_turn_enemy', lambda c: [TriggerEndTurnEffects(
        c.player_id, request((3 - c.player_id,)), c.source_id)])
    registry.register_behavior('demo.end_turn_finite_body', finite_body)
    registry.register_behavior('demo.end_turn_phase_body', phase_body)
    for definition in (
        CardDefinition(BOTH_ID, 'Synthetic both-owner end-turn caller', CardType.SPELL,
            on_play='demo.end_turn_both'),
        CardDefinition(ENEMY_ID, 'Synthetic enemy-owner end-turn caller', CardType.SPELL,
            on_play='demo.end_turn_enemy'),
        CardDefinition(FINITE_ID, 'Synthetic finite end-turn choice body', CardType.MINION, health=50,
            limited_triggers=(LimitedTriggerSpec('turn_ended', 'demo.end_turn_finite_body',
                uses=4, end_turn=EndTurnSpec()),)),
        CardDefinition(PHASE_ID, 'Synthetic real-start phase forwarder', CardType.MINION, health=50,
            triggers=(TriggerSpec('turn_started', 'demo.end_turn_phase_body'),)),
    ):
        registry.register_card(definition)
    return registry


def resolve_choices(game):
    resolved = 0
    while game.state.pending_choice is not None:
        assert resolved < 12
        port = game.for_player(game.state.pending_choice.player_id)
        listing = port.legal_actions()
        action = next(a for a in listing['actions'] if a['type'] == 'select_choice')
        assert port.submit({'revision': listing['revision'], 'action': action})['accepted']
        resolved += 1
    return resolved


def clocks(game):
    return tuple(sum(e.kind == kind for e in game.events)
                 for kind in ('turn_ended', 'turn_started', 'card_drawn', 'player_effect_ticked'))


def run():
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_04', board=('ICC_901', 'BOT_107', FINITE_ID),
            hand=('CATA_480', BOTH_ID, ENEMY_ID), deck=('CS2_182',) * 4, mana=10, max_mana=10),
        PlayerSetup('HERO_08', board=('BOT_107', PHASE_ID), deck=('CS2_182',) * 4)),
        seed=146, name='synthetic-end-turn-activations'), build_registry())
    submit(game, 'CATA_480')
    submit(game, BOTH_ID)
    assert game.state.pending_choice is not None
    assert clocks(game) == (0, 0, 0, 0)
    assert game.state.players[1].player_effects[0].remaining_turns == 3
    snapshot = game.snapshot()
    restored = Game.from_snapshot(json.loads(json.dumps(snapshot)), build_registry())
    for match in (game, restored):
        assert resolve_choices(match) == 2
        assert clocks(match) == (0, 0, 0, 0)
        outer, nested = match.state.end_turn_batches
        assert outer.activation.request.selector.player_ids == (1, 2)
        assert [p.repetitions for p in outer.plans] == [2, 2, 1]
        assert {s.card_id for s in outer.plans[0].contributors} == {'ICC_901', 'CATA_480'}
        assert len(outer.plans[0].contributors) == 2
        assert nested.activation.parent_batch_id == outer.id
        assert nested.activation.parent_id == outer.first_id + 2
        assert nested.activation.request.selector.mode == 'selected'
        assert nested.subjects[0].player_id == 2 and nested.activation.issuer_player_id == 1
        icc = next(e for e in match.state.entities.values() if e.card_id == 'ICC_901')
        assert icc.silenced and not icc.abilities
        assert [e.amount for e in match.events if e.kind == 'armor_gained'] == [3, 5]
        submit(match, ENEMY_ID)
        enemy = match.state.end_turn_batches[-1]
        assert enemy.activation.request.selector.player_ids == (2,)
        assert all(s.player_id == 2 for s in enemy.subjects)
        assert clocks(match) == (0, 0, 0, 0)
        assert match.state.players[1].player_effects[0].remaining_turns == 3
        submit(match)
        assert resolve_choices(match) == 4
        state = match.state
        groups = state.end_turn_batches
        assert [b.activation.kind for b in groups] == ['effect', 'effect', 'effect', 'natural', 'phase']
        assert [b.total for b in groups] == [5, 1, 1, 4, 4]
        assert all(b.completed for b in groups)
        assert [p.repetitions for p in groups[-1].plans] == [2, 2]
        assert all({s.card_id for s in p.contributors} == {'CATA_480'} for p in groups[-1].plans)
        phase = groups[-1]
        assert phase.activation.issuer_player_id == 2 and all(s.player_id == 1 for s in phase.subjects)
        assert phase.event.kind == 'turn_started' and phase.event in match.events
        assert phase.event.player_id == 2 and phase.activation.request.profile_id == PHASE_PROFILE
        assert clocks(match) == (1, 1, 1, 1)
        assert state.turn == 2 and state.active_player == 2
        assert state.players[1].player_effects[0].remaining_turns == 2
        assert len(state.players[1].deck) == 4 and len(state.players[2].deck) == 3
        finite = next(state.entities[i] for i in state.players[1].board if state.entities[i].card_id == FINITE_ID)
        ability = next(a for a in finite.abilities if a.kind == 'limited_trigger')
        assert ability.uses_remaining == 1 and finite.damage == 15
        assert [e.amount for e in match.events if e.kind == 'armor_gained'] == [3, 5, 10, 11, 14, 15]
        rows = state.end_turn_history
        finite_rows = [r for r in rows if r.capture.subject.card_id == FINITE_ID]
        assert len(finite_rows) == 6 and all(r.completed and r.guard_passed for r in finite_rows)
        receipts = [r.guard_event for r in finite_rows if r.capture.repeat_index == 0]
        assert len(receipts) == 3 and len({e.sequence for e in receipts}) == 3
        assert sum(e.kind == 'limited_trigger_used' for e in match.events) == 3
        assert all(r.guard_event == next(x.guard_event for x in finite_rows if x.id == r.guard_id)
                   for r in finite_rows)
        assert sorted(r.execution_order for r in rows) == list(range(1, 16))
        assert len(rows) == 15 and all(r.completed for r in rows)
        assert [d.card_id for d in state.death_history] == ['ICC_901', 'BOT_107']
        assert icc.id in state.entities and state.entities[icc.id].zone == Zone.GRAVEYARD
        assert [state.entities[p.hero_id].health for p in state.players.values()] == [28, 21]
        assert state.entities[state.players[1].hero_id].armor == 51
        public = json.dumps(match.observe(1), sort_keys=True)
        for private in ('end_turn_guard_id', 'end_turn_ability_id', 'guard_event', 'contributors', 'parent_batch_id'):
            assert '"' + private + '"' not in public
    assert game.snapshot() == restored.snapshot()
    assert replay(build_replay(game), build_registry()).snapshot() == game.snapshot()
    return game, snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', type=Path, help='Verify with this explicit extended registry factory')
    args = parser.parse_args()
    if args.replay is not None:
        game = replay(json.loads(args.replay.read_text(encoding='utf-8')), build_registry())
        print('回放逐步校验通过')
        print(json.dumps({'actions': len(game.history), 'state_hash': game.state_hash()}))
        return
    game, snapshot = run()
    output = Path(__file__).resolve().parents[1] / 'outputs'
    for name, value in (('v105-end-turn-activations-snapshot.json', snapshot),
                        ('v105-end-turn-activations-replay.json', build_replay(game)),
                        ('v105-end-turn-activations-view.json', game.observe(1))):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'actions': len(game.history), 'events': len(game.events),
        'end_turn_batches': len(game.state.end_turn_batches),
        'end_turn_activations': len(game.state.end_turn_history),
        'finite_consumptions': sum(e.kind == 'limited_trigger_used' for e in game.events),
        'nested_batches': sum(b.activation.parent_batch_id is not None for b in game.state.end_turn_batches),
        'phase_batches': sum(b.activation.kind == 'phase' for b in game.state.end_turn_batches),
        'state_hash': game.state_hash(), 'restored_and_replayed': True}))


if __name__ == '__main__':
    main()
