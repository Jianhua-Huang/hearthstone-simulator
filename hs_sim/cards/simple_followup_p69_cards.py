"""Physical Shred casts, native hand progress and independent Aura clocks."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.allocation_facts import allocation_from_dict
from hs_sim.engine.deck_shuffles import ShuffleDeckCards
from hs_sim.engine.effects import (AddToHand, ChoiceOption, CopyMinion, Heal, HealBatch,
    RandomDamageBatch, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.model import (BoardPresenceReference, CardDefinition, CardType,
    DamageKind, EndTurnSpec, HandActionSpec, HandProgressSpec, HealingKind, Keyword,
    PlayerEffectSpec, PlayerPlayedClassCostSpec, TriggerSpec, Zone)
from hs_sim.engine.player_effects import AddPlayerEffect, ConsumePlayerEffect
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.sacrifice import (BuffCapturedMinion, GrantCapturedKeyword,
    MinionReference, live_minion)
from hs_sim.engine.spell_casts import CastStoredSpell
from hs_sim.engine.spell_history import CastFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.engine.zones import AddToDeck, CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import characters, minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p69-v1.json'
BATCH_HASH = '28baa1980d97504c949d060256323ad0f5e5404ccb79c0dc9e3c8c4241391a22'
TIMEHOPPER, FATEBREAKER, VELOCIDRAKE, REINFORCEMENT, STAND, SPRITE, PHOENIX = (
    'TIME_025', 'TIME_028', 'TIME_029', 'JAIL_327', 'CATA_498', 'MEND_100', 'FIR_919')
BULB, GNOMISH, MEKKATORQUE = 'MEND_100t', 'TIME_009t1', 'TIME_009t2'
SHRED = 'TIME_025t'
COLLECTIBLE_ROOTS = (TIMEHOPPER, FATEBREAKER, VELOCIDRAKE, REINFORCEMENT, STAND, SPRITE, PHOENIX)
DEPENDENCIES = (BULB, GNOMISH, MEKKATORQUE)
ROOTS = COLLECTIBLE_ROOTS + DEPENDENCIES
PREFIX, POOL_ID = 'cards.simple_followup_p69.', 'constructed.cards'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != COLLECTIBLE_ROOTS
            or tuple(x['record']['id'] for x in d['dependencies']) != DEPENDENCIES
            or tuple(x['record']['id'] for x in d['existing_dependencies']) != (SHRED,) or d['skipped']):
        raise TargetValidationError('P69 complete original scope changed')
    if any(canonical_digest(x['record']) != x['record_sha256'] for key in
            ('cards', 'dependencies', 'existing_dependencies', 'evidence_only') for x in d[key]):
        raise TargetValidationError('P69 complete original source changed')
    return d


def automatic(c, material, callback):
    return RequestChoice(c.player_id, (ChoiceOption(json.dumps(material, sort_keys=True), 'Original material'),),
        c.source_id, min_count=0, max_count=0, on_select=PREFIX + callback)


def original(c):
    if c.choice is None or c.choice.selected_ids or len(c.choice.choice.options) != 1:
        raise ResolutionError('P69 automatic callback lost its complete original material')
    return json.loads(c.choice.choice.options[0].id)


def register_simple_followup_p69_cards(registry):
    d = load_batch()
    pin = d['existing_dependency_definition_pins'][SHRED]
    if canonical_digest(asdict(registry.card(SHRED))) != pin['sha256']:
        raise TargetValidationError('P69 requires its complete existing Shred definition')

    def shreds(c):
        return (ShuffleDeckCards(c.player_id, c.player_id,
            tuple(AddToDeck(c.player_id, SHRED, source_id=c.source_id) for _ in range(2)), c.source_id),)

    def deck_cast(c):
        material = dict(beneficiary=asdict(MinionReference.capture(c.source)),
            cause=asdict(SummonCause.capture(c)), previous=[row.id for row in c.state.cast_history])
        options = tuple(ChoiceOption(json.dumps(dict(material, card=asdict(CardReference.capture(e))), sort_keys=True),
            'Original physical Shred') for i in c.state.players[c.player_id].deck
            for e in (c.state.entities[i],) if e.card_id == SHRED and e.zone == Zone.DECK and e.controller == c.player_id)
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
            sample_size=1, on_select=PREFIX + 'selected_shred'),) if options else ()

    def selected_shred(c):
        m = original(c); ref = dict(m['card']); ref['zone'] = Zone(ref['zone'])
        return CastStoredSpell(CardReference(**ref), c.player_id, c.source_id), automatic(c, m, 'after_shred')

    def after_shred(c):
        m = original(c); ref = MinionReference(**m['beneficiary'])
        rows = [row for row in c.state.cast_history if row.id not in m['previous'] and
            (row.source_id, row.player_id, row.card_id, row.caster_id, row.from_zone, row.origin) ==
            (m['card']['entity_id'], ref.player_id, SHRED, ref.entity_id, Zone.DECK, 'effect')]
        if len(rows) > 1:
            raise ResolutionError('P69 physical Shred acquired duplicate cast records')
        if not rows or not rows[0].completed or rows[0].failure is not None or live_minion(c.state, ref) is None:
            return ()
        if ref.card_id == FATEBREAKER:
            return (BuffCapturedMinion(ref, 3, 3, c.source_id),)
        cause = dict(m['cause']); cause['source'] = allocation_from_dict(cause['source'])
        return (CopyMinion(BoardPresenceReference.capture(c.state, ref.entity_id), ref.player_id,
            cause=SummonCause(**cause)),)

    def growth(c):
        a = progress_ability(c.source)
        if a is None or a.hand_progress != registry.card(c.source.card_id).hand_progress:
            raise ResolutionError('P69 spell lost its original physical hand progress')
        return a.progress_completions

    def stand(c):
        return (RandomDamageBatch(minions(c, registry, 3-c.player_id), 2,
            2 + growth(c), c.source_id, DamageKind.SPELL),)

    def bulb(c):
        n = 1 + growth(c)
        return (CastFromPool(c.player_id, POOL_ID, PoolQuery(kinds=(CardType.SPELL,), collectible=True,
            min_cost=n, max_cost=n), count=3, source_id=c.source_id),)

    def reinforcement(c):
        return (SummonFromZone(c.player_id, query=PoolQuery(kinds=(CardType.MINION,), max_cost=2),
            source_id=c.source_id, cause=SummonCause.capture(c)),)

    def gnomish(c):
        return (HealBatch(tuple(Heal(i, 4, c.source_id, HealingKind.SPELL)
            for i in characters(c, registry, c.player_id))),)

    def mekkatorque(c):
        options = tuple(ChoiceOption(json.dumps(asdict(MinionReference.capture(c.state.entities[i])), sort_keys=True),
            'Original friendly minion') for i in minions(c, registry, c.player_id))
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
            sample_size=1, on_select=PREFIX + 'aura_buff'),) if options else ()

    def aura_buff(c):
        ref = MinionReference(**original(c))
        return BuffCapturedMinion(ref, 4, 4, c.source_id), GrantCapturedKeyword(ref, Keyword.DIVINE_SHIELD, c.source_id)

    def phoenix_end(c):
        if c.player_effect is None or c.player_effect.spec_id != PREFIX + 'phoenix_return':
            raise ResolutionError('Phoenix return requires its original captured player instance')
        return (ConsumePlayerEffect(c.player_id, c.player_effect,
            (AddToHand(c.player_id, PHOENIX, c.source_id),)),)

    bodies = dict(shreds=shreds, deck_cast=deck_cast, selected_shred=selected_shred, after_shred=after_shred,
        stand=stand, bulb=bulb, reinforcement=reinforcement, gnomish=gnomish, mekkatorque=mekkatorque,
        aura_buff=aura_buff, noop=lambda c:(), sprite=lambda c:(AddToHand(c.player_id, BULB, c.source_id),),
        phoenix_death=lambda c:(AddPlayerEffect(c.player_id, PREFIX + 'phoenix_return', c.source_id),),
        phoenix_end=phoenix_end)
    for name, body in bodies.items(): registry.register_behavior(PREFIX + name, body)
    registry.register_trigger_condition(PREFIX + 'own_end', lambda c:c.event is not None and c.event.player_id == c.player_id)
    registry.register_player_effect(PlayerEffectSpec(PREFIX + 'phoenix_return', PHOENIX,
        triggers=(TriggerSpec('turn_ended', PREFIX + 'phoenix_end', EndTurnSpec('either')),)))
    scripts = {TIMEHOPPER:'shreds', FATEBREAKER:'deck_cast', VELOCIDRAKE:'deck_cast', STAND:'stand',
        SPRITE:'sprite', BULB:'bulb'}
    auras = {REINFORCEMENT:'reinforcement', GNOMISH:'gnomish', MEKKATORQUE:'mekkatorque'}
    for cid, body in auras.items():
        registry.register_player_effect(PlayerEffectSpec(PREFIX + body, cid, kind='aura', duration=3,
            tick_event='turn_ended', triggers=(TriggerSpec('turn_ended', PREFIX + body, EndTurnSpec()),)))
    for row in d['cards'] + d['dependencies']:
        raw = row['record']; cid = raw['id']; kind = CardType(raw['type'].lower()); kwargs = {}
        if cid in scripts: kwargs['on_play' if kind == CardType.SPELL else 'battlecry'] = PREFIX + scripts[cid]
        if cid in auras: kwargs['ongoing_effect_id'] = PREFIX + auras[cid]
        if cid in (STAND, BULB):
            kwargs['hand_progress'] = HandProgressSpec('event', 1, on_complete=PREFIX + 'noop', repeat=True,
                event='turn_ended', condition_id=PREFIX + 'own_end')
        if cid == FATEBREAKER: kwargs['keywords'] = (Keyword.LIFESTEAL,)
        if cid == VELOCIDRAKE: kwargs['keywords'] = (Keyword.RUSH,)
        if cid == PHOENIX:
            kwargs.update(deathrattle=PREFIX + 'phoenix_death', player_played_class_cost=
                PlayerPlayedClassCostSpec(None, 'cost.player-played-card-count-turn-v1'))
        if cid in (GNOMISH, MEKKATORQUE):
            kwargs['hand_actions'] = (HandActionSpec('trade', 'trade', 1),)
        if kind == CardType.SPELL: kwargs['spell_school'] = SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL'))
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'], attack=raw['attack'] or 0,
            health=raw['health'] or 0, metadata=metadata_from_record(raw), **kwargs)
        registry.register_card(card)
        if cid not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
