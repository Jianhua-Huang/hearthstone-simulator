"""Cosmic Manifestations repeats its damage and original semantic shuffle."""
import json
from pathlib import Path

from hs_sim.engine.effects import Damage
from hs_sim.engine.model import CardClass, CardDefinition, CardType, DamageKind, Keyword, SpellSchool, TargetSpec, Zone
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/cosmic-manifestation-v1.json'
BATCH_HASH = '9b0dbd67e8e6c4ae95bbe3908b1c36d01db5c9018a8766ac96ad25f1f07ec65b'
COSMIC = 'JAIL_892'
POOL_ID = 'constructed.cards'
BODY = 'cards.cosmic_manifestation.cast'
QUERY = PoolQuery(kinds=(CardType.SPELL,), collectible=True, class_mode='specified',
                  classes=(CardClass.DEMON_HUNTER,), include_neutral=False)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (COSMIC,) or
            any(data[k] for k in ('dependencies','existing_dependencies','evidence_only','skipped'))):
        raise TargetValidationError('Cosmic Manifestations requires its complete reviewed source')
    for row in data['cards']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Cosmic Manifestations original row is incomplete')
    return data


def body(context):
    if context.spell_conditions is None:
        raise ValueError('Cosmic Manifestations needs original accepted Outcast conditions')
    effects = (Damage(context.target_id, 2, context.source_id, DamageKind.SPELL),
        GenerateFromPool(context.player_id, POOL_ID, QUERY, source_id=context.source_id,
            destination='deck', shuffle_actor_id=context.player_id))
    return effects * (2 if context.spell_conditions.outcast else 1)


def register_cosmic_manifestation_cards(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['tags'].get('CLASS'),raw['tags'].get('SPELL_SCHOOL'),
            raw['tags'].get('OUTCAST')) != ('SPELL',2,14,6,1):
        raise TargetValidationError('Cosmic Manifestations lost its Demon Hunter Shadow Outcast face')
    registry.register_behavior(BODY, body)
    card = CardDefinition(COSMIC, raw['name'], CardType.SPELL, cost=2, metadata=metadata_from_record(raw),
        keywords=(Keyword.OUTCAST,), spell_school=SpellSchool.SHADOW, on_play=BODY,
        targeting=TargetSpec(zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION)))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
