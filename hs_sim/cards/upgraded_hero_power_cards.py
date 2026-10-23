"""Eleven upgraded starting powers required by Standard Genn's Worgen face."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.effects import (Buff, ChoiceOption, Damage, Destroy, Draw, EquipWeapon,
    GainArmor, Heal, RequestChoice)
from hs_sim.engine.model import (CardDefinition, CardType, DamageKind, EndTurnSpec,
    HealingKind, Keyword, TargetSpec, TriggerSpec)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.hero_power_values import armor_effect as hero_power_armor
from hs_sim.targets import TargetValidationError, canonical_digest
from .basic_hero_roles import TOTEMS
from .metadata import metadata_from_record

UPGRADES = {f'HERO_{i:02}bp': f'HERO_{i:02}bp2' for i in range(1, 12)}
POWERS = tuple(UPGRADES.values())
DAGGER, GHOUL, RECRUIT = 'AT_132_ROGUEt', 'HERO_11bp2t', 'CS2_101t'
PREFIX = 'cards.upgraded_hero_power.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/upgraded-hero-powers-v1.json'
BATCH_HASH = '9a36c90eb839121f2e13fd3bee11e6d2d9a6f4ab32cee47cfe6a6560469ba416'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != POWERS or
            tuple(x['record']['id'] for x in data['dependencies']) != (DAGGER, GHOUL)):
        raise TargetValidationError('Unreviewed complete upgraded power family')
    for row in data['cards'] + data['dependencies'] + data['existing_dependencies']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete original upgraded power dependency')
    return data


def register_upgraded_hero_power_cards(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        raw = row['record']
        if canonical_digest(asdict(registry.card(raw['id']))) != row['definition_sha256']:
            raise TargetValidationError('Upgraded power changed an original basic dependency')
    def summon(c, ids):
        cause = SummonCause.capture(c)
        return tuple(SummonByCard(c.player_id, (SummonEntryMaterial(cid),), cause) for cid in ids)
    def totems(c):
        options = tuple(ChoiceOption(cid, registry.card(cid).name, summon(c, (cid,))) for cid in TOTEMS)
        return (RequestChoice(c.player_id, options, c.source_id),)
    def attack(c, armor=0):
        return (Buff(c.state.players[c.player_id].hero_id, attack=2,
            source_id=c.source_id, expires_turn=c.state.turn), *(() if not armor else (hero_power_armor(c, armor, registry),)))
    bodies = {
        POWERS[0]: lambda c: (hero_power_armor(c, 4, registry),),
        POWERS[1]: totems,
        POWERS[2]: lambda c: (EquipWeapon(c.player_id, DAGGER),),
        POWERS[3]: lambda c: summon(c, (RECRUIT, RECRUIT)),
        POWERS[4]: lambda c: (Damage(c.state.players[3-c.player_id].hero_id if c.target_id is None else c.target_id,
            3, c.source_id, DamageKind.HERO_POWER),),
        POWERS[5]: lambda c: attack(c, 2),
        POWERS[6]: lambda c: (Draw(c.player_id),),
        POWERS[7]: lambda c: (Damage(c.target_id, 2, c.source_id, DamageKind.HERO_POWER),),
        POWERS[8]: lambda c: (Heal(c.target_id, 4, c.source_id, HealingKind.HERO_POWER),),
        POWERS[9]: attack,
        POWERS[10]: lambda c: summon(c, (GHOUL,)),
    }
    registry.register_behavior(PREFIX+'ghoul_end', lambda c: (Destroy(c.source_id, c.source_id),))
    for cid, body in bodies.items(): registry.register_behavior(PREFIX+cid, body)
    for row in data['cards'] + data['dependencies']:
        raw = row['record']; cid = raw['id']; kwargs = {}
        if cid in POWERS:
            kwargs['on_use'] = PREFIX+cid
            if cid in (POWERS[1], POWERS[3], POWERS[10]): kwargs['requires_board_space'] = True
            if cid in (POWERS[7], POWERS[8]): kwargs['targeting'] = TargetSpec()
        if cid == GHOUL:
            kwargs.update(keywords=(Keyword.CHARGE,), triggers=(TriggerSpec('turn_ended',
                PREFIX+'ghoul_end', EndTurnSpec()),))
        definition = CardDefinition(cid, raw['name'], CardType[raw['type']], cost=raw['cost'],
            attack=raw['attack'] or 0, health=(raw['health'] or 0) if cid != DAGGER else 0,
            durability=raw['health'] if cid == DAGGER else 0,
            metadata=replace(metadata_from_record(raw), deck_identity=cid), **kwargs)
        registry.register_card(definition); registry.register_pool_card(PoolCard.from_definition(definition))
