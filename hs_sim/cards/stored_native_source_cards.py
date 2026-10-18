"""Two actual native consumers share physical removal and granted parameters."""
import json
from pathlib import Path

from hs_sim.engine.consumed_cards import (ConsumptionProfile, ConsumeHandSpell,
    ConsumeDeckMinion, ResolveConsumedDeathrattle)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.model import CardDefinition, CardType, EndTurnSpec, TargetMode, TargetSpec, TriggerSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CLOUD, ANCIENT = 'CATA_563', 'EDR_494'
PREFIX = 'cards.stored_native_source.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/stored-native-source-cards-v1.json'
BATCH_HASH = 'ffa76aee969c0c1241bc5b2c7654aceb28ec218119bb71ff372af716e2bb8782'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CLOUD, ANCIENT)
            or any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped'))
            or any(canonical_digest(x['record']) != x['record_sha256'] for x in data['cards'])):
        raise TargetValidationError('Stored native consumers lost their complete original source')
    return data


def register_stored_native_source_cards(registry):
    def spell_four(c):
        target = c.state.entities.get(c.target_id)
        return (target is not None and target.zone == Zone.HAND and target.kind == CardType.SPELL
            and target.controller == c.player_id and quote_unselected_cost(c.state, registry, target).amount <= 4)
    def absorb(c):
        if c.target_id is None or c.source.zone != Zone.BOARD:
            return ()
        target = c.state.entities[c.target_id]
        if target.zone != Zone.HAND or target.kind != CardType.SPELL or target.controller != c.player_id:
            return ()
        return (ConsumeHandSpell(MinionReference.capture(c.source), CardReference.capture(target), CLOUD),)
    def eat(c):
        if c.source.zone != Zone.BOARD:
            return ()
        return (ConsumeDeckMinion(MinionReference.capture(c.source), ANCIENT),)
    def payload(c):
        if c.deathrattle is None:
            raise ValueError('Consumed native body requires its actual Deathrattle')
        if c.deathrattle.ability.consumed_card_id is None:
            return ()
        return (ResolveConsumedDeathrattle(c.deathrattle.id),)
    registry.register_target_rule(PREFIX + 'spell_four', spell_four)
    registry.register_behavior(PREFIX + 'absorb', absorb)
    registry.register_behavior(PREFIX + 'eat', eat)
    registry.register_behavior(PREFIX + 'payload', payload)
    for item in load_batch()['cards']:
        row = item['record']
        cid = row['id']
        expected = (3, 4, 3) if cid == CLOUD else (8, 6, 7)
        if row['type'] != 'MINION' or (row['cost'], row['attack'], row['health']) != expected or row['tags'].get('DEATHRATTLE') != 1:
            raise TargetValidationError('Stored native consumer changed its original face')
        fields = dict(battlecry=PREFIX + 'absorb', target_rule=PREFIX + 'spell_four',
            targeting=TargetSpec(TargetMode.IF_AVAILABLE, zones=(Zone.HAND,), kinds=(CardType.SPELL,), relation='friendly')) if cid == CLOUD else dict(
            triggers=(TriggerSpec('turn_ended', PREFIX + 'eat', end_turn=EndTurnSpec()),))
        card = CardDefinition(cid, row['name'], CardType.MINION, cost=row['cost'], attack=row['attack'], health=row['health'],
            deathrattle=PREFIX + 'payload', metadata=metadata_from_record(row), **fields)
        registry.register_card(card)
        registry.register_consumption_profile(ConsumptionProfile(cid, 'hand_spell' if cid == CLOUD else 'deck_minion'))
        if cid not in registry.pool_cards:
            registry.register_pool_card(PoolCard.from_definition(card))
