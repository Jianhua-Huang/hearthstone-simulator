"""Synthetic paid-hand fees at the original two repeat-acceptance windows.

The first root costs 1 because its last-use discount is consumed at payment;
its two later accepted-hand quotes are 3. The middle root costs 3, but a real
committed reaction removes the tax before late acceptance. Its three accepted
payloads survive the first payload's removal of the donor and return of the tax.
No real cards, official timing calibration or automated CAST support is implied.
"""
import argparse
import json
from pathlib import Path

from hs_sim.engine import (
    CardClass, CardDefinition, CardMetadata, CardType, CostAuraSpec, CostSpec,
    Game, PlayerSetup, RecipientMetadataFilter, Registry, RepeatCostFilter,
    RepeatMatchSpec, RepeatSourceEligibility, Scenario, SpellRepeatSpec,
    SpellSchool, TriggerSpec,
)
from hs_sim.engine.effects import (
    AddCostModifier, ChoiceOption, Destroy, GainArmor, GrantCostAura,
    ModifyCost, RequestChoice, Silence,
)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_modifiers import AddSpellRepeatModifier


PROFILE = 'repeat.cost.accepted_hand'
PREPARE = 'example.fee.prepare'
BEFORE = 'example.fee.before'
MIDDLE = 'example.fee.middle'
AFTER = 'example.fee.after'
DONOR = 'example.fee.donor'
FALSE_DONOR = 'example.fee.false-donor'
WATCHER = 'example.fee.watcher'
TAX = 'example.fee.tax'
HIDDEN = 'example.fee.hidden'


def build_registry():
    registry = Registry('spell-cost-matching-example-v1')
    mage = CardMetadata(False, (CardClass.MAGE,), None, tribes=())
    dragon = CardMetadata(False, (CardClass.MAGE,), None, tribes=('dragon',))
    warrior = CardMetadata(False, (CardClass.WARRIOR,), None, tribes=())
    registry.register_card(CardDefinition('hero.one', 'Own hero', CardType.HERO,
        health=30, metadata=warrior))
    registry.register_card(CardDefinition('hero.two', 'Enemy hero', CardType.HERO,
        health=30, metadata=mage))
    school = RecipientMetadataFilter(spell_schools=(SpellSchool.ARCANE,))
    late_match = RepeatMatchSpec(recipient_metadata=school,
        source_eligibility=RepeatSourceEligibility('repeat.witness.controlled',
            tribes_any=('dragon',), exclude_carrier=True),
        recipient_cost=RepeatCostFilter('window_quote', maximum=2, quote_profile_id=PROFILE))
    submitted_match = RepeatMatchSpec(recipient_metadata=school,
        recipient_cost=RepeatCostFilter('submitted_quote', maximum=2))
    window_player_match = RepeatMatchSpec(recipient_metadata=school,
        recipient_cost=RepeatCostFilter('window_quote', maximum=2, quote_profile_id=PROFILE))
    registry.register_card(CardDefinition(DONOR, 'Late fee donor', CardType.MINION,
        attack=1, health=5, metadata=dragon,
        spell_repeats=(SpellRepeatSpec(3, 'other', late_match),)))
    false_late_match = RepeatMatchSpec(recipient_metadata=school,
        recipient_cost=RepeatCostFilter('window_quote', minimum=9, quote_profile_id=PROFILE))
    registry.register_card(CardDefinition(FALSE_DONOR, 'False late fee donor', CardType.MINION,
        attack=1, health=5, metadata=mage,
        spell_repeats=(SpellRepeatSpec(4, 'other', false_late_match),)))
    tax = CostAuraSpec(CostSpec(delta=2, card_types=(CardType.SPELL,)), relation='enemy')
    registry.register_card(CardDefinition(TAX, 'Enemy spell tax', CardType.MINION,
        attack=1, health=5, cost_auras=(tax,), metadata=mage))
    registry.register_card(CardDefinition(HIDDEN, 'Private enemy card', CardType.MINION,
        attack=1, health=1, metadata=mage))

    def prepare(context):
        sources = [i for i in context.state.players[context.player_id].hand
                   if context.state.entities[i].card_id in (BEFORE, MIDDLE, AFTER)]
        assert len(sources) == 3
        return [*(ModifyCost(i, CostSpec(set_to=1), context.source_id) for i in sources),
            AddCostModifier(context.player_id,
                CostSpec(delta=-2, card_types=(CardType.SPELL,), card_ids=(BEFORE,)),
                uses_remaining=1, source_id=context.source_id),
            AddSpellRepeatModifier(context.player_id,
                SpellRepeatSpec(2, 'other', submitted_match),
                source_id=context.source_id, uses=2),
            AddSpellRepeatModifier(context.player_id,
                SpellRepeatSpec(4, 'other', window_player_match),
                source_id=context.source_id, uses=2)]

    def remove_tax(context):
        if context.event.source_id is None:
            return []
        source = context.state.entities[context.event.source_id]
        if source.card_id != MIDDLE:
            return []
        carrier = next(i for i in context.state.players[2].board
                       if context.state.entities[i].card_id == TAX)
        return [Silence(carrier)]

    def payload(context):
        effects = [GainArmor(context.player_id, 1)]
        if context.cast.card_id == MIDDLE and context.cast.iteration == 1:
            donor = next(i for i in context.state.players[context.player_id].board
                         if context.state.entities[i].card_id == DONOR)
            carrier = next(i for i in context.state.players[2].board
                           if context.state.entities[i].card_id == TAX)
            effects += [Destroy(donor, context.source_id),
                        GrantCostAura(carrier, tax, context.source_id)]
        return [RequestChoice(context.player_id, (
            ChoiceOption('resolve', 'Resolve this accepted payload', tuple(effects)),),
            source_id=context.source_id)]

    registry.register_behavior('example.fee.prepare', prepare)
    registry.register_behavior('example.fee.remove-tax', remove_tax)
    registry.register_behavior('example.fee.payload', payload)
    registry.register_card(CardDefinition(PREPARE, 'Prepare fee sources', CardType.MINION,
        health=4, metadata=mage, battlecry='example.fee.prepare'))
    registry.register_card(CardDefinition(WATCHER, 'Committed tax remover', CardType.MINION,
        health=4, metadata=dragon,
        triggers=(TriggerSpec('card_committed', 'example.fee.remove-tax'),)))
    for card_id in (BEFORE, MIDDLE, AFTER):
        registry.register_card(CardDefinition(card_id, card_id, CardType.SPELL,
            cost=5, metadata=mage, spell_school=SpellSchool.ARCANE,
            on_play='example.fee.payload'))
    return registry


def submit(game, kind, card_id=None, *, position=None):
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
    assert result['accepted'], result
    return result


def window_amount(receipt):
    facts = receipt.cost_facts
    assert facts is not None
    quotes = [q for q in facts.window_quotes if q.profile_id == PROFILE]
    assert len(quotes) == 1
    return quotes[0].amount


def assert_player_information(game):
    forbidden = (
        'submitted_cost', 'cost_facts', 'cost_input', 'window_quotes',
        'cost_use_history', 'payment_state', 'quote_state', 'cost_proof',
        'spell_submission', 'spell_payload', 'spell_acceptances',
        'resolution_frame', 'rng_state', 'FinishSpellAcceptance',
    )
    for player_id in (1, 2):
        port = game.for_player(player_id)
        observation = port.observe()
        value = {'observation': observation, 'actions': port.legal_actions(), 'events': port.events()}
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
        assert all('"' + field + '"' not in encoded for field in forbidden)
        if player_id == 1:
            assert HIDDEN not in encoded
        detached = port.observe()
        detached.clear()
        assert port.observe() == observation


def run():
    game = Game.from_scenario(Scenario((
        PlayerSetup('hero.one', hand=(PREPARE, BEFORE, MIDDLE, AFTER),
            board=(DONOR, WATCHER, FALSE_DONOR), mana=10, max_mana=10),
        PlayerSetup('hero.two', hand=(HIDDEN,), board=(TAX,))),
        seed=157, name='synthetic-paid-fees-two-repeat-windows'), build_registry())
    waiting = []
    positions = []
    branches = []
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
            snapshot = json.loads(json.dumps(game.snapshot()))
            restored = Game.from_snapshot(snapshot, build_registry())
            cloned = game.clone()
            replayed = replay(build_replay(game), build_registry())
            for branch in (restored, cloned, replayed):
                assert branch.snapshot() == snapshot
                for player_id in (1, 2):
                    assert branch.for_player(player_id).observe() == game.for_player(player_id).observe()
            branches = [restored, cloned, replayed]
            root = game.state.play_history[-1]
            assert root.spell_payload.casts == {BEFORE: 2, MIDDLE: 3, AFTER: 1}[root.card_id]
            assert root.submitted_cost is not None
            assert root.submitted_cost.quote.amount == root.cost
            assert (root.spell_submission.cost_facts.printed_cost,
                    root.spell_submission.cost_facts.local_amount) == (5, 1)
            assert (root.spell_payload.cost_facts.printed_cost,
                    root.spell_payload.cost_facts.local_amount) == (5, 1)
            assert window_amount(root.spell_payload) == (1 if root.card_id == MIDDLE else 3)
            # The false player window source demands this independent quote;
            # it must be retained even though it contributes no repeat count.
            assert window_amount(root.spell_submission) == 3
            iteration = next(c.iteration for c in reversed(game.state.cast_history) if c.play_id == root.id)
            waiting.append(snapshot)
            positions.append({'card_id': root.card_id, 'iteration': iteration,
                              'cost': root.cost, 'casts': root.spell_payload.casts,
                              'late_window_amount': window_amount(root.spell_payload)})

    step('play_card', PREPARE, position=3)
    for card_id, expected_waits in ((BEFORE, 2), (MIDDLE, 3), (AFTER, 1)):
        start = len(waiting)
        step('play_card', card_id)
        while game.state.pending_choice is not None:
            step('select_choice')
        assert len(waiting) - start == expected_waits
    roots = [p for p in game.state.play_history if p.kind == CardType.SPELL]
    assert [p.cost for p in roots] == [1, 3, 3]
    assert [p.spell_payload.casts for p in roots] == [2, 3, 1]
    assert [len(p.spell_submission.modifiers) for p in roots] == [1, 0, 0]
    assert [len(p.spell_payload.contributors) for p in roots] == [0, 1, 0]
    assert all(p.completed and p.spell_acceptance_closed for p in roots)
    assert game.state.players[1].mana == 3
    assert game.state.entities[game.state.players[1].hero_id].armor == 6
    assert [m.spec.casts for m in game.state.players[1].spell_modifiers] == [2, 4]
    assert [m.uses_remaining for m in game.state.players[1].spell_modifiers] == [1, 2]
    assert game.state.players[1].cost_modifiers == []
    assert len(game.state.cost_use_history) == 4
    assert len(waiting) == 6 and len(game.history) == 10
    snapshot = game.snapshot()
    assert Game.from_snapshot(json.loads(json.dumps(snapshot)), build_registry()).snapshot() == snapshot
    assert game.clone().snapshot() == snapshot
    assert replay(build_replay(game), build_registry()).snapshot() == snapshot
    return game, waiting, positions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--replay')
    parser.add_argument('--output-dir', default=str(Path(__file__).resolve().parents[1] / 'outputs/v116-fee-native'))
    args = parser.parse_args()
    if args.replay:
        game = replay(json.loads(Path(args.replay).read_text(encoding='utf-8')), build_registry())
        print(json.dumps({'replayed': True, 'actions': len(game.history), 'state_hash': game.state_hash()}))
        return
    game, waiting, positions = run()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    summary = {
        'actions': len(game.history), 'events': len(game.events),
        'state_hash': game.state_hash(), 'schema': game.snapshot()['schema_version'],
        'paid_amounts': [1, 3, 3], 'accepted_quotas': [2, 3, 1],
        'late_window_amounts': [3, 1, 3], 'armor': 6, 'mana_remaining': 3,
        'choices': len(waiting), 'positions': positions,
        'restored_cloned_and_replayed': True, 'both_player_DTO': True,
        'synthetic_scenario': True, 'representative_cards_added': 0,
        'cn_calibrated': False,
    }
    for name, value in (
        ('summary', summary), ('snapshot', game.snapshot()), ('waiting', waiting),
        ('replay', build_replay(game)), ('view1', game.observe(1)), ('view2', game.observe(2)),
    ):
        path = output / (name + '.json')
        with path.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
