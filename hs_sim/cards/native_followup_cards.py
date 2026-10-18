"""Current Core native declarations and complete draw/token followups."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import Damage, DamageBatch, Draw, Heal, HealBatch, InvokeBehavior, RandomDamage
from hs_sim.engine.health_theft import RandomStealHealthToHero
from hs_sim.engine.model import (CardDefinition, CardType, DamageKind, EndTurnSpec, HealingKind,
                                 TriggerSpec)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/native-followup-effects-v1.json'
BATCH_HASH = '7b16d50f378a09ef13cea0dbef42f32865a736a69f8db24754152386548531ac'
PREFIX = 'cards.native_followup.'
ALIASES = {'CORE_BT_156': 'BT_156', 'CORE_CS2_122': 'CS2_122', 'CORE_CS2_222': 'CS2_222',
           'CORE_EX1_059': 'EX1_059', 'CORE_OG_044': 'OG_044'}
SCRIPTS = {'EDR_476': 'moonwell', 'CAP_102': 'land_ho', 'EDR_817': 'infestation',
           'CAP_107t': 'cannon', 'EDR_810t': 'leech'}


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Native followup cards differ from their reviewed full source pin')
    return data


def minions(c, registry, player_id):
    return tuple(eid for eid in c.state.players[player_id].board for e in (c.state.entities[eid],)
        if e.kind == CardType.MINION and e.active and e.health > 0 and not e.doomed
        and registry.card(e.card_id).interactable is None)


def deathrattle_position(c):
    """Use the actual natural death slot, or the live carrier's right side."""
    if c.deathrattle is None:
        raise ValueError('Deathrattle placement requires its actual native activation')
    if c.death is not None:return c.death.position
    board=c.state.players[c.player_id].board
    return board.index(c.source_id)+1 if c.source_id in board else None


def characters(c, registry, player_id):
    hero = c.state.entities[c.state.players[player_id].hero_id]
    return ((hero.id,) if hero.active and hero.health > 0 and not hero.doomed else ()) + minions(c, registry, player_id)


def next_body(c, name):
    return InvokeBehavior(PREFIX+name, c.source_id, c.player_id, c.target_id,
                          None if c.play is None else c.play.id)


def register_cannoneer_behaviors(registry):
    from hs_sim.engine.native_producer_quantities import CANNONEER_SHOT, count
    def cannon(c):
        amount = count(c.state, registry, c.player_id, c.source.card_id, CANNONEER_SHOT)
        return tuple(next_body(c, 'cannon_execute') for _ in range(amount))
    # The classified end-turn context is frozen before sibling bodies execute.
    # Accept this producer in a fresh ordinary continuation, once per body.
    registry.register_behavior(PREFIX+'cannon', lambda c: (next_body(c, 'cannon_accept_shots'),))
    registry.register_behavior(PREFIX+'cannon_accept_shots', cannon)
    registry.register_behavior(PREFIX+'cannon_execute', lambda c: (
        RandomDamage(characters(c, registry, 3-c.player_id), 1, c.source_id, DamageKind.MINION_ABILITY),))


def register_native_followup_cards(registry):
    register_cannoneer_behaviors(registry)
    def spawn(c, card_id):
        request = SummonByCard(c.player_id, (SummonEntryMaterial(card_id),), SummonCause.capture(c))
        return (request, request)

    def leech(c):
        ids = characters(c, registry, 3-c.player_id)
        if not ids: return ()
        lowest = min(c.state.entities[eid].health for eid in ids)
        references = tuple(MinionReference.capture(c.state.entities[eid])
            if c.state.entities[eid].kind == CardType.MINION else eid
            for eid in ids if c.state.entities[eid].health == lowest)
        from .summon_beneficiary_cards import leech_theft_amount
        return (RandomStealHealthToHero(c.player_id, references, leech_theft_amount(c), c.source_id),)

    bodies = {
        'moonwell': lambda c: (DamageBatch(tuple(Damage(eid, 4, c.source_id, DamageKind.SPELL)
            for eid in characters(c, registry, 3-c.player_id))), next_body(c, 'moonwell_heal')),
        'moonwell_heal': lambda c: (HealBatch(tuple(Heal(eid, 4, c.source_id, HealingKind.SPELL)
            for eid in characters(c, registry, c.player_id))),),
        'land_ho': lambda c: (Draw(c.player_id, 2, c.source_id), next_body(c, 'cannons')),
        'infestation': lambda c: (Draw(c.player_id, 2, c.source_id), next_body(c, 'leeches')),
        'cannons': lambda c: spawn(c, 'CAP_107t'),
        'leeches': lambda c: spawn(c, 'EDR_810t'),
        'leech': lambda c: (next_body(c, 'leech_execute'),),
        'leech_execute': leech,
    }
    for name, body in bodies.items():
        registry.register_behavior(PREFIX+name, body)
    for row in load_batch()['cards']:
        raw, recipe = row['record'], row['recipe']
        if (canonical_digest(raw) != row['record_sha256'] or
                (raw['cost'], raw['attack'] or 0, raw['health'] or 0, raw['collectible']) !=
                (recipe['cost'], recipe['attack'], recipe['health'], recipe['root'])):
            raise TargetValidationError('Native followup card lost its reviewed complete printed face')
        kind = CardType(raw['type'].lower())
        metadata = replace(metadata_from_record(raw), deck_identity=recipe['deck_identity'])
        if raw['id'] in ALIASES:
            if recipe['alias'] != ALIASES[raw['id']]:
                raise TargetValidationError('Unreviewed native Core alias')
            original = registry.card(recipe['alias'])
            if (kind, raw['cost'], raw['attack'], raw['health']) != (
                    original.kind, original.cost, original.attack, original.health):
                raise TargetValidationError('Native alias printed body differs from its reviewed original')
            definition = replace(original, id=raw['id'], name=raw['name'], metadata=metadata)
        else:
            if recipe['alias'] is not None or SCRIPTS.get(raw['id']) != recipe['script']:
                raise TargetValidationError('Unreviewed native followup body')
            kwargs = ({'on_play': PREFIX+recipe['script']} if kind == CardType.SPELL else
                      {'triggers': (TriggerSpec('turn_ended', PREFIX+recipe['script'], EndTurnSpec()),)})
            definition = CardDefinition(raw['id'], raw['name'], kind, cost=raw['cost'],
                attack=recipe['attack'], health=recipe['health'], metadata=metadata,
                spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')), **kwargs)
        registry.register_card(definition)
        registry.register_pool_card(PoolCard.from_definition(definition))
