"""Two real private hand offers use separate original-card and name consumers."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import AddToHand
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_inspection import (InspectHandCards, RememberHandForDeathrattle,
    DiscardRememberedHand, selected_hand)
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.model import (CardDefinition, CardType, HandInvestigation,
    NativeDeathrattleSpec, PlayerEffectSpec, TriggerSpec, Zone)
from hs_sim.engine.owner_turns import current_owner_turn, owner_turn_index
from hs_sim.engine.player_effects import AddPlayerEffect, ConsumePlayerEffect
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_deathrattle_memory_cards import memory

AUGUR, HOLMES, COIN = 'JAIL_303', 'JAIL_851', 'GAME_005'
ROOTS = (AUGUR, HOLMES)
PREFIX = 'cards.private_hand_inspection.'
PROGRAM = PREFIX + 'investigation'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/private-hand-inspection-v1.json'
BATCH_HASH = 'ea85cdd828170f18a633145c5fc3611758f8a30161c84df2c02c8c331bd88177'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != ROOTS or
            tuple(x['record']['id'] for x in data['existing_dependencies']) != (COIN,) or
            tuple(x['record']['id'] for x in data['evidence_only']) != ('JAIL_303e', 'JAIL_851e', 'JAIL_851e1') or
            data['dependencies'] or data['skipped']):
        raise TargetValidationError('Private hand inspection lost its complete original scope')
    for section in ('cards', 'existing_dependencies', 'evidence_only'):
        for row in data[section]:
            if canonical_digest(row['record']) != row['record_sha256']:
                raise TargetValidationError('Incomplete original private hand inspection source')
    return data


def register_private_hand_inspection_cards(registry):
    data = load_batch()
    if canonical_digest(asdict(registry.card(COIN))) != data['existing_dependency_definition_pins'][COIN]:
        raise TargetValidationError('Investigation changed its existing complete Coin definition')

    def augur(c):
        source = c.source
        material = dict(source=None, abilities=[])
        if source.kind == CardType.MINION and source.zone == Zone.BOARD and source.active:
            material = dict(source=asdict(MinionReference.capture(source)), abilities=[a.id
                for a in active_abilities(source, 'deathrattle') if a.deathrattle_memory is not None
                and a.deathrattle_memory.spec.kind == 'hand_selection'])
        return (InspectHandCards(c.player_id, 3 - c.player_id, 3, c.source_id,
            PREFIX + 'remember', json.dumps(material, sort_keys=True)),)

    def remember(c):
        card, entry, material = selected_hand(c)
        if set(material) != {'source', 'abilities'}:
            raise ResolutionError('Native hand choice lost its original source material')
        if material['source'] is None:
            return ()
        return (RememberHandForDeathrattle(card, entry.id, MinionReference(**material['source']),
            tuple(material['abilities'])),)

    def discard(c):
        return tuple(DiscardRememberedHand(c.deathrattle.id, identity)
            for identity in memory(c, 'hand_selection').hand_entry_ids)

    def investigate(c):
        card, entry, material = selected_hand(c)
        if material:
            raise ResolutionError('Investigation received unrelated native selection material')
        target = HandInvestigation(card.card_id, entry.id, 3 - c.player_id,
            owner_turn_index(c.state, 3 - c.player_id) + 1)
        return (AddPlayerEffect(c.player_id, PROGRAM, c.source_id, investigation=target),)

    def watch(c):
        instance = c.player_effect
        if instance is None or instance.spec_id != PROGRAM or instance.investigation is None:
            raise ResolutionError('Investigation lost its original private program')
        target = instance.investigation
        interval = current_owner_turn(c.state)
        if interval.player_id != target.opponent_id:
            return ()
        if interval.owner_index > target.owner_turn_index or (
                interval.owner_index == target.owner_turn_index and c.event.kind == 'turn_ended'):
            return (ConsumePlayerEffect(c.player_id, instance, ()),)
        if interval.owner_index != target.owner_turn_index or c.event.kind != 'card_played':
            return ()
        played = play_record(c.state, dict(c.event.data)['play_id'])
        if played.player_id != target.opponent_id or registry.card(played.card_id).name != registry.card(target.card_id).name:
            return ()
        return (ConsumePlayerEffect(c.player_id, instance,
            tuple(AddToHand(c.player_id, COIN, instance.source_id) for _ in range(3))),)

    bodies = dict(augur=augur, remember=remember, discard=discard, investigate=investigate, watch=watch,
        holmes=lambda c: (InspectHandCards(c.player_id, 3 - c.player_id, 4, c.source_id, PREFIX + 'investigate'),))
    for name, body in bodies.items():
        registry.register_behavior(PREFIX + name, body)
    registry.register_player_effect(PlayerEffectSpec(PROGRAM, HOLMES, kind='hand_investigation',
        triggers=tuple(TriggerSpec(event, PREFIX + 'watch') for event in ('turn_started', 'turn_ended', 'card_played'))))
    for row in data['cards']:
        raw = row['record']; cid = raw['id']
        expected = (4, 2, 6) if cid == AUGUR else (4, 4, 5)
        if (raw['type'], raw['cost'], raw['attack'], raw['health']) != ('MINION', *expected):
            raise TargetValidationError('Private hand card changed its original printed body')
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=4, attack=expected[1], health=expected[2],
            battlecry=PREFIX + ('augur' if cid == AUGUR else 'holmes'),
            deathrattle=PREFIX + 'discard' if cid == AUGUR else None,
            native_deathrattle=NativeDeathrattleSpec('hand_selection') if cid == AUGUR else None,
            metadata=metadata_from_record(raw))
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
