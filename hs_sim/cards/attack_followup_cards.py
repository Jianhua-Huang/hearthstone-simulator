"""Real native attack rewards, original combat kills and captured follow attacks."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import AddToHand, ForceAttack
from hs_sim.engine.character_attacks import completed_attack
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BoardPresenceReference, CardDefinition, CardType, DamageKind, Keyword, TriggerSpec, Zone
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/attack-followup-effects-v1.json'
BATCH_HASH = '33ea47132508f07a1b83675716ae65dc3b25fd263bfc4f8b317e1cf7d2d8cd0f'
PREFIX = 'cards.attack_followups.'
SCRIPTS = {'CORE_CATA_004': 'rehgar', 'CORE_CFM_344': 'finja', 'CS3_020': 'inquisitor'}


def load_batch():
    value = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(value) != BATCH_HASH:
        raise TargetValidationError('Native attack followups differ from the reviewed complete source pin')
    return value


def living_source(c):
    return (c.source.kind == CardType.MINION and c.source.zone == Zone.BOARD and c.source.active
            and c.source.health > 0 and not c.source.doomed)


def register_attack_followup_cards(registry):
    batch = load_batch()
    dep = batch['reused_dependencies'][0]
    bolt = dep['record']
    definition = registry.card(bolt['id'])
    if (canonical_digest(bolt) != dep['record_sha256'] or (bolt['id'], bolt['dbf_id']) != ('CORE_EX1_238', 69625)
            or definition.kind != CardType.SPELL or definition.cost != bolt['cost'] or definition.on_play is None):
        raise TargetValidationError('Rehgar lost its complete named Lightning Bolt dependency')

    def rehgar(c):
        row = completed_attack(c)
        if row is None or not living_source(c) or row.source_kind != CardType.MINION:
            return ()
        board = c.state.players[c.player_id].board
        attacker_id = row.declaration.source_id
        if attacker_id not in board:
            return ()
        if abs(board.index(attacker_id)-board.index(c.source_id)) > 1:
            return ()
        return (AddToHand(c.player_id, bolt['id'], c.source_id),)

    def finja(c):
        row = completed_attack(c)
        if row is None or row.declaration.source_id != c.source_id or not living_source(c):
            return ()
        target = c.state.entities[row.delivery.target_id]
        cause = target.death_cause
        if target.kind != CardType.MINION or cause is None or cause.kind not in ('damage', 'poison'):
            return ()
        result = cause.health_result
        if (result is None or result.damage_kind != DamageKind.COMBAT.value or result.source_id != c.source_id
                or result.original_target_id != row.delivery.target_id
                or (result.source_zone_epoch, result.source_entered_order) !=
                   (row.combat.source_zone_epoch, row.combat.source_entered_order)
                or not row.combat.event_cursor < result.batch_id <= row.terminal.event_cursor):
            return ()
        return (SummonFromZone(c.player_id, count=2, query=PoolQuery(tribes_any=('murloc',)),
                              source_id=c.source_id, cause=SummonCause.capture(c)),)

    def inquisitor(c):
        row = completed_attack(c)
        if (row is None or not living_source(c) or row.source_kind != CardType.HERO
                or row.combat.player_id != c.player_id):
            return ()
        target = c.state.entities[row.delivery.target_id]
        if (not target.active or target.health <= 0 or target.doomed or target.controller == c.player_id
                or target.zone not in (Zone.HERO, Zone.BOARD)):
            return ()
        defender = BoardPresenceReference.capture(c.state, target.id) if target.kind == CardType.MINION else target.id
        return (ForceAttack(BoardPresenceReference.capture(c.state, c.source_id), defender),)

    bodies = dict(rehgar=rehgar, finja=finja, inquisitor=inquisitor)
    for name, body in bodies.items():
        registry.register_behavior(PREFIX+name, body)
    identity = batch['historical_identity_evidence'][0]
    if canonical_digest(identity['record']) != identity['record_sha256'] or identity['record']['id'] != 'CFM_344':
        raise TargetValidationError('Finja lost its explicit historical deck identity')
    for row in batch['cards']:
        raw, recipe = row['record'], row['recipe']
        if (canonical_digest(raw) != row['record_sha256'] or raw['type'] != 'MINION' or not raw['collectible']
                or SCRIPTS.get(raw['id']) != recipe['script'] or
                (raw['cost'], raw['attack'], raw['health']) != (recipe['cost'], recipe['attack'], recipe['health'])):
            raise TargetValidationError('Unreviewed native attack-followup face')
        if raw['id'] == 'CORE_CFM_344' and (
                raw['tags'].get('DECK_RULE_COUNT_AS_COPY_OF_CARD_ID') != identity['record']['dbf_id']
                or recipe['deck_identity'] != identity['record']['id']):
            raise TargetValidationError('Finja changed its named original identity')
        if raw['id'] == 'CORE_CATA_004' and raw['tags'].get('COLLECTION_RELATED_CARD_DATABASE_ID') != bolt['dbf_id']:
            raise TargetValidationError('Rehgar changed its named generated spell')
        card = CardDefinition(raw['id'], raw['name'], CardType.MINION, cost=recipe['cost'],
            attack=recipe['attack'], health=recipe['health'], keywords=tuple(Keyword(k) for k in recipe['keywords']),
            triggers=(TriggerSpec('attack_finished', PREFIX+recipe['script']),),
            metadata=replace(metadata_from_record(raw), deck_identity=recipe['deck_identity']))
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
