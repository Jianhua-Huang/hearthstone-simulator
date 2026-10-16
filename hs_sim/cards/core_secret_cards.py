"""Reviewed current Core secrets using the existing hidden-secret interpreter."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import RandomDestroy
from hs_sim.engine.interrupts import attack_live
from hs_sim.engine.model import CardDefinition, CardType, Keyword, SecretSpec, Zone
from hs_sim.engine.play_history import play_record, played_cards
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/core-secret-effects-v1.json'
BATCH_HASH = '6698956af0b0738eee101179d80e940d306597d3aef02c3e5e4484598f91fc92'
PREFIX = 'cards.core_secrets.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Core secret content differs from the reviewed complete source pin')
    return data


def event_play(c):
    if c.event is None or c.event.kind != 'card_played': return None
    record = play_record(c.state, dict(c.event.data).get('play_id'))
    if (record.source_id, record.player_id) != (c.event.source_id, c.event.player_id) or not record.completed:
        raise ValueError('Secret lost its original completed physical hand play')
    return record


def enemy_minions(c, registry):
    return tuple(eid for eid in c.state.players[3-c.player_id].board for e in (c.state.entities[eid],)
        if e.kind == CardType.MINION and e.active and e.health > 0 and not e.doomed
        and registry.card(e.card_id).interactable is None)


def oasis(c):
    if not attack_live(c.state, c.window): return False
    attacker = c.state.entities[c.window.source_id]; target = c.state.entities[c.window.target_id]
    return attacker.controller != c.player_id and target.kind == CardType.MINION and target.controller == c.player_id


def rat(c):
    record = event_play(c)
    return record is not None and record.player_id != c.player_id and record.turn == c.state.turn and len(
        played_cards(c.state, record.player_id, turn=record.turn, before_id=record.id+1)) >= 3


def pressure(c, registry):
    record = event_play(c)
    return record is not None and record.player_id != c.player_id and record.kind == CardType.SPELL and (
        not record.countered and bool(enemy_minions(c, registry)))


def summoned(c, card):
    return (SummonByCard(c.player_id, (SummonEntryMaterial(card),), SummonCause.capture(c)),)


def register_core_secret_cards(registry):
    data = load_batch()
    for dependency in data['reused_dependencies']:
        raw = dependency['record']; existing = registry.card(raw['id'])
        if canonical_digest(raw) != dependency['record_sha256'] or (
                existing.cost, existing.attack, existing.health, existing.metadata) != (
                raw['cost'], raw['attack'], raw['health'], metadata_from_record(raw)):
            raise TargetValidationError('The real Water Elemental dependency differs from its current complete data')
    conditions = {'oasis': oasis, 'rat': rat, 'pressure': lambda c: pressure(c, registry)}
    bodies = {'oasis': lambda c: summoned(c, 'CS2_033'), 'rat': lambda c: summoned(c, 'GIL_577t'),
              'pressure': lambda c: (RandomDestroy(enemy_minions(c, registry), c.source_id),)}
    for name, condition in conditions.items():
        registry.register_secret_condition(PREFIX+name, condition)
        registry.register_behavior(PREFIX+name, bodies[name])
    for row in data['cards']:
        raw, recipe = row['record'], row['recipe']
        if canonical_digest(raw) != row['record_sha256'] or raw['cost'] != recipe['cost']:
            raise TargetValidationError('Core secret record or reviewed printed cost changed')
        kind = CardType(raw['type'].lower()); kwargs = {}; keywords = ()
        if recipe['root']:
            if kind != CardType.SPELL or raw['tags'].get('SECRET') != 1:
                raise TargetValidationError('Core secret root lacks its original Secret spell declaration')
            keywords = (Keyword.SECRET,)
            if recipe['alias'] is not None:
                original = registry.card(recipe['alias'])
                if original.secret is None or original.cost != raw['cost']:
                    raise TargetValidationError('Current secret alias lost its reviewed complete original behavior')
                kwargs['secret'] = original.secret
            else:
                name = recipe['script']
                if name not in conditions: raise TargetValidationError('Unreviewed current secret body')
                kwargs['secret'] = SecretSpec(recipe['deck_identity'],
                    ('attack_declared',) if name == 'oasis' else ('card_played',),
                    PREFIX+name, PREFIX+name, requires_board_space=name in ('oasis', 'rat'))
        elif raw['id'] != 'GIL_577t' or kind != CardType.MINION:
            raise TargetValidationError('Unreviewed current secret dependency')
        definition = CardDefinition(raw['id'], raw['name'], kind, cost=raw['cost'],
            attack=raw['attack'] or 0, health=raw['health'] if kind == CardType.MINION else 0,
            keywords=keywords, spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),
            metadata=replace(metadata_from_record(raw), deck_identity=recipe['deck_identity']), **kwargs)
        registry.register_card(definition); registry.register_pool_card(PoolCard.from_definition(definition))
