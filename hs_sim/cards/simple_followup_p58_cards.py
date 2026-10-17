"""Corrupted dreams, original carriers, staged discovery and native hand progress."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.effects import Damage, DamageBatch, GrantDeathrattle, InvokeBehavior, ShuffleIntoDeck
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardDefinition, CardType, CostSpec, DamageKind,
    HandActionSpec, HandProgressSpec, Keyword, KeywordAuraSpec, SpellSchool, TargetSpec, Zone)
from hs_sim.engine.pools import DiscoverFromPool, GenerateFromPool, PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.sacrifice import BuffCapturedMinion, GrantCapturedKeyword, MinionReference
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference, FillHandWithCard, ModifyStoredCost
from hs_sim.targets import TargetValidationError, canonical_digest
from .entry_native_cards import PREFIX as ENTRY_PREFIX
from .metadata import metadata_from_record
from .native_followup_cards import characters, deathrattle_position, minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p58-v1.json'
BATCH_HASH = 'cb2fd22e5240837202e037463078f056f5d1f140644d6adb4ee8f408fa8e4303'
NIGHTMARE, DREAM, SISTER, AWAKENING = ('EDR_846t1', 'EDR_846t2', 'EDR_846t3', 'EDR_846t4')
HOOKTAIL, CHEST, ULFARR, LIFESOURCE, STRIKER, ORDINANCE = ('TIME_713', 'TIME_713t', 'CORE_CATA_006', 'TIME_448', 'CATA_551', 'JAIL_735')
ROOTS = (NIGHTMARE, DREAM, SISTER, AWAKENING, HOOKTAIL, CHEST, ULFARR, LIFESOURCE, STRIKER, ORDINANCE)
EXISTING = ('EDR_846t5', 'CATA_551t', 'GAME_005')
PARENT, PREFIX, POOL_ID = 'EDR_846', 'cards.simple_followup_p58.', 'constructed.cards'
DISCOVERY = PoolQuery(kinds=(CardType.MINION,), collectible=True, class_mode='current')
EIGHTS = PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=8, max_cost=8)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != ROOTS
            or tuple(x['record']['id'] for x in data['existing_dependencies']) != EXISTING
            or tuple(x['record']['id'] for x in data['evidence_only']) != (PARENT,)
            or data['dependencies'] or data['skipped']):
        raise TargetValidationError('P58 complete reviewed identities changed')
    for row in data['cards'] + data['existing_dependencies'] + data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('P58 complete original source row changed')
    return data


def register_simple_followup_p58_cards(registry):
    data = load_batch()
    for cid, pin in data['existing_dependency_definition_pins'].items():
        if canonical_digest(asdict(registry.card(cid))) != pin:
            raise TargetValidationError('P58 exact existing dependency definition changed: ' + cid)

    def nightmare(c):
        ref = MinionReference.capture(c.state.entities[c.target_id])
        return (BuffCapturedMinion(ref, 5, 5, c.source_id),
            GrantCapturedKeyword(ref, Keyword.IMMUNE, c.source_id, c.state.turn))

    def dream(c):
        target = c.state.entities[c.target_id]
        ref = MinionReference.capture(target)
        return shuffled(c, (ShuffleIntoDeck(ref.entity_id, target.owner),), player_id=target.owner)

    def ulfarr(c):
        return tuple(GrantDeathrattle(i, PREFIX + 'carrier_rattle', c.source_id)
            for i in minions(c, registry, c.player_id) if i != c.source_id)

    def carrier_rattle(c):
        if c.deathrattle is None:
            raise ResolutionError('Ulfarr grant requires its actual original carrier invocation')
        cost = registry.card(c.deathrattle.card_id).cost
        return (SummonFromPool(c.player_id, POOL_ID, PoolQuery(kinds=(CardType.MINION,),
            collectible=True, min_cost=cost, max_cost=cost), source_id=c.source_id,
            cause=SummonCause.capture(c), position=deathrattle_position(c)),)

    def lifesource_after(c):
        if any(c.state.entities[i].kind == CardType.MINION for i in c.state.players[c.player_id].deck):
            return ()
        refs = tuple(CardReference.capture(c.state.entities[i]) for i in c.state.players[c.player_id].hand
            if c.state.entities[i].kind == CardType.MINION)
        return tuple(ModifyStoredCost(ref, CostSpec(delta=-2, card_types=(CardType.MINION,)), c.source_id) for ref in refs)

    def ordinance(c):
        if c.cast is None:
            raise ResolutionError('Ordinance requires its actual original spell cast')
        count = sum(d.id != c.cast.id and d.player_id == c.player_id and d.turn == c.state.turn
            and d.completed and d.payload_started and not d.interrupted and d.failure is None
            for d in c.state.cast_history)
        return (GenerateFromPool(c.player_id, POOL_ID, EIGHTS, count=2 if count >= 3 else 1,
            destination='board', source_id=c.source_id, cause=SummonCause.capture(c)),)

    bodies = {NIGHTMARE: nightmare, DREAM: dream,
        AWAKENING: lambda c: (DamageBatch(tuple(Damage(i, 5, c.source_id, DamageKind.SPELL)
            for i in characters(c, registry, 3-c.player_id))),),
        HOOKTAIL: lambda c: (SummonByCard(3-c.player_id, (SummonEntryMaterial(CHEST),), SummonCause.capture(c)),),
        CHEST: lambda c: (FillHandWithCard(3-c.player_id, 'GAME_005', c.source_id),),
        ULFARR: ulfarr, 'carrier_rattle': carrier_rattle,
        LIFESOURCE: lambda c: (DiscoverFromPool(c.player_id, POOL_ID, DISCOVERY, source_id=c.source_id,
            discoveries=2), InvokeBehavior(PREFIX + 'lifesource_after', c.source_id, c.player_id)),
        'lifesource_after': lifesource_after, ORDINANCE: ordinance}
    for name, body in bodies.items():
        registry.register_behavior(PREFIX + name, body)
    for row in data['cards']:
        raw = row['record']; cid = raw['id']; kind = CardType(raw['type'].lower()); kwargs = {}
        if kind == CardType.SPELL:
            kwargs['on_play'] = PREFIX + cid
            if cid in (NIGHTMARE, DREAM, AWAKENING): kwargs['spell_school'] = SpellSchool.SHADOW
            if cid == ORDINANCE: kwargs['spell_school'] = SpellSchool.ARCANE
        if cid in (NIGHTMARE, DREAM): kwargs['targeting'] = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
        if cid in (HOOKTAIL, ULFARR): kwargs['battlecry'] = PREFIX + cid
        if cid == CHEST: kwargs['deathrattle'] = PREFIX + cid
        if cid == SISTER:
            kwargs.update(keywords=(Keyword.ELUSIVE,), keyword_auras=(KeywordAuraSpec(Keyword.ELUSIVE, 'friendly_hero'),))
        if cid == STRIKER:
            kwargs.update(keywords=(Keyword.TAUNT,), hand_progress=HandProgressSpec('event', 1, 'CATA_551t',
                event='card_committed', condition_id=ENTRY_PREFIX + 'dragon'))
        if cid == ORDINANCE: kwargs['hand_actions'] = (HandActionSpec('prepare', 'prepare', 1),)
        def numeric(field):
            value = raw[field]
            return data['numeric_normalizations'][cid][field] if value is None else value
        card = CardDefinition(cid, raw['name'], kind, cost=numeric('cost'),
            attack=numeric('attack') if kind == CardType.MINION else 0,
            health=numeric('health') if kind == CardType.MINION else 0,
            metadata=metadata_from_record(raw), **kwargs)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
