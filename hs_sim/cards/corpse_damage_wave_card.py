"""Bloodfiend consumes one original capped debit, then ordinary damage waves."""
import json
from pathlib import Path

from hs_sim.engine.effects import Damage, DamageBatch, InvokeBehavior
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, Resource
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.resource_operations import SpendUpToResource
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

CARD = 'BE_283'
PREFIX = 'cards.corpse_damage_waves.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/corpse-damage-waves-v1.json'
BATCH_HASH = 'c84982073e60c39fb6ed70b935f6e1eee8476760cec2d6683807f925cb6e5c0f'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Bloodfiend requires its complete original capped-corpse source')
    return data


def register_corpse_damage_wave_card(registry):
    def spent(c):
        result = c.resource_result
        if result is None or (result.player_id, result.resource, result.cap, result.source_id) != (
                c.player_id, Resource.CORPSES, 4, c.source_id):
            raise ResolutionError('Bloodfiend requires its original complete capped-corpse result')
        return tuple(InvokeBehavior(PREFIX+'wave', c.source_id, c.player_id) for _ in range(result.actual_amount))

    def wave(c):
        return (DamageBatch(tuple(Damage(eid, 1, c.source_id, DamageKind.MINION_ABILITY)
            for player in (1, 2) for eid in minions(c, registry, player) if eid != c.source_id)),)

    registry.register_behavior(PREFIX+'body', lambda c: (
        SpendUpToResource(c.player_id, Resource.CORPSES, 4, c.source_id, PREFIX+'spent'),))
    registry.register_behavior(PREFIX+'spent', spent)
    registry.register_behavior(PREFIX+'wave', wave)
    raw = load_batch()['cards'][0]['record']
    if ((raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('BATTLECRY'),
            raw['tags'].get('COST_BLOOD'), raw['tags'].get('CORPSE_SPENDER')) != ('MINION', 4, 4, 4, 1, 3, 1)):
        raise TargetValidationError('Bloodfiend lost its real triple-Blood Battlecry face')
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'], health=raw['health'],
        battlecry=PREFIX+'body', metadata=metadata_from_record(raw))
    registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
