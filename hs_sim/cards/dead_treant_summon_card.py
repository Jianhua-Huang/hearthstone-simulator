"""Splintered Reality queries real deaths and rewards its exact summon receipts."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import InvokeBehavior
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType, SpellSchool, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.successful_summons import BuffSummonedMinion
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

SPELL, TREANT = 'END_009', 'END_009t'
PREFIX = 'cards.dead_treant_summon.'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/dead-treant-summon-card-v1.json'
BATCH_HASH = 'be8cff33f612b212ab534f3261a3f1998d91b997cc2a383a177c7e15aef914b1'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['cards']+data['existing_dependencies']+data['evidence_only']
    if (canonical_digest(data) != BATCH_HASH or [x['record']['id'] for x in data['cards']] != [SPELL]
            or [x['record']['id'] for x in data['existing_dependencies']] != [TREANT]
            or data['dependencies'] or data['skipped']
            or any(canonical_digest(x['record']) != x['record_sha256'] for x in rows)):
        raise TargetValidationError('Splintered Reality lost its complete reviewed source')
    family = data['treant_family']
    actual = sorted(x['record']['id'] for x in rows if x['record']['tags'].get('2831') == 1)
    if (family['numeric_tag'], family['value'], sorted(family['card_ids'])) != ('2831', 1, actual):
        raise TargetValidationError('Treant classification differs from the complete pinned evidence')
    return data


def original_cast(c):
    cast = c.cast
    if (cast is None or cast not in c.state.cast_history or cast.card_id != SPELL
            or (cast.source_id, cast.player_id) != (c.source_id, c.player_id)
            or cast.completed or cast.interrupted or not cast.payload_started):
        raise ResolutionError('Splintered Reality requires its original active cast')
    return cast


def original_summon_ids(c):
    """Read producer and entry receipts, never names or final board positions."""
    cast = original_cast(c)
    roots = [x for x in c.state.card_summon_history if x.request.cause.cast_id == cast.id]
    if len(roots) != 2:
        raise ResolutionError('Splintered Reality lost its two original summon requests')
    ids = []
    for root in roots:
        cause = root.request.cause
        if (root.status not in ('completed', 'skipped')
                or root.request.materials != (SummonEntryMaterial(TREANT),)
                or (cause.origin, cause.source.entity_id, cause.player_id, cause.cast_card_id)
                != ('spell_cast', c.source_id, c.player_id, SPELL)):
            raise ResolutionError('Splintered Reality borrowed an unrelated summon request')
        for delivery in root.deliveries:
            if delivery.entity is None:
                continue
            f = delivery.entity
            matches = [row.id for row in c.state.successful_summon_history
                       if (row.entity_id, row.minion.zone_epoch, row.minion.entered_order)
                       == (f.entity_id, f.zone_epoch, f.entered_order) and row.player_id == c.player_id]
            if len(matches) != 1:
                raise ResolutionError('Splintered Reality lost an original successful entry')
            ids.extend(matches)
    if len(ids) != len(set(ids)):
        raise ResolutionError('Splintered Reality duplicated an original entry')
    return tuple(ids)


def register_dead_treant_summon_card(registry):
    data = load_batch()
    dependency = data['existing_dependencies'][0]
    if canonical_digest(asdict(registry.card(TREANT))) != dependency['definition_sha256']:
        raise TargetValidationError('Splintered Reality changed its existing exact Treant')
    family = frozenset(data['treant_family']['card_ids'])

    def summon(c):
        original_cast(c)
        request = SummonByCard(c.player_id, (SummonEntryMaterial(TREANT),), SummonCause.capture(c))
        return (request, request, InvokeBehavior(PREFIX+'reward', c.source_id, c.player_id))

    def reward(c):
        ids = original_summon_ids(c)
        amount = sum(d.zone == Zone.BOARD and d.controller == c.player_id and d.card_id in family
                     for d in c.state.death_history)
        return tuple(BuffSummonedMinion(c.player_id, i, c.source_id, amount, amount)
                     for i in ids) if amount else ()

    registry.register_behavior(PREFIX+'summon', summon)
    registry.register_behavior(PREFIX+'reward', reward)
    raw = data['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['tags'].get('SPELL_SCHOOL')) != ('SPELL', 4, 4):
        raise TargetValidationError('Splintered Reality lost its real Nature spell face')
    card = CardDefinition(SPELL, raw['name'], CardType.SPELL, cost=raw['cost'],
                          spell_school=SpellSchool.NATURE, on_play=PREFIX+'summon',
                          metadata=metadata_from_record(raw))
    registry.register_card(card)
    if SPELL not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
