"""Reviewed attack transformation and actual next-turn played-minion resummoning."""
import json
from pathlib import Path
from hs_sim.engine.cross_zone import TransformCapturedMinion
from hs_sim.engine.model import CardDefinition, CardType, Keyword, SecretSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import ResurrectMinion, death_record
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/reactive-secret-effects-v1.json'
BATCH_HASH = '7b1ffacaa4b458907eeb73846e5714dacaadf2cbd5a7807b3d22e3f734283ec1'
PREFIX = 'cards.reactive_secrets.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Reactive secrets differ from the reviewed complete source pin')
    return data


def sheep(c):
    target = c.state.entities[c.window.source_id]
    return (TransformCapturedMinion(MinionReference.capture(target), 'CS2_tk1', c.source_id),)


def qualifying_death(c):
    if c.event is None or c.event.kind != 'minion_died': return None
    data = dict(c.event.data)
    death = death_record(c.state, data.get('death_id'))
    if (death.entity_id, death.controller, death.batch, death.turn) != (
            c.event.source_id, c.event.player_id, data.get('batch'), c.state.turn):
        raise ValueError('Secret lost its original current minion death')
    if death.controller != c.player_id or death.zone != Zone.BOARD: return None
    play = next((row for row in reversed(c.state.play_history) if row.source_id == death.entity_id), None)
    if (play is None or play.kind != CardType.MINION or play.minion_result != 'summoned' or
            not play.completed or play.countered or play.turn+1 != death.turn):
        return None
    entry = next((row for row in reversed(c.state.successful_summon_history)
                  if row.entity_id == death.entity_id), None)
    # HAND -> PLAY -> BOARD is the original physical play. Later stored-card
    # summons of this same entity cannot borrow its earlier hand-play history.
    # Face/control changes during that board residence do not publish an entry.
    if entry is None or (entry.turn, entry.action, entry.minion.zone_epoch) != (
            play.turn, play.action, play.submitted_cost.zone_epoch+2):
        return None
    return death


def resummon(c):
    death = qualifying_death(c)
    if death is None: raise ValueError('Accepted resummoning lost its original qualifying death')
    return (ResurrectMinion(c.player_id, death.id, position=death.position,
                           source_id=c.source_id, cause=SummonCause.capture(c)),)


def register_reactive_secret_cards(registry):
    registry.register_behavior(PREFIX+'sheep', sheep)
    registry.register_behavior(PREFIX+'resummon', resummon)
    registry.register_secret_condition(PREFIX+'resummon', lambda c: qualifying_death(c) is not None)
    for row in load_batch()['cards']:
        raw, recipe = row['record'], row['recipe']
        if canonical_digest(raw) != row['record_sha256'] or raw['cost'] != recipe['cost']:
            raise TargetValidationError('Unreviewed reactive secret record or cost')
        kwargs = {}
        if recipe['root']:
            if raw['type'] != 'SPELL' or raw['tags'].get('SECRET') != 1:
                raise TargetValidationError('Reactive secret lost its full declaration')
            if (raw['id'], recipe['script']) == ('JAIL_315', 'sheep'):
                spec = SecretSpec('JAIL_315', ('attack_declared',), 'm4.minion_attack', PREFIX+'sheep')
            elif (raw['id'], recipe['script']) == ('TIME_620', 'resummon'):
                spec = SecretSpec('TIME_620', ('minion_died',), PREFIX+'resummon', PREFIX+'resummon',
                                  requires_board_space=True)
            else: raise TargetValidationError('Unreviewed reactive secret body')
            kwargs = dict(secret=spec, keywords=(Keyword.SECRET,),
                          spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')))
        elif raw['id'] != 'CS2_tk1' or raw['type'] != 'MINION' or (raw['attack'], raw['health']) != (1, 1):
            raise TargetValidationError('Unreviewed Sheep dependency')
        kind = CardType(raw['type'].lower())
        definition = CardDefinition(raw['id'], raw['name'], kind, cost=raw['cost'],
            attack=raw['attack'] or 0, health=raw['health'] if kind == CardType.MINION else 0,
            metadata=metadata_from_record(raw), **kwargs)
        registry.register_card(definition)
        registry.register_pool_card(PoolCard.from_definition(definition))
