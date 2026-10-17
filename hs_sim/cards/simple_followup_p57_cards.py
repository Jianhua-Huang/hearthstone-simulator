"""Explicit egg forms, original health results, paid plays and next owner turn."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import Damage, Draw
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_followups import InvokeHealthResult
from hs_sim.engine.model import (CardAbilityCondition, CardDefinition, CardType, CostSpec, DamageKind,
    HandActionSpec, Keyword, SpellSchool, TargetSpec, Zone, TriggerSpec)
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .next_play_price_cards import PREFIX as PRICE_PREFIX

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p57-v1.json'
BATCH_HASH = 'cf3d93e5697c415f218ef07c0ec0dd55451e7828888bdcb2bd9d2b2d3c0943de'
EGG, BEAST = 'DINO_410', 'DINO_410t'
EGGS = (EGG, 'DINO_410t2', 'DINO_410t3', 'DINO_410t4', 'DINO_410t5')
CHAIN = (*EGGS, BEAST)
HARDSHIP, VANESSA, TAX = 'END_020', 'JAIL_407', 'TLC_452t15'
DEFERRED, PARENT = 'TIME_615', 'TLC_452'
ROOTS = (EGG, BEAST, *EGGS[1:], HARDSHIP, VANESSA, TAX)
PREFIX, POOL_ID = 'cards.simple_followup_p57.', 'constructed.cards'
BATTLECRIES = PoolQuery(kinds=(CardType.MINION,), collectible=True, ability=CardAbilityCondition(basis='printed'))
ONES = PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=1, max_cost=1)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != ROOTS
            or tuple(x['record']['id'] for x in data['skipped']) != (DEFERRED,)
            or tuple(x['record']['id'] for x in data['evidence_only']) != (PARENT,)
            or data['dependencies'] or data['existing_dependencies']):
        raise TargetValidationError('P57 complete reviewed scope changed')
    for row in data['cards'] + data['skipped'] + data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('P57 complete original source row changed')
    if data['numeric_normalizations'] != {cid: {'attack': 0} for cid in EGGS}:
        raise TargetValidationError('P57 only permits five explicitly reviewed egg attack zeros')
    return data


def register_simple_followup_p57_cards(registry):
    def hardship_result(c):
        result = c.health_result
        if result is None:
            raise ResolutionError('Hardship requires its original settled health result')
        target = c.state.entities[result.original_target_id]
        alive = target.kind == CardType.MINION and target.zone == Zone.BOARD and target.active and target.health > 0 and not target.doomed
        return (Draw(c.player_id, source_id=c.source_id),) if alive else (
            InvokeHealthResult(PREFIX + 'hardship_death', c.event),)

    def hardship_death(c):
        result = c.health_result
        died = result.target_id == result.original_target_id and any(
            d.entity_id == result.original_target_id and d.cause is not None and
            d.cause.kind in ('damage', 'poison') and d.cause.result == result.payload()
            for d in c.state.death_history)
        return (SummonFromPool(c.player_id, POOL_ID, ONES, source_id=c.source_id,
            cause=SummonCause.capture(c)),) if died else ()

    def vanessa(c):
        record = play_record(c.state, dict(c.event.data)['play_id'])
        if not record.completed or (record.source_id, record.player_id) != (c.event.source_id, c.event.player_id):
            raise ResolutionError('Vanessa requires the complete original finished PlayRecord')
        if record.player_id != c.player_id or record.source_id == c.source_id:
            return ()
        return (GenerateFromPool(c.player_id, POOL_ID, BATTLECRIES, source_id=c.source_id,
            cost=CostSpec(delta=-2, card_types=(CardType.MINION,))),)

    registry.register_behavior(PREFIX + HARDSHIP, lambda c: (
        Damage(c.target_id, 1, c.source_id, DamageKind.SPELL, PREFIX + 'hardship_result'),))
    registry.register_behavior(PREFIX + 'hardship_result', hardship_result)
    registry.register_behavior(PREFIX + 'hardship_death', hardship_death)
    registry.register_behavior(PREFIX + VANESSA, vanessa)
    registry.register_behavior(PREFIX + TAX, lambda c: (AddPlayerEffect(3-c.player_id, PREFIX + 'pending_tax', c.source_id),))
    for cid, next_cid in zip(EGGS, CHAIN[1:]):
        registry.register_behavior(PREFIX + cid, lambda c, next_cid=next_cid: (
            SummonByCard(c.player_id, (SummonEntryMaterial(next_cid),), SummonCause.capture(c)),))
    for row in load_batch()['cards']:
        raw = row['record']; cid = raw['id']; kind = CardType(raw['type'].lower()); kwargs = {}
        if cid in EGGS:
            kwargs['deathrattle'] = PREFIX + cid
        elif cid == BEAST:
            kwargs['keywords'] = (Keyword.TAUNT,)
        elif cid == HARDSHIP:
            kwargs.update(on_play=PREFIX + cid, spell_school=SpellSchool.SHADOW,
                targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)))
        elif cid == VANESSA:
            kwargs.update(hand_actions=(HandActionSpec('prepare', 'prepare', 1),),
                triggers=(TriggerSpec('card_played', PREFIX + VANESSA),))
        elif cid == TAX:
            kwargs['battlecry'] = PREFIX + cid
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'],
            attack=(0 if cid in EGGS else raw['attack']) if kind == CardType.MINION else 0,
            health=raw['health'] if kind == CardType.MINION else 0,
            metadata=metadata_from_record(raw), **kwargs)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_player_effect(replace(registry.player_effect(PRICE_PREFIX + 'pending_slow'),
        id=PREFIX + 'pending_tax', card_id=TAX))
