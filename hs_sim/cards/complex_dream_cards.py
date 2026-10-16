"""Complete complex Dream dependencies; the five-card source is separate."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import Damage, DamageBatch
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, SpellSchool, TargetSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import (BuffCapturedMinionWithStartTrigger,
    DestroyCapturedMinion, MinionReference)
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import characters

AWAKENS = 'DREAM_02'
NIGHTMARE = 'DREAM_05'
PREFIX = 'cards.complex_dream.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/complex-dream-v1.json'
BATCH_HASH = '7d20598e54b231ee2c12dad4ff628a4416a4d71c1d9babf7c65e1572f327731d'
YSERA_IDS = frozenset(('CORE_VAN_EX1_572', 'CS3_033', 'DRG_320', 'EDR_000',
    'EX1_572', 'LEG_CS3_033', 'Story_07_Ysera', 'VAN_EX1_572'))


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Complex Dream lost its complete source pin')
    if data['cards'] or tuple(x['record']['id'] for x in data['dependencies']) != (AWAKENS, NIGHTMARE):
        raise TargetValidationError('Unreviewed complex Dream family')
    for group in ('dependencies', 'evidence_only', 'ysera_exclusion_source'):
        for row in data[group]:
            if canonical_digest(row['record']) != row['record_sha256']:
                raise TargetValidationError('Complex Dream lost a complete source row')
    if frozenset(x['record']['id'] for x in data['ysera_exclusion_source']) != YSERA_IDS:
        raise TargetValidationError('Unreviewed exact Ysera exclusion family')
    return data


def register_complex_dream_cards(registry):
    data = load_batch()

    def awakens(c):
        return (DamageBatch(tuple(Damage(i, 5, c.source_id, DamageKind.SPELL)
            for player in (1, 2) for i in characters(c, registry, player)
            if c.state.entities[i].card_id not in YSERA_IDS)),)

    def nightmare(c):
        target = c.state.entities.get(c.target_id)
        if (target is None or target.kind != CardType.MINION or target.zone != Zone.BOARD
                or not target.active or target.health <= 0 or target.doomed):
            return ()
        return (BuffCapturedMinionWithStartTrigger(MinionReference.capture(target), 5, 5,
            PREFIX + 'due.' + str(c.player_id), c.source_id, PREFIX + 'actor.' + str(c.player_id)),)

    def due(c, caster):
        if c.event.player_id != caster or not living_source(c):
            return ()
        if (c.trigger is None or c.trigger.kind != 'limited_trigger'
                or c.trigger.limited_trigger.event != 'turn_started'
                or c.trigger.limited_trigger.behavior_id != PREFIX + 'due.' + str(caster)
                or c.trigger.source_id is None):
            raise ResolutionError('Nightmare lost its original removable start attachment')
        return (DestroyCapturedMinion(MinionReference.capture(c.source), c.trigger.source_id),)

    registry.register_behavior(PREFIX + 'awakens', awakens)
    registry.register_behavior(PREFIX + 'nightmare', nightmare)
    registry.register_behavior(PREFIX + 'due.1', lambda c: due(c, 1))
    registry.register_behavior(PREFIX + 'due.2', lambda c: due(c, 2))
    registry.register_trigger_condition(PREFIX + 'actor.1', lambda c: c.event.player_id == 1)
    registry.register_trigger_condition(PREFIX + 'actor.2', lambda c: c.event.player_id == 2)
    for row in data['dependencies']:
        raw = row['record']; cid = raw['id']
        if raw['type'] != 'SPELL' or raw['collectible']:
            raise TargetValidationError('Complex Dream requires its original noncollectible spell')
        if cid == AWAKENS:
            if raw['cost'] != 2: raise TargetValidationError('Unreviewed Awakens cost')
            kwargs = dict(cost=raw['cost'], on_play=PREFIX + 'awakens', spell_school=SpellSchool.NATURE)
        else:
            if raw['cost'] is not None or 'COST' in raw['tags']:
                raise TargetValidationError('Nightmare must preserve its missing raw cost')
            kwargs = dict(on_play=PREFIX + 'nightmare', spell_school=SpellSchool.SHADOW,
                targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)))
        card = CardDefinition(cid, raw['name'], CardType.SPELL,
            metadata=replace(metadata_from_record(raw), deck_identity=cid), **kwargs)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
