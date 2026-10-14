"""Synthetic bound magnetic materials reserve independent normal-entry targets."""
from dataclasses import replace
import json, sys
from hs_sim.engine import (BodyReference, BodyRootTargetBinding, BodyTargetBinding,
    BodyTargetProfile, CardDefinition, CardType, Game, GrantBattlecry, GrantCombo,
    Keyword, PlayerSetup, Registry, Scenario, TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (Buff, ChoiceOption, Damage, Destroy, GainArmor,
    RandomDamage, RequestChoice, Summon, Transform)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CardClass, CardMetadata
from hs_sim.engine.zones import CardReference

FRIEND = TargetSpec(TargetMode.IF_AVAILABLE, (Zone.BOARD,), (CardType.MINION,), 'friendly')
ENEMY = replace(FRIEND, mode=TargetMode.REQUIRED, relation='enemy')
HAND = TargetSpec(TargetMode.OPTIONAL, (Zone.HAND,), (CardType.MINION,), 'friendly')


def registry(mode='accepted'):
    r = Registry('magnetic-independent-root-' + mode)
    r.register_body_target_profile(BodyTargetProfile('paid', 'paid_hand', 'manual', 'pre_payment'))
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=100))
    r.register_card(CardDefinition('friend', 'Host', CardType.MINION, attack=1, health=20,
        metadata=CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=('mech',))))
    r.register_card(CardDefinition('enemy', 'Enemy', CardType.MINION, attack=1, health=20))
    r.register_card(CardDefinition('fodder', 'Hand target', CardType.MINION, attack=1, health=8))
    r.register_card(CardDefinition('nonmech', 'Non-host', CardType.MINION, attack=1, health=20,
        metadata=CardMetadata(collectible=False, classes=(CardClass.NEUTRAL,), rarity=None, tribes=())))
    def body(c):
        effects = [GainArmor(c.player_id, 1)]
        if c.target_id is not None:
            target = c.state.entities[c.target_id]
            effects.append(BuffStoredCard(CardReference.capture(target), attack=1, source_id=c.source_id)
                if target.zone == Zone.HAND else Buff(target.id, attack=1, source_id=c.source_id))
        return [RequestChoice(c.player_id, (ChoiceOption('go', 'Continue', tuple(effects)),), c.source_id)] if mode == 'body_wait' else effects
    r.register_behavior('body', body)
    r.register_behavior('ordinary', lambda c: [Damage(c.target_id, 2, c.source_id)]
        if c.target_id is not None else [GainArmor(c.player_id, 2)])
    r.register_card(CardDefinition('material', 'Material', CardType.MINION, cost=2, attack=1, health=20,
        battlecry='body', combo='body', on_play='ordinary', targeting=FRIEND,
        keywords=(Keyword.COMBO, Keyword.MAGNETIC), magnetic_tribes=('mech',)))
    r.register_card(CardDefinition('enemy_body', 'Enemy body', CardType.MINION, health=3, battlecry='body', targeting=ENEMY))
    r.register_card(CardDefinition('hand_body', 'Hand body', CardType.MINION, health=3, battlecry='body', targeting=HAND))
    r.register_card(CardDefinition('no_combo', 'Untargeted combo', CardType.MINION, health=3,
        combo='body', keywords=(Keyword.COMBO,)))
    def setup(c):
        source = next(c.state.entities[i] for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == 'material')
        reference = BodyReference.capture(source)
        return [GrantBattlecry(reference, 'enemy_body', c.source_id),
            GrantBattlecry(reference, 'hand_body', c.source_id), GrantCombo(reference, 'no_combo', c.source_id)]
    r.register_behavior('setup', setup)
    r.register_card(CardDefinition('setup', 'Setup', CardType.SPELL, on_play='setup'))
    for name, family in (('material', 'battlecry'), ('material', 'combo'),
                        ('enemy_body', 'battlecry'), ('hand_body', 'battlecry'), ('no_combo', 'combo')):
        r.register_body_target_binding(BodyTargetBinding(name, family, 'paid', carrier_card_ids=('material',)))
    root = BodyRootTargetBinding('material', 'paid', 'explicit_root', ENEMY)
    if mode == 'conditional': root = replace(root, target_condition='manathirst', manathirst_threshold=9)
    r.register_body_root_target_binding(root)
    def react(c):
        if c.event.source_id is None or c.state.entities[c.event.source_id].card_id != 'material': return []
        host = c.state.players[c.player_id].board[0]
        if mode == 'choose':
            return [RequestChoice(c.player_id, (ChoiceOption('keep', 'Keep host', ()),
                ChoiceOption('depart', 'Remove host', (Destroy(host),))), c.source_id)]
        if mode == 'blocked': return [Transform(host, 'nonmech')]
        if mode == 'fail': return [RandomDamage((c.state.players[2].hero_id,), 1, source_id=c.source_id),
            Summon(c.player_id, 'unsupported.magnetic.root')]
        return [Destroy(host)]
    r.register_behavior('react', react)
    if mode in ('departure', 'body_wait', 'choose', 'blocked', 'conditional', 'fail'):
        r.register_card(CardDefinition('watcher', 'Watcher', CardType.MINION, health=20,
            triggers=(TriggerSpec('magnetized' if mode == 'fail' else 'card_committed', 'react'),)))
    return r


def scenario(mode='accepted', *, full=False, reverse=False, enemy_card='enemy'):
    watch = ('watcher',) if mode in ('departure', 'body_wait', 'choose', 'blocked', 'conditional', 'fail') else ()
    board = ('friend',) * (7 - len(watch) if full else 1) + watch
    if reverse: board = tuple(reversed(board))
    return Scenario((PlayerSetup('hero', hand=('setup', 'material', 'fodder'), board=board,
        mana=6, max_mana=6), PlayerSetup('hero', board=('enemy',), hand=(enemy_card,), mana=6, max_mana=6)), seed=37)


def card_ref(game, name):
    return next(c['ref'] for c in game.for_player(1).observe()['observation']['players'][0]['hand'] if c.get('card_id') == name)


def command(game, position=0):
    port = game.for_player(1)
    options = port.independent_targets(card_ref(game, 'material'), position=position)
    if options['error'] is not None or not options['choices']: raise ValueError('No actual bound magnetic route')
    choice = options['choices'][0]
    body_targets = [{'body': b['body'], 'target': next((v for v in b['targets'] if v is not None), None)} for b in choice['bodies']]
    return {'revision': options['revision'], 'action': {'type': 'play_card', 'card': choice['card'],
        'target': choice['root_targets'][0], 'position': position, 'body_targets': body_targets}}


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'departure'
    game = Game.from_scenario(scenario(mode, full=mode == 'blocked'), registry(mode))
    initial = game.snapshot(); commands = []; positions = []
    port = game.for_player(1)
    commands.append({'revision': port.observe()['revision'], 'action': {'type': 'play_card', 'card': card_ref(game, 'setup')}})
    assert port.submit(commands[-1])['accepted']
    commands.append(command(game)); assert port.submit(commands[-1])['accepted']
    positions.append({'after_commands': len(commands), 'snapshot': game.snapshot(),
        'observations': [game.for_player(i).observe() for i in (1, 2)]})
    while game.state.pending_choice is not None:
        legal = port.legal_actions(); assert legal['error'] is None
        commands.append({'revision': legal['revision'], 'action': legal['actions'][-1]})
        assert port.submit(commands[-1])['accepted']
        positions.append({'after_commands': len(commands), 'snapshot': game.snapshot(),
            'observations': [game.for_player(i).observe() for i in (1, 2)]})
    print(json.dumps({'mode': mode, 'initial': initial, 'commands': commands, 'positions': positions,
        'final': game.snapshot()}, ensure_ascii=False))


if __name__ == '__main__': main()
