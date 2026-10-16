"""Reviewed returns and hand growth, planned with original physical references."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import (CardDefinition, CardType, CostSpec, EndTurnSpec, Keyword,
    TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.return_followups import RandomReturnCapturedMinion, ReturnCapturedMinion
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/return-hand-effects-v1.json'
BATCH_HASH = '8c5b81028f5eefc41805e6363c9b87292f23b0fae241135ac0ea2972337e31f4'
PREFIX = 'cards.return_hand.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Return-hand content differs from its reviewed source pin')
    return data


def board_refs(c, player, registry):
    return tuple(MinionReference.capture(e) for eid in c.state.players[player].board
        for e in (c.state.entities[eid],) if e.kind == CardType.MINION and e.active and e.health > 0
        and not e.doomed and registry.card(e.card_id).interactable is None)


def return_spider(c):
    e = c.state.entities.get(c.target_id)
    if e is None or e.zone != Zone.BOARD or e.kind != CardType.MINION or e.controller != c.player_id:
        return ()
    return (ReturnCapturedMinion(MinionReference.capture(e), c.source_id,
        on_success=(SummonByCard(c.player_id, (SummonEntryMaterial('EDR_523t'),), SummonCause.capture(c)),)),)


def hand_buffs(c, attack, health, kinds):
    return tuple(BuffStoredCard(CardReference.capture(e), attack, health, c.source_id)
        for eid in c.state.players[c.player_id].hand for e in (c.state.entities[eid],) if e.kind in kinds)


SCRIPTS = {
    'enemy_owner_return': lambda c, r: tuple(ReturnCapturedMinion(ref, c.source_id, to_owner=True)
                                         for ref in board_refs(c, 3-c.player_id, r)),
    'return_spider': lambda c, r: return_spider(c),
    'random_return_discount': lambda c, r: (RandomReturnCapturedMinion(board_refs(c, c.player_id, r),
                                          c.source_id, CostSpec(delta=-2)),),
    'end_hand_buff': lambda c, r: hand_buffs(c, 1, 1, (CardType.MINION,)),
    'hand_attack_buff': lambda c, r: hand_buffs(c, 2, 0, (CardType.MINION, CardType.WEAPON)),
}


def register_return_hand_cards(registry):
    for name, fn in SCRIPTS.items():
        registry.register_behavior(PREFIX+name, lambda c, fn=fn: fn(c, registry))
    for row in load_batch()['cards']:
        raw, recipe = row['record'], row['recipe']
        if canonical_digest(raw) != row['record_sha256'] or recipe['cost'] != raw['cost']:
            raise TargetValidationError('Return-hand record or reviewed printed cost changed')
        kind = CardType(raw['type'].lower()); kwargs = {}
        entry, script = recipe['entry'], recipe['script']
        if script is not None:
            if script not in SCRIPTS: raise TargetValidationError('Unknown return-hand body')
            if entry == 'own_turn_end':
                kwargs['triggers'] = (TriggerSpec('turn_ended', PREFIX+script, EndTurnSpec()),)
            elif entry in ('on_play', 'battlecry', 'deathrattle'): kwargs[entry] = PREFIX+script
            else: raise TargetValidationError('Unreviewed return-hand entry')
        if recipe['target'] is not None:
            if recipe['target'] != 'friendly_minion': raise TargetValidationError('Unreviewed return-hand target')
            kwargs['targeting'] = TargetSpec(TargetMode.REQUIRED, zones=(Zone.BOARD,),
                                             kinds=(CardType.MINION,), relation='friendly')
        definition = CardDefinition(raw['id'], raw['name'], kind, cost=raw['cost'], attack=raw['attack'] or 0,
            health=raw['health'] if kind == CardType.MINION else 0,
            durability=raw['health'] if kind == CardType.WEAPON else 0,
            keywords=tuple(Keyword(x) for x in recipe['keywords']),
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),
            metadata=replace(metadata_from_record(raw), deck_identity=recipe['deck_identity']), **kwargs)
        registry.register_card(definition); registry.register_pool_card(PoolCard.from_definition(definition))
