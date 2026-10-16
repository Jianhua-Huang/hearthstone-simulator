"""Complete named deathrattle loop and spell followup, using public effects."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.effects import AddToHand, Damage, DamageBatch
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, SpellSchool
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/fixed-named-followups-v1.json'
BATCH_HASH = '8c3b290d6dca723d566c63373e7b68827e499961153f8e9bf2ee953f9c4fb214'
PREFIX = 'cards.fixed_named_followups.'
BLOODPETAL = 'TLC_234'
SEEDLING = 'TLC_234t'
THUNDERQUAKE = 'TIME_215'
STATIC_SHOCK = 'TIME_218'
ROOTS = (BLOODPETAL, THUNDERQUAKE)


def load_batch():
    value = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(value) != BATCH_HASH:
        raise TargetValidationError('Fixed named followups lost their complete reviewed pin')
    return value


def register_fixed_named_followup_cards(registry):
    data = load_batch()
    if (tuple(row['record']['id'] for row in data['cards']) != ROOTS or
            tuple(row['record']['id'] for row in data['dependencies']) != (SEEDLING,)):
        raise TargetValidationError('Unreviewed named followup family')
    existing, = data['existing_dependencies']
    if (existing['record']['id'] != STATIC_SHOCK or
            canonical_digest(asdict(registry.card(STATIC_SHOCK))) != existing['definition_sha256']):
        raise TargetValidationError('Named followup requires the complete existing Static Shock')
    for row in data['cards'] + data['dependencies'] + data['existing_dependencies'] + data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Named followup source record changed')

    def summon(card_id):
        return lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial(card_id),), SummonCause.capture(c)),)

    registry.register_behavior(PREFIX + 'seedling', summon(SEEDLING))
    registry.register_behavior(PREFIX + 'bloodpetal', summon(BLOODPETAL))
    registry.register_behavior(PREFIX + 'thunderquake', lambda c: (
        DamageBatch(tuple(Damage(eid, 1, c.source_id, DamageKind.SPELL)
                          for player in (c.player_id, 3 - c.player_id) for eid in minions(c, registry, player))),
        AddToHand(c.player_id, STATIC_SHOCK, c.source_id),
    ))
    for row in data['cards'] + data['dependencies']:
        raw = row['record']; cid = raw['id']; kind = CardType(raw['type'].lower())
        if raw['collectible'] != (cid in ROOTS):
            raise TargetValidationError('Named followup collectible identity changed')
        kwargs = ({'on_play': PREFIX + 'thunderquake', 'spell_school': SpellSchool.NATURE}
                  if cid == THUNDERQUAKE else
                  {'deathrattle': PREFIX + ('seedling' if cid == BLOODPETAL else 'bloodpetal')})
        attack = 0 if cid == SEEDLING else raw['attack'] or 0
        definition = CardDefinition(cid, raw['name'], kind, cost=raw['cost'], attack=attack,
                                    health=raw['health'] or 0,
                                    metadata=replace(metadata_from_record(raw), deck_identity=cid), **kwargs)
        registry.register_card(definition)
        registry.register_pool_card(PoolCard.from_definition(definition))
