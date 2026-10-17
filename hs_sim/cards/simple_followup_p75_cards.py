"""Original paid/turn histories and independent old Colossal appendages."""
import json
from pathlib import Path

from hs_sim.engine.effects import Freeze, RandomDamage
from hs_sim.engine.health_followups import InvokeHealthResult
from hs_sim.engine.model import (CardDefinition, CardType, CostSpec, DamageKind, EndTurnSpec,
    HandActionSpec, HealthFlow, Keyword, PaymentType, TriggerSpec, Zone)
from hs_sim.engine.play_history import played_cards
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion, FreezeCapturedMinion, MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import characters

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p75-v1.json'
BATCH_HASH = '17750ae94bcbb3638c20d4ca76e525a32af516eeaa620013f4542b3d2785ba05'
WANNABE, JADE = 'JAIL_909', 'JAIL_474'
DRILLS = ('TSC_029t', 'TSC_029t2')
STALKS = ('TSC_219t', 'TSC_219t2', 'TSC_219t3', 'TSC_219t4')
WINGS = ('NX2_037t', 'NX2_037t2')
COLLECTIBLE_ROOTS = (WANNABE, JADE)
DEPENDENCIES = (*DRILLS, *STALKS, *WINGS)
ROOTS = (*COLLECTIBLE_ROOTS, *DEPENDENCIES)
PREFIX = 'cards.simple_followup_p75.'
POOL_ID = 'constructed.cards'
EIGHTS = PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=8, max_cost=8)


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or d['existing_dependencies'] or d['skipped']
            or tuple(x['record']['id'] for x in d['cards']) != COLLECTIBLE_ROOTS
            or tuple(x['record']['id'] for x in d['dependencies']) != DEPENDENCIES):
        raise TargetValidationError('P75 complete source scope changed')
    if any(canonical_digest(x['record']) != x['record_sha256']
            for key in ('cards', 'dependencies', 'evidence_only') for x in d[key]):
        raise TargetValidationError('P75 complete original row changed')
    return d


def register_simple_followup_p75_cards(registry):
    d = load_batch()

    def wannabe(c):
        if c.combo is None:
            raise ValueError('Defias Wannabe needs its actual Combo acceptance')
        if not living_source(c): return ()
        count = sum(p.id != c.combo.play_id for p in played_cards(c.state, c.player_id, turn=c.state.turn))
        return (BuffCapturedMinion(MinionReference.capture(c.source), count, count, c.source_id),) if count else ()

    def jade(c):
        count = sum(p.cost == 2 and p.payment == PaymentType.MANA for p in played_cards(c.state, c.player_id))
        return (GenerateFromPool(c.player_id, POOL_ID, EIGHTS, count=2, source_id=c.source_id,
            cost=CostSpec(delta=-count) if count else None),)

    def stalk(c):
        if c.event.player_id != c.player_id or not living_source(c): return ()
        return (RandomDamage(characters(c, registry, 3-c.player_id), 2, c.source_id, DamageKind.MINION_ABILITY),)

    def wing(c):
        result = c.health_result
        if (result is None or result.flow != HealthFlow.DAMAGE.value or result.damage_dealt <= 0
                or (result.source_id, result.source_controller, result.source_card_id) !=
                   (c.source_id, c.player_id, c.source.card_id)
                or (result.source_zone_epoch, result.source_entered_order) !=
                   (c.source.zone_epoch, c.source.entered_order)):
            return ()
        return (InvokeHealthResult(PREFIX+'freeze_damaged', c.event),)

    def freeze_damaged(c):
        result = c.health_result
        if result is None or result.flow != HealthFlow.DAMAGE.value or result.damage_dealt <= 0:
            return ()
        entity = c.state.entities.get(result.target_id)
        if (entity is None or not entity.active or entity.doomed or entity.health <= 0
                or (entity.card_id, entity.controller, entity.kind.value, entity.zone_epoch, entity.entered_order) !=
                   (result.target_card_id, result.target_controller, result.target_kind,
                    result.target_zone_epoch, result.target_entered_order)):
            return ()
        if entity.kind == CardType.MINION and entity.zone == Zone.BOARD:
            return (FreezeCapturedMinion(MinionReference.capture(entity), c.source_id),)
        if entity.kind == CardType.HERO and entity.zone == Zone.HERO:
            return (Freeze(entity.id, c.source_id),)
        return ()

    for name, body in dict(wannabe=wannabe, jade=jade, stalk=stalk, wing=wing, freeze_damaged=freeze_damaged).items():
        registry.register_behavior(PREFIX+name, body)
    for item in (*d['cards'], *d['dependencies']):
        raw = item['record']; cid = raw['id']; kw = {}
        if cid == WANNABE:
            kw.update(keywords=(Keyword.COMBO,), combo=PREFIX+'wannabe', hand_actions=(HandActionSpec('prepare', 'prepare', 1),))
        if cid == JADE: kw['on_play'] = PREFIX+'jade'
        if cid in DRILLS or cid in WINGS: kw['keywords'] = (Keyword.RUSH,)
        if cid in WINGS: kw['triggers'] = (TriggerSpec('health_resolved', PREFIX+'wing'),)
        if cid in STALKS:
            if raw['tags']['TAG_SCRIPT_DATA_NUM_1'] != 2:
                raise TargetValidationError('Stalk printed numeric damage changed')
            kw['triggers'] = (TriggerSpec('turn_ended', PREFIX+'stalk', end_turn=EndTurnSpec()),)
        minion = raw['type'] == 'MINION'
        definition = CardDefinition(cid, raw['name'], CardType.MINION if minion else CardType.SPELL,
            cost=raw['cost'], attack=raw['attack'] if minion else 0, health=raw['health'] if minion else 0,
            metadata=metadata_from_record(raw), **kw)
        registry.register_card(definition)
        if cid not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(definition))
