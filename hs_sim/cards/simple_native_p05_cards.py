"""Four P05 native roots reuse armor, original residence and summon facts."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.effects import CopyMinion, InvokeBehavior, RandomDamage
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (
    AttackPolicySpec, BoardPresenceReference, CardDefinition, CardType,
    DamageKind, Keyword, StatRelationOperand, StatRelationSpec, TriggerSpec,
)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import BuffCapturedMinion, MinionReference
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import characters

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-native-p05-v1.json'
BATCH_HASH = '3c124993ad05ea62005052fca0841d07c1528deb4bbbd4e5feca3c7b0b95d113'
GAUNTLET = 'CORE_LOOT_044'
DINOSITTER = 'TLC_822'
DODO = 'TIME_703'
HARBINGER = 'TIME_EVENT_300'
PAGETURNER = 'TLC_220'
DOOMSAYER = 'CORE_NEW1_021'
ROOTS = (GAUNTLET, DODO, HARBINGER, PAGETURNER)
PREFIX = 'cards.simple_native_p05.'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(d) != BATCH_HASH:
        raise TargetValidationError('P05 lost its complete reviewed source pin')
    if (tuple(x['record']['id'] for x in d['cards']) != ROOTS or d['dependencies'] or
            tuple(x['record']['id'] for x in d['skipped']) != (DINOSITTER,)):
        raise TargetValidationError('Unreviewed P05 roots or dependencies')
    for key in ('cards', 'dependencies', 'existing_dependencies', 'evidence_only', 'skipped'):
        for row in d[key]:
            if canonical_digest(row['record']) != row['record_sha256']:
                raise TargetValidationError('P05 complete source row changed')
    return d


def register_simple_native_p05_cards(registry):
    d = load_batch()
    existing, = d['existing_dependencies']
    if (existing['record']['id'] != DOOMSAYER or existing['record']['dbf_id'] != 76317 or
            canonical_digest(asdict(registry.card(DOOMSAYER))) != existing['definition_sha256']):
        raise TargetValidationError('P05 requires the exact complete existing Doomsayer76317')

    def dodo(c):
        hero = c.state.entities[c.state.players[c.player_id].hero_id]
        if hero.health > 10 or not living_source(c):
            return ()
        return (BuffCapturedMinion(MinionReference.capture(c.source), 5, 5, c.source_id),
                CopyMinion(BoardPresenceReference.capture(c.state, c.source_id), c.player_id, cause=SummonCause.capture(c)))

    def pageturner(c):
        event = c.event
        if event is None or event.kind != 'minion_summoned':
            raise ResolutionError('Pageturner requires its original successful summon notification')
        if event.player_id != c.player_id:
            return ()
        rows = [row for row in c.state.successful_summon_history if row.event_sequence == event.sequence]
        if len(rows) != 1:
            raise ResolutionError('Pageturner lost its original successful summon occurrence')
        row = rows[0]
        fact = row.minion
        target = c.state.entities[event.target_id]
        if (row.entity_id, row.player_id) != (event.target_id, event.player_id) or (
                target.id, target.card_id, target.controller, target.zone_epoch, target.entered_order) != (
                fact.entity_id, fact.card_id, fact.controller, fact.zone_epoch, fact.entered_order):
            raise ResolutionError('Pageturner borrowed another physical entry or later residence')
        if row.tribes is None:
            raise UnsupportedDefinitionError('Unknown original Elemental summon tribes')
        if not row.tribes.matches_any(('elemental',)):
            return ()
        return (InvokeBehavior(PREFIX+'hit', c.source_id, c.player_id),)

    bodies = {
        'dodo': dodo,
        'harbinger': lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial(DOOMSAYER),), SummonCause.capture(c)),),
        'pageturner': pageturner,
        'hit': lambda c: (RandomDamage(characters(c, registry, 3-c.player_id), 3, c.source_id, DamageKind.MINION_ABILITY),),
    }
    for name, body in bodies.items():
        registry.register_behavior(PREFIX+name, body)
    for row in d['cards']:
        raw = row['record']
        cid = raw['id']
        kind = CardType(raw['type'].lower())
        if raw['collectible'] is not True:
            raise TargetValidationError('P05 roots require reviewed collectible faces')
        kwargs = {}
        if cid == GAUNTLET:
            kwargs.update(durability=raw['health'], stat_relations=(StatRelationSpec(operand=StatRelationOperand.CONTROLLER_ARMOR),),
                          attack_policies=(AttackPolicySpec('cannot_attack_heroes'),))
        elif cid == DODO:
            kwargs.update(keywords=(Keyword.TAUNT,), battlecry=PREFIX+'dodo')
        elif cid == HARBINGER:
            if raw['tags']['COLLECTION_RELATED_CARD_DATABASE_ID'] != existing['record']['dbf_id']:
                raise TargetValidationError('Harbinger lost its exact related Doomsayer identity')
            kwargs['deathrattle'] = PREFIX+'harbinger'
        elif cid == PAGETURNER:
            kwargs['triggers'] = (TriggerSpec('minion_summoned', PREFIX+'pageturner'),)
        card = CardDefinition(
            cid, raw['name'], kind, cost=raw['cost'], attack=raw['attack'] or 0,
            health=raw['health'] if kind == CardType.MINION else 0,
            metadata=replace(metadata_from_record(raw), deck_identity='LOOT_044' if cid == GAUNTLET else cid), **kwargs,
        )
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
