"""Five real P02 roots and their four exact official named summon dependencies."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import InvokeBehavior, RandomDamage
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.kindred import repeat_components, request
from hs_sim.engine.model import (
    CardDefinition, CardType, DamageKind, HealthFlow, KindredProfile, Keyword,
    TriggerSpec, Zone,
)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion, MinionReference
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import completed_attack
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import characters

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p02-v1.json'
BATCH_HASH = '76e84f31d2d21de433e6f615c8a33705c3031df760989c895c122891bb010b8b'
CROOK = 'EDR_416'
MIRROR = 'TIME_006'
DOOMSPEAKER = 'TIME_008'
PREDATORS = 'TLC_519'
DEFENSES = 'TLC_622'
BLAZE = 'CATA_586'
SHEEP = 'EDR_416t'
MAGE = 'TIME_006t1'
SPITTER = 'TLC_519t'
SECURITY = 'TLC_622t'
ROOTS = (CROOK, MIRROR, PREDATORS, DEFENSES, BLAZE)
SKIPPED_ROOTS = (DOOMSPEAKER,)
DEPENDENCIES = (SHEEP, SECURITY, SPITTER, MAGE)
PREFIX = 'cards.simple_followup_p02.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('P02 lost its reviewed complete source pin')
    if (tuple(row['record']['id'] for row in data['cards']) != ROOTS or
            tuple(row['record']['id'] for row in data['dependencies']) != DEPENDENCIES or
            data['existing_dependencies'] or
            tuple(row['record']['id'] for row in data['skipped']) != SKIPPED_ROOTS):
        raise TargetValidationError('Unreviewed P02 root or named dependency set')
    for row in data['cards'] + data['dependencies'] + data['evidence_only'] + data['skipped']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('P02 complete source row changed')
    return data


def register_simple_followup_p02_cards(registry):
    data = load_batch()

    def summon(c, cid):
        return SummonByCard(c.player_id, (SummonEntryMaterial(cid),), SummonCause.capture(c))

    def follow(c, name):
        return InvokeBehavior(PREFIX + name, c.source_id, c.player_id, c.target_id,
                              None if c.play is None else c.play.id)

    def crook(c):
        row = completed_attack(c)
        if row is None or row.source_kind != CardType.HERO or row.declaration.player_id != c.player_id:
            return ()
        return (summon(c, SHEEP),)

    def mirror_extra(c):
        if not any(has_any_tribe(registry, c.state.entities[i], ('dragon',))
                   for i in c.state.players[c.player_id].hand):
            return ()
        return (summon(c, MAGE),)

    def damaged_source(c):
        result = c.health_result
        if result is None:
            raise ResolutionError('P02 damage trigger requires its original health result')
        source = c.source
        if (result.flow != HealthFlow.DAMAGE.value or result.damage_dealt <= 0 or
                result.target_id != c.source_id or source.kind != CardType.MINION or
                source.zone != Zone.BOARD or not source.active or source.health <= 0 or source.doomed or
                (result.target_zone_epoch, result.target_entered_order) != (source.zone_epoch, source.entered_order)):
            return None
        return result

    def security(c):
        return (BuffCapturedMinion(MinionReference.capture(c.source), 1, 0, c.source_id),) if damaged_source(c) else ()

    def blaze(c):
        result = damaged_source(c)
        if result is None or result.health_after <= 0 or result.doomed_after:
            return ()
        return (summon(c, BLAZE),)

    bodies = {
        'crook': crook,
        'mirror': lambda c: (summon(c, MAGE), follow(c, 'mirror_extra')),
        'mirror_extra': mirror_extra,
        'predators': lambda c: request(c, PREDATORS),
        'predators_prepare': lambda c: (summon(c, SPITTER), *repeat_components(c)),
        'predators_active': lambda c: (summon(c, SPITTER),),
        'defenses': lambda c: (summon(c, SECURITY), summon(c, SECURITY)),
        'security': security,
        'blaze': blaze,
        'blaze_death': lambda c: (RandomDamage(characters(c, registry, 3-c.player_id),
                                               2, c.source_id, DamageKind.MINION_ABILITY),),
    }
    for name, body in bodies.items():
        registry.register_behavior(PREFIX + name, body)
    for row in data['cards'] + data['dependencies']:
        raw = row['record']
        cid = raw['id']
        kind = CardType(raw['type'].lower())
        if raw['collectible'] != (cid in ROOTS):
            raise TargetValidationError('P02 collectible identity changed')
        kwargs = {}
        if cid == CROOK:
            kwargs.update(durability=raw['health'], triggers=(TriggerSpec('attack_finished', PREFIX+'crook'),))
        elif cid in (MIRROR, PREDATORS, DEFENSES):
            kwargs['on_play'] = PREFIX + {MIRROR: 'mirror', PREDATORS: 'predators', DEFENSES: 'defenses'}[cid]
        elif cid == BLAZE:
            kwargs.update(triggers=(TriggerSpec('health_resolved', PREFIX+'blaze'),), deathrattle=PREFIX+'blaze_death')
        elif cid == SHEEP:
            kwargs['dormant_turns'] = 2
        elif cid == MAGE:
            kwargs['keywords'] = (Keyword.TAUNT,)
        elif cid == SPITTER:
            kwargs['keywords'] = (Keyword.STEALTH, Keyword.POISONOUS)
        elif cid == SECURITY:
            kwargs.update(keywords=(Keyword.TAUNT,), triggers=(TriggerSpec('health_resolved', PREFIX+'security'),))
        card = CardDefinition(
            cid, raw['name'], kind, cost=raw['cost'], attack=raw['attack'] or 0,
            health=raw['health'] if kind == CardType.MINION else 0,
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),
            metadata=replace(metadata_from_record(raw), deck_identity=cid), **kwargs,
        )
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_kindred_profile(KindredProfile(
        PREDATORS, 'body', PREFIX+'predators', active=PREFIX+'predators_active', prepare=PREFIX+'predators_prepare',
    ))
