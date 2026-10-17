"""Ordinary bilateral summons, transformations and complete Rafaam leaves."""
import json
from pathlib import Path

from hs_sim.engine.cross_zone import (BuffMinionsInZones, MinionScope,
    TransformCapturedMinion, TransformMinionsInZones)
from hs_sim.engine.effects import (AddCostModifier, CopyMinion, Damage,
    DamageBatch, GainArmor, InvokeBehavior)
from hs_sim.engine.model import (BoardPresenceReference, CardDefinition, CardType,
    CostSpec, DamageKind, Keyword, Zone)
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import ChooseFromZone, DrawMatching
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p70-v1.json'
BATCH_HASH = '042b1436d4e63c4290bdc10960bf716eb68827efd047c80d7101ee4cb8f795fe'
MULTIVERSE, BRIBE = 'TIME_014', 'JAIL_EVENT_102'
TINY, GREEN, EXPLORER, WARCHIEF, MINDFLAYER, CALAMITOUS, MURLOC, ARCHMAGE = (
    'TIME_005t' + str(i) for i in (1, 2, 3, 4, 5, 6, 8, 9))
SHEEP, PARENT, GIANT = 'TIME_005t9t', 'TIME_005', 'TIME_005t7'
COLLECTIBLE_ROOTS = (BRIBE,)
DEPENDENCIES = (TINY, GREEN, EXPLORER, WARCHIEF, MINDFLAYER, CALAMITOUS, MURLOC, ARCHMAGE, SHEEP)
ROOTS, FAMILY = COLLECTIBLE_ROOTS + DEPENDENCIES, (PARENT,) + tuple('TIME_005t' + str(i) for i in range(1, 10)) + (SHEEP,)
PREFIX, POOL_ID = 'cards.simple_followup_p70.', 'constructed.cards'
MINIONS = PoolQuery(kinds=(CardType.MINION,), collectible=True)


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != COLLECTIBLE_ROOTS
            or tuple(x['record']['id'] for x in d['dependencies']) != DEPENDENCIES
            or d['existing_dependencies'] or d['skipped'] or set(d['rafaam_family_ids']) != set(FAMILY)):
        raise TargetValidationError('P70 complete source scope changed')
    for key in ('cards', 'dependencies', 'evidence_only'):
        for row in d[key]:
            if canonical_digest(row['record']) != row['record_sha256']:
                raise TargetValidationError('P70 complete original raw changed')
            if (row['record']['id'] in FAMILY) != (row['record']['tags'].get('3928') == 1):
                raise TargetValidationError('P70 exact original Rafaam family changed')
    return d


def register_simple_followup_p70_cards(registry):
    d = load_batch()

    def bribe(c):
        query = PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=2, max_cost=2)
        cause = SummonCause.capture(c)
        return (GenerateFromPool(c.player_id, POOL_ID, query, count=2, source_id=c.source_id,
                    destination='board', cause=cause),
                GenerateFromPool(3-c.player_id, POOL_ID, query, count=2, source_id=c.source_id,
                    destination='board', cause=cause),
                TransformMinionsInZones(c.player_id, POOL_ID, 1, scope=MinionScope(zones=(Zone.BOARD,)),
                    source_id=c.source_id))

    def family_query():
        # Recompute against the final immutable assembly, including definitions
        # registered after this adapter. The named family itself is fixed data.
        return PoolQuery(kinds=(CardType.MINION,), exclude_card_ids=tuple(sorted(cid for cid in registry.cards if cid not in FAMILY)))

    def held(c):
        return any(c.state.entities[i].card_id in FAMILY and i != c.source_id for i in c.state.players[c.player_id].hand)

    def tiny(c):
        return (DrawMatching(c.player_id, family_query(), 'skip', source_id=c.source_id),)

    def green(c):
        return (BuffMinionsInZones(c.player_id, 2, 2,
            MinionScope((Zone.HAND, Zone.BOARD), family_query(), exclude_source=True), c.source_id),)

    def explorer(c):
        return (ChooseFromZone(c.player_id, c.player_id, Zone.DECK, family_query(), operation='take',
            distinct='entity', source_id=c.source_id,discovery=True),)

    def mindflayer(c):
        return (CopyMinion(BoardPresenceReference.capture(c.state, c.source_id), c.player_id,
            cause=SummonCause.capture(c)),) if living_source(c) and held(c) else ()

    def calamitous(c):
        return (DamageBatch(tuple(Damage(i, 6, c.source_id, DamageKind.MINION_ABILITY)
            for p in (1, 2) for i in minions(c, registry, p) if c.state.entities[i].card_id not in FAMILY)),)

    def archmage(c):
        return tuple(TransformCapturedMinion(MinionReference.capture(c.state.entities[i]), SHEEP, c.source_id)
            for p in (1, 2) for i in minions(c, registry, p) if c.state.entities[i].card_id not in FAMILY)

    bodies = dict(bribe=bribe,
        tiny=tiny, green=green, explorer=explorer, mindflayer=mindflayer, calamitous=calamitous, archmage=archmage,
        warchief=lambda c:(GainArmor(c.player_id, 5), InvokeBehavior(PREFIX + 'more_armor', c.source_id, c.player_id)),
        more_armor=lambda c:(GainArmor(c.player_id, 5),) if held(c) else (),
        murloc=lambda c:(AddCostModifier(c.player_id, CostSpec(delta=-3, card_ids=FAMILY),
            uses_remaining=1, source_id=c.source_id),))
    for name, body in bodies.items(): registry.register_behavior(PREFIX + name, body)
    scripts = {BRIBE:'bribe', TINY:'tiny', GREEN:'green', EXPLORER:'explorer',
        WARCHIEF:'warchief', MINDFLAYER:'mindflayer', CALAMITOUS:'calamitous', MURLOC:'murloc', ARCHMAGE:'archmage'}
    for row in d['cards'] + d['dependencies']:
        raw = row['record']; cid = raw['id']; kind = CardType(raw['type'].lower()); kwargs = {}
        if cid in scripts: kwargs['on_play' if kind == CardType.SPELL else 'battlecry'] = PREFIX + scripts[cid]
        if cid == TINY: kwargs['deathrattle'] = PREFIX + 'tiny'
        if cid == MINDFLAYER: kwargs['keywords'] = (Keyword.TAUNT,)
        if kind == CardType.SPELL: kwargs['spell_school'] = SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL'))
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'], attack=raw['attack'] or 0,
            health=raw['health'] or 0, metadata=metadata_from_record(raw), **kwargs)
        registry.register_card(card)
        if cid not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
