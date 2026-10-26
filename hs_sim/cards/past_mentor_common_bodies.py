"""Six actual past-teacher dependencies, using ordinary shared effects."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.cross_zone import BuffMinionsInZones, MinionScope
from hs_sim.engine.effects import Draw, GainArmor, Heal, HealBatch, InvokeBehavior
from hs_sim.engine.model import (CardDefinition, CardType, HandDerivativeSpec,
    HealingKind, Keyword, SummonStats)
from hs_sim.engine.ordered_group_batches import FillBoardWithCard
from hs_sim.engine.pools import PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.spell_casts import active_cast
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import characters

ROOTS = ('ONY_021', 'TSC_656', 'GVG_033', 'SCH_609', 'DMF_732', 'DAL_256')
DEPENDENCIES = ('ONY_001t', 'TSC_656t', 'DAL_256t2', 'DAL_256ts')
PREFIX = 'cards.past_mentor_common.'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/past-mentor-common-bodies-v1.json'
BATCH_HASH = '9988abaa7f0de536de5016c8715df10fc5a78dec74ad662edbb800f8eb090ffa'
EIGHT_COST = PoolQuery(kinds=(CardType.MINION,), min_cost=8, max_cost=8, collectible=True)


def load_batch():
    value = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(value) != BATCH_HASH or value['schema'] != 1 or
            tuple(row['record']['id'] for row in value['cards']) != ROOTS or
            tuple(row['record']['id'] for row in value['dependencies']) != DEPENDENCIES or
            value['formal_pool_complete'] is not False or value['cn_calibrated'] is not False or
            len(value['official_faces']) != 20 or
            any(canonical_digest(row['record']) != row['record_sha256']
                for row in value['cards']+value['dependencies'])):
        raise TargetValidationError('Past teacher dependencies lost their exact complete original scope')
    return value


def register_past_mentor_common_bodies(registry):
    data = load_batch(); rows = {row['record']['id']: row['record']
        for row in data['cards']+data['dependencies']}
    if any(cid in registry.cards for cid in rows):
        raise TargetValidationError('Past teacher dependencies must not replace existing native cards')
    for source, token in (('ONY_021', 'ONY_001t'), ('TSC_656', 'TSC_656t'), ('DAL_256', 'DAL_256t2')):
        if rows[source]['tags'].get('COLLECTION_RELATED_CARD_DATABASE_ID') != rows[token]['dbf_id']:
            raise TargetValidationError('Past spell lost its exact referenced physical token')

    def cause(c):
        record = active_cast(c.state, c.source_id, c.player_id)
        if (record is None or not record.payload_started or record.failure is not None or
                record.card_id not in (*ROOTS, 'DAL_256ts')):
            raise UnsupportedDefinitionError('Past spell summon requires its original active CAST')
        return SummonCause.capture(replace(c, cast=record))

    def plant(c):
        # Draw effects and their reactions finish before the queued body reads
        # the hand. Burned cards do not increase its actual size.
        size = len(c.state.players[c.player_id].hand)
        material = SummonEntryMaterial('TSC_656t', stats=SummonStats(size, size))
        return (SummonByCard(c.player_id, (material,), cause(c)),)

    def heal_all(c):
        ids = tuple(i for player in (1, 2) for i in characters(c, registry, player))
        return (HealBatch(tuple(Heal(i, c.state.entities[i].max_health,
            c.source_id, HealingKind.SPELL) for i in ids)),)

    def treants(c):
        request = SummonByCard(c.player_id, (SummonEntryMaterial('DAL_256t2'),), cause(c))
        return (request,)*5

    bodies = {
        'ONY_021': lambda c: (FillBoardWithCard(c.player_id, 'ONY_001t', cause(c)),),
        'TSC_656': lambda c: (Draw(c.player_id, 3, c.source_id),
            InvokeBehavior(PREFIX+'plant', c.source_id, c.player_id)),
        'plant': plant,
        'GVG_033': heal_all,
        'SCH_609': lambda c: (BuffMinionsInZones(c.player_id, 4, 4, MinionScope(), c.source_id),),
        'DMF_732': lambda c: (GainArmor(c.player_id, 8),
            SummonFromPool(c.player_id, 'constructed.minions', EIGHT_COST, c.source_id, cause=cause(c))),
        'DAL_256': treants,
        'DAL_256ts': treants,
    }
    for name, body in bodies.items(): registry.register_behavior(PREFIX+name, body)
    for cid, raw in rows.items():
        kind = CardType(raw['type'].lower())
        if kind == CardType.MINION:
            keys = tuple(Keyword(key.lower()) for key in ('RUSH', 'TAUNT') if raw['tags'].get(key)==1)
            card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'], attack=raw['attack'],
                health=raw['health'], keywords=keys, metadata=metadata_from_record(raw))
        else:
            twin = cid=='DAL_256'
            card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'], on_play=PREFIX+cid,
                spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')), metadata=metadata_from_record(raw),
                keywords=(Keyword.TWINSPELL,) if twin else (),
                hand_derivatives=(HandDerivativeSpec(Keyword.TWINSPELL, 'DAL_256ts'),) if twin else ())
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
