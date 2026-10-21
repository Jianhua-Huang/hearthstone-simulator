"""Flame Shock uses the accepted spell arrows and ordinary health/mana effects."""
import json
from pathlib import Path

from hs_sim.engine.effects import Damage, DamageBatch, Overload
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, SpellSchool, TargetSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.spell_target_groups import SpellTargetGroupProfile, target_ids
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'BE_302'
BODY = 'cards.flame_shock.damage'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/flame-shock-v1.json'
BATCH_HASH = '2f73b3efa93a58c835acc1ecd56caf335a52c48d03b07da26ff0190130ff8203'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in data['cards'])):
        raise TargetValidationError('Flame Shock lost its complete reviewed original face')
    return data


def register_flame_shock_card(registry):
    raw = load_batch()['cards'][0]['record']
    if ((raw['type'], raw['cost'], raw['collectible'], raw['tags'].get('CLASS'),
            raw['tags'].get('RARITY'), raw['tags'].get('SPELL_SCHOOL')) != ('SPELL', 1, True, 8, 3, 2) or
            not any(x['tag'] == 'ReferencedTag' and x['attributes'].get('enumID') == '215' and
                x['attributes'].get('name') == 'OVERLOAD' and x['attributes'].get('value') == '1'
                for x in raw['unmapped_xml_nodes'])):
        raise TargetValidationError('Flame Shock requires its original Shaman Fire spell and Overload one')
    def body(c):
        hits = tuple(Damage(i, 2, c.source_id, DamageKind.SPELL) for i in target_ids(c))
        return (*((DamageBatch(hits),) if hits else ()), Overload(c.player_id, 1))
    registry.register_behavior(BODY, body)
    card = CardDefinition(CARD, raw['name'], CardType.SPELL, cost=1, spell_school=SpellSchool.FIRE,
        on_play=BODY, targeting=TargetSpec(relation='enemy'), metadata=metadata_from_record(raw))
    registry.register_card(card)
    # Exact two manual arrows is an explicit local profile pending CN shortage
    # calibration. No unknown raw tag is interpreted as a target-count rule.
    registry.register_spell_target_group_profile(SpellTargetGroupProfile(
        CARD, 'flame-shock-two-enemies-local-v1', shortfall='reject'))
    registry.register_pool_card(PoolCard.from_definition(card))
