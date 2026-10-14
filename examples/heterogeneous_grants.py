"""Synthetic public heterogeneous body grants; no official rule calibration.

Run as a module for a real seat-bound JSON command demonstration. This example
uses the same public effects and trusted bindings that extension authors use.
"""
from dataclasses import replace
import json

from hs_sim.engine import (BodyReference, BodyRootTargetBinding, BodyTargetBinding,
    BodyTargetProfile, CardDefinition, CardType, Game, GrantBattlecry, GrantCombo,
    Keyword, PlayerSetup, Registry, Scenario, TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.body_grants import RemoveGrantedBody, ConsumeGrantedBody
from hs_sim.engine.effects import (Buff, ChoiceOption, Damage, Destroy, Draw,
    GainArmor, RandomDamage, RequestChoice, Summon, Silence, Transform,
    ReturnToHand, ChangeControl, CopyMinion)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import (BattlecryRepeatSpec, CardClass, CardMetadata, ComboRepeatSpec,
    RewindSpec)
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard

FRIEND = TargetSpec(TargetMode.IF_AVAILABLE, (Zone.BOARD,), (CardType.MINION,), 'friendly')
ENEMY = replace(FRIEND, mode=TargetMode.REQUIRED, relation='enemy')
HAND = TargetSpec(TargetMode.OPTIONAL, (Zone.HAND,), (CardType.MINION,), 'friendly', True)
FULL_GRANTS = ((GrantBattlecry, 'enemy_body'), (GrantBattlecry, 'hand_body'),
    (GrantBattlecry, 'no_body'), (GrantBattlecry, 'conditional'),
    (GrantBattlecry, 'low'), (GrantBattlecry, 'high'),
    (GrantCombo, 'enemy_combo'), (GrantCombo, 'hand_combo'), (GrantCombo, 'no_combo'))
COMPACT_GRANTS = FULL_GRANTS[:2] + FULL_GRANTS[-1:]


def registry(mode='normal', carrier='minion', variant='complete'):
    r = Registry('heterogeneous-grants-' + mode + '-' + carrier + '-' + variant)
    for profile in ('paid', 'other'):
        r.register_body_target_profile(BodyTargetProfile(profile, 'paid_hand', 'manual', 'pre_payment'))
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=100))
    r.register_card(CardDefinition('friend', 'Friend', CardType.MINION, attack=1, health=20,
        metadata=CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=('mech',))))
    r.register_card(CardDefinition('enemy', 'Enemy', CardType.MINION, attack=1, health=20))
    r.register_card(CardDefinition('fodder', 'Hand card', CardType.MINION, attack=1, health=8))
    r.register_behavior('unsafe_body', lambda c: [])
    r.register_target_rule('unsafe', lambda c: True)

    def body(c):
        effects = [GainArmor(c.player_id, 1)]
        if c.target_id is not None:
            target = c.state.entities[c.target_id]
            effects.append(BuffStoredCard(CardReference.capture(target), attack=1, source_id=c.source_id)
                if target.zone == Zone.HAND else Buff(target.id, attack=1, source_id=c.source_id))
        if mode == 'wait':
            return [RequestChoice(c.player_id, (ChoiceOption('go', 'Continue', tuple(effects)),), c.source_id)]
        if mode == 'fail' and c.combo is not None:
            return [RandomDamage((c.state.players[2].hero_id,), 1, source_id=c.source_id),
                Summon(c.player_id, 'unsupported.heterogeneous')]
        return effects
    r.register_behavior('body', body)
    r.register_behavior('ordinary', lambda c: [Damage(c.target_id, 2, c.source_id)])
    values = dict(battlecry='body', combo='body', targeting=FRIEND, keywords=(Keyword.COMBO,))
    if mode == 'magnetic':
        values.update(keywords=(Keyword.COMBO, Keyword.MAGNETIC), magnetic_tribes=('mech',))
    else:
        values['on_play'] = 'ordinary'
    if mode in ('retained', 'retry'):
        values.update(rewind=RewindSpec(), keywords=(*values['keywords'], Keyword.REWIND))
    if carrier == 'weapon':
        values.pop('combo'); values['keywords'] = ()
        r.register_card(CardDefinition('unit', 'Unit', CardType.WEAPON, cost=2, attack=1, durability=4, **values))
    elif carrier == 'hero':
        r.register_behavior('power', lambda c: [])
        r.register_card(CardDefinition('power', 'Power', CardType.HERO_POWER, cost=2, on_use='power'))
        r.register_card(CardDefinition('unit', 'Unit', CardType.HERO, cost=2, health=100,
            hero_card=True, hero_armor=3, initial_hero_power='power', **values))
    else:
        r.register_card(CardDefinition('unit', 'Unit', CardType.MINION, cost=2, attack=1, health=20, **values))
    for name, domain, condition, threshold, family in (
        ('enemy_body', ENEMY, None, None, 'battlecry'),
        ('hand_body', HAND, None, None, 'battlecry'),
        ('no_body', None, None, None, 'battlecry'),
        ('conditional', replace(ENEMY, mode=TargetMode.IF_AVAILABLE), 'outcast', None, 'battlecry'),
        ('low', replace(ENEMY, mode=TargetMode.IF_AVAILABLE), 'manathirst', 5, 'battlecry'),
        ('high', replace(ENEMY, mode=TargetMode.IF_AVAILABLE), 'manathirst', 9, 'battlecry'),
        ('enemy_combo', ENEMY, None, None, 'combo'),
        ('hand_combo', replace(HAND, mode=TargetMode.IF_AVAILABLE), None, None, 'combo'),
        ('no_combo', None, None, None, 'combo')):
        fields = {family: 'body', 'targeting': domain, 'target_condition': condition, 'manathirst': threshold}
        if family == 'combo': fields['keywords'] = (Keyword.COMBO,)
        if condition is not None: fields['keywords'] = (*fields.get('keywords', ()), Keyword(condition))
        if variant == 'custom_body' and name == 'enemy_body': fields['target_rule'] = 'unsafe'
        r.register_card(CardDefinition(name, name, CardType.MINION, health=8, **fields))
    grants = COMPACT_GRANTS if mode in ('wait', 'compact', 'magnetic') else FULL_GRANTS
    def source(c):
        return next(e for e in c.state.entities.values() if e.card_id == 'unit' and e.controller == c.player_id
            and e.zone in (Zone.HAND, Zone.DECK, Zone.BOARD, Zone.HERO, Zone.WEAPON))
    def setup(c):
        e = source(c)
        return [effect(BodyReference.capture(e), name, c.source_id,
            expires_turn=c.state.turn if mode == 'expiry' else None) for effect, name in grants]
    r.register_behavior('setup', setup)
    def spell(name, behavior, targeted=False):
        r.register_behavior(name, behavior)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, requires_target=targeted))
    r.register_card(CardDefinition('setup', 'Setup', CardType.SPELL, on_play='setup'))
    spell('tempo', lambda c: [GainArmor(c.player_id, 1)])
    spell('copy', lambda c: [CopyCard(CardReference.capture(source(c)), c.player_id, source_id=c.source_id)])
    spell('base_copy', lambda c: [CopyCard(CardReference.capture(source(c)), c.player_id, mode='base', source_id=c.source_id)])
    spell('hide', lambda c: [MoveCard(CardReference.capture(source(c)), c.player_id, Zone.DECK, position='top', source_id=c.source_id)])
    spell('draw', lambda c: [Draw(c.player_id, 1)])
    for name, operation in (('remove', RemoveGrantedBody), ('consume', ConsumeGrantedBody)):
        def mutate(c, operation=operation):
            e = source(c)
            a = next(a for a in e.abilities if a.kind == 'battlecry' and a.origin == 'granted' and not a.consumed)
            return [operation(BodyReference.capture(e), a.id, 'battlecry', c.source_id)]
        spell(name, mutate)
    spell('silence', lambda c: [Silence(c.target_id)], True)
    spell('transform', lambda c: [Transform(c.target_id, 'friend')], True)
    spell('return', lambda c: [ReturnToHand(c.target_id)], True)
    spell('control', lambda c: [ChangeControl(c.target_id, 2)], True)
    spell('board_copy', lambda c: [CopyMinion(c.target_id, c.player_id)], True)
    spell('duplicate', lambda c: [GrantBattlecry(BodyReference.capture(source(c)), 'enemy_body', c.source_id)])
    if mode == 'repeat':
        r.register_card(CardDefinition('repeater', 'Repeater', CardType.MINION, health=20,
            battlecry_repeats=(BattlecryRepeatSpec(2),), combo_repeats=(ComboRepeatSpec(3),)))
    if mode == 'retained':
        r.register_card(CardDefinition('holder', 'Holder', CardType.MINION, health=20, retain_rewind_outcomes=True))
    if mode == 'magnetic':
        def depart(c):
            e = c.state.entities.get(c.event.source_id)
            return [Destroy(c.state.players[1].board[0])] if e and e.card_id == 'unit' else []
        r.register_behavior('host_depart', depart)
        r.register_card(CardDefinition('watcher', 'Watcher', CardType.MINION, health=20,
            triggers=(TriggerSpec('card_committed', 'host_depart'),)))
    if variant != 'profile_only':
        for name in ('unit', *(name for _, name in FULL_GRANTS)):
            for family in ('battlecry', 'combo'):
                if getattr(r.card(name), family) is None: continue
                if variant == 'missing_printed' and (name, family) == ('unit', 'combo'): continue
                if variant == 'missing_new' and name == 'enemy_body': continue
                options = {}
                if name == 'enemy_body':
                    if variant == 'wrong_origin': options['origins'] = ('printed',)
                    if variant == 'wrong_kind': options['carrier_kinds'] = (CardType.WEAPON,)
                    if variant == 'wrong_card': options['carrier_card_ids'] = ('friend',)
                profile = 'other' if variant == 'different_profile' and name == 'enemy_body' else 'paid'
                r.register_body_target_binding(BodyTargetBinding(name, family, profile, **options))
    if variant != 'missing_root':
        r.register_body_root_target_binding(BodyRootTargetBinding('unit', 'paid', 'body_only')
            if mode == 'magnetic' else BodyRootTargetBinding('unit', 'paid', 'explicit_root', ENEMY,
                target_rule='unsafe' if variant == 'custom_root' else 'any_entity'))
    return r


def scenario(mode='normal', *, zone='hand', enemy_card='enemy', enemy_board=('enemy', 'enemy'),
             empty_friend=False, outcast=False):
    hand = ('setup', *((() if outcast else ('fodder',))), *((('unit',) if zone == 'hand' else ())),
            'fodder', 'tempo', 'copy', 'hide', 'draw', 'remove', 'consume')
    board = () if empty_friend else ('friend',)
    if zone == 'board': board += ('unit',)
    if mode == 'repeat': board += ('repeater',)
    if mode == 'retained': board += ('holder',)
    if mode == 'magnetic' and zone == 'depart': board += ('watcher',)
    if zone == 'depart': hand = ('setup', 'unit', 'fodder')
    return Scenario((PlayerSetup('hero', hand=hand, board=board,
        deck=('unit', 'fodder') if zone == 'deck' else ('fodder',), mana=6, max_mana=6),
        PlayerSetup('hero', hand=(enemy_card,), board=enemy_board, deck=('fodder',), mana=6, max_mana=6)), seed=37)


def card_ref(game, name='unit', index=0):
    cards = game.for_player(1).observe()['observation']['players'][0]['hand']
    return [c for c in cards if c.get('card_id') == name][index]['ref']


def command(game, card=None, position=None, *, optional_none=False):
    port = game.for_player(1)
    options = port.independent_targets(card or card_ref(game), position=position)
    if options['error'] is not None or not options['choices']:
        raise ValueError('No complete current target route: ' + str(options['error']))
    choice = options['choices'][0]
    bodies = []
    for body in choice['bodies']:
        values = body['targets']
        selected = values[0] if optional_none else next((v for v in values if v is not None), None)
        bodies.append({'body': body['body'], 'target': selected})
    action = {'type': 'play_card', 'card': choice['card'], 'target': choice['root_targets'][0], 'body_targets': bodies}
    if position is not None: action['position'] = position
    return {'revision': options['revision'], 'action': action}


def main():
    game = Game.from_scenario(scenario(), registry())
    port = game.for_player(1)
    initial = game.snapshot()
    commands = []
    setup = {'revision': port.observe()['revision'], 'action': {'type': 'play_card', 'card': card_ref(game, 'setup')}}
    commands.append(setup)
    assert port.submit(setup)['accepted']
    commands.append(command(game))
    assert port.submit(commands[-1])['accepted']
    print(json.dumps({'initial': initial, 'commands': commands, 'final': game.snapshot(),
        'observations': [game.for_player(i).observe() for i in (1, 2)]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
