"""Aviana reuses genuine owner intervals, exact program consumption and costs."""
import json
from pathlib import Path

from hs_sim.engine.effects import AddCostModifier
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType, CostSpec, PlayerEffectSpec, TriggerSpec
from hs_sim.engine.owner_turns import current_owner_turn
from hs_sim.engine.player_effects import AddPlayerEffect, ConsumePlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'EDR_895'
PREFIX = 'cards.aviana_lunar_cycle.'
PROGRAM = PREFIX+'countdown'
TURNS = 3
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/aviana-lunar-cycle-v1.json'
BATCH_HASH = '1684c8b9ccc20e8c6ec637162290e707c19113738bef0bb33f7bff911857cab9'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            tuple(x['record']['id'] for x in data['evidence_only']) != ('EDR_895e','EDR_895t') or
            data['dependencies'] or data['existing_dependencies'] or data['skipped']):
        raise TargetValidationError('Aviana requires her complete original lunar source records')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete original Aviana lunar record')
    if data['evidence_only'][1]['record']['tags'].get('TAG_SCRIPT_DATA_NUM_1') != TURNS:
        raise TargetValidationError('Aviana changed the original three-turn lunar countdown')
    return data


def register_aviana_lunar_cycle_card(registry):
    def deadline(c):
        if c.event is None or c.event.kind != 'turn_started' or c.event.player_id != c.player_id:
            return ()
        instance = c.player_effect
        if instance is None or instance.spec_id != PROGRAM:
            raise ResolutionError('Lunar cycle lost its original persistent instance')
        interval = current_owner_turn(c.state)
        if (interval.origin != 'actual' or interval.turn != dict(c.event.data).get('turn') or
                interval.publication_event not in (None,c.event.sequence) or
                c.event.sequence <= interval.start_event):
            return ()
        original = max((row.owner_index for row in c.state.owner_turn_history
            if row.player_id == c.player_id and row.turn <= instance.created_turn), default=0)
        if interval.owner_index-original < TURNS:
            return ()
        return (ConsumePlayerEffect(c.player_id, instance,
            (AddCostModifier(c.player_id, CostSpec(set_to=1), source_id=instance.source_id),)),)
    registry.register_behavior(PREFIX+'deadline',deadline)
    registry.register_behavior(PREFIX+'begin',lambda c:(AddPlayerEffect(c.player_id,PROGRAM,c.source_id),))
    registry.register_player_effect(PlayerEffectSpec(PROGRAM,CARD,
        triggers=(TriggerSpec('turn_started',PREFIX+'deadline'),)))
    raw = load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('BATTLECRY')) != ('MINION',9,7,11,1):
        raise TargetValidationError('Aviana changed her complete original printed body')
    card = CardDefinition(CARD,raw['name'],CardType.MINION,cost=9,attack=7,health=11,
        battlecry=PREFIX+'begin',metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
