"""Ten real ordinary predicates keep native facts and guard-free subjects."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.assemble_reactions import AssembleReactionSource
from hs_sim.engine.cross_zone import TransformMinionFromPool
from hs_sim.engine.draw_casts import draw_record
from hs_sim.engine.effects import AddToHand, Destroy, Draw, InvokeBehavior, RandomForceAttack
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.jade import printed_definition
from hs_sim.engine.model import CardType, CostSpec, HandActionSpec, Keyword, SpellSchool
from hs_sim.engine.pools import DiscoverFromPool, GenerateFromPool
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .native_followup_cards import characters
from . import fixed_companion_cards as companions
from . import simple_followup_p41_cards as native_variant
from . import simple_followup_p42_cards as native_herald
from . import simple_followup_p89_cards as native_wo

TIGER, VARIANT, PAGETURNER, EREDAR, ANTONIDAS, AUCTIONEER, BROLL, BLAZE, HERALD, WO = SOURCES = (
    'BE_999', 'TIME_049', 'TLC_220', 'CORE_TTN_843', 'CORE_EX1_559', 'JAIL_718', 'EDR_853', 'FIR_904', 'FIR_913', 'TIME_013')
DEMON, FIREBALL = 'TTN_843t1', 'CS2_029'
DEPENDENCIES = (DEMON, FIREBALL, 'NEW1_034', 'NEW1_033', 'NEW1_032')
PAGE_INNER, BLAZE_INNER = 'cards.simple_native_p05.hit', 'cards.simple_followup_p43.burst'
PREFIX = 'cards.assemble_turn_draw_spell.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-turn-draw-spell-followups-v1.json'
BATCH_HASH = 'd073b79eca1d31fadce4efadd359490e405a462f2987ea7d1fae4960118221e0'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != SOURCES + DEPENDENCIES or
            tuple(row['card_id'] for row in data['reviewed_templates']) != SOURCES or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256'] for row in data['existing_dependencies']) or
            any(canonical_digest(row['query']) != row['query_sha256'] for row in data['queries'].values()) or
            canonical_digest(data['companion_family']) != data['companion_family_sha256'] or
            canonical_digest(data['companion_producer']) != data['companion_producer_sha256']):
        raise TargetValidationError('Turn/draw/spell assembly requires ten complete sources and five original named dependencies')
    return data


def register_assemble_turn_draw_spell_followups(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Turn/draw/spell assembly changed a complete original source or dependency')
    for entry in data['reviewed_templates']:
        original = registry.card(entry['card_id'])
        if (len(original.triggers) != 1 or original.triggers[0].event != entry['event'] or
                original.triggers[0].behavior_id != entry['original_behavior_id']):
            raise TargetValidationError('Turn/draw/spell assembly lost its actual unique ordinary trigger')
        registry.behavior(entry['original_behavior_id'])
    queries = {
        'variant': (native_variant.POOL_ID, native_variant.QUERY),
        'herald': (native_herald.POOL_ID, native_herald.QUERY),
        'wo': (native_wo.PAST_POOL, native_wo.QUERIES[native_wo.WO]),
    }
    for name, (pool, query) in queries.items():
        pin = data['queries'][name]
        if pool != pin['pool_id'] or canonical_digest(asdict(query)) != pin['query_sha256']:
            raise TargetValidationError('Turn/draw/spell assembly changed an entire native generation query')
    if (canonical_digest(asdict(registry.minion_family_profile(companions.COMPANION_FAMILY))) != data['companion_family_sha256'] or
            canonical_digest(asdict(registry.summon_producer_profile(companions.PREFIX + 'random'))) != data['companion_producer_sha256']):
        raise TargetValidationError('Turn/draw/spell assembly changed the original companion family or producer')
    for identity in (PAGE_INNER, BLAZE_INNER):
        registry.behavior(identity)
    original = registry.behavior(registry.card(ANTONIDAS).triggers[0].behavior_id)
    bindings = dict(zip(original.__code__.co_freevars, (cell.cell_contents for cell in original.__closure__ or ())))
    if bindings.get('fire', {}).get('id') != data['native_fireball_id'] or data['native_fireball_id'] != FIREBALL:
        raise TargetValidationError('Turn/draw/spell assembly changed the actual original Fireball identity')

    def event(c, kind):
        if c.event is None or c.event.kind != kind:
            raise ResolutionError('Turn/draw/spell assembly requires its original ' + kind + ' event')
        return c.event

    def any_turn(c):
        event(c, 'turn_started')
        return living_source(c)

    def own_turn(c):
        return event(c, 'turn_started').player_id == c.player_id and living_source(c)

    def own_elemental_summon(c):
        original = event(c, 'minion_summoned')
        if original.player_id != c.player_id:
            return False
        rows = [row for row in c.state.successful_summon_history if row.event_sequence == original.sequence]
        if len(rows) != 1:
            raise ResolutionError('Pageturner assembly lost its unique original successful summon')
        row = rows[0]
        fact = row.minion
        target = c.state.entities[original.target_id]
        if ((row.entity_id, row.player_id) != (original.target_id, original.player_id) or
                (target.id, target.card_id, target.controller, target.zone_epoch, target.entered_order) !=
                (fact.entity_id, fact.card_id, fact.controller, fact.zone_epoch, fact.entered_order)):
            raise ResolutionError('Pageturner assembly borrowed another physical entry or later residence')
        if row.tribes is None:
            raise UnsupportedDefinitionError('Unknown original Elemental summon tribes')
        return row.tribes.matches_any(('elemental',))

    def own_draw(c):
        original = event(c, 'card_drawn')
        row = draw_record(c.state, dict(original.data)['draw_id'])
        if (row.entity_id, row.player_id) != (original.target_id, original.player_id) or row.outcome not in ('hand', 'cast'):
            raise ResolutionError('Eredar assembly lost its original physical draw')
        c.state.entities[row.entity_id]
        return row.player_id == c.player_id

    def started(c):
        original = event(c, 'spell_cast_started')
        row = cast_record(c.state, dict(original.data)['cast_id'])
        if (row.source_id, row.player_id) != (original.source_id, original.player_id):
            raise ResolutionError('Spell-start assembly lost its actual original cast')
        return row

    def own_hand_cast_start(c):
        row = started(c)
        return row.player_id == c.player_id and row.origin == 'hand'

    def own_cast_start(c):
        row = started(c)
        return living_source(c) and row.player_id == c.player_id and row.failure in (None, 'countered')

    def finished(c, school=None):
        original = event(c, 'spell_cast_finished')
        row = cast_record(c.state, dict(original.data)['cast_id'])
        if ((row.source_id, row.player_id, row.target_id) != (original.source_id, original.player_id, original.target_id) or
                not row.completed or not row.payload_started or row.failure is not None or row.interrupted):
            raise ResolutionError('Spell-finish assembly requires its actual successful original cast')
        return (row.player_id == c.player_id and living_source(c) and
            (school is None or registry.card(row.card_id).spell_school == school))

    def transform_five(c):
        if not living_source(c):
            return ()
        # Use the same public printed basis as the consumer. The text is five,
        # while the old native two-cost card's relative request happened to be +3.
        delta = 5 - printed_definition(registry, c.source).cost
        return (TransformMinionFromPool(MinionReference.capture(c.source), native_variant.POOL_ID,
            delta, query=native_variant.QUERY, cost_basis='printed', source_id=c.source_id),)

    conditions = {
        'any_turn': any_turn, 'own_turn': own_turn, 'own_elemental_summon': own_elemental_summon,
        'own_draw': own_draw, 'own_hand_cast_start': own_hand_cast_start, 'own_cast_start': own_cast_start,
        'own_finished_cast': finished, 'own_finished_fel_cast': lambda c: finished(c, SpellSchool.FEL),
        'own_finished_fire_cast': lambda c: finished(c, SpellSchool.FIRE),
    }
    for name, predicate in conditions.items():
        registry.register_trigger_condition(PREFIX + name, predicate)
    bodies = {
        'force_attack': lambda c: (RandomForceAttack((c.source_id,), characters(c, registry, 3-c.player_id), c.source_id),) if living_source(c) else (),
        'transform_five': transform_five,
        'late_hit': lambda c: (InvokeBehavior(PAGE_INNER, c.source_id, c.player_id),),
        'demon': lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial(DEMON),), SummonCause.capture(c)),),
        'fireball': lambda c: (AddToHand(c.player_id, FIREBALL, c.source_id),),
        'draw': lambda c: (Draw(c.player_id, source_id=c.source_id),),
        'companion': lambda c: companions.companion_effects(c, registry),
        'destroy_burst': lambda c: (Destroy(c.source_id, c.source_id), InvokeBehavior(BLAZE_INNER, c.source_id, c.player_id)),
        'elemental': lambda c: (GenerateFromPool(c.player_id, native_herald.POOL_ID, native_herald.QUERY,
            source_id=c.source_id, cost=CostSpec(delta=-3, card_types=(CardType.MINION,))),),
        'past_nature': lambda c: (DiscoverFromPool(c.player_id, native_wo.PAST_POOL,
            native_wo.QUERIES[native_wo.WO], source_id=c.source_id),),
    }
    for name, body in bodies.items():
        registry.register_behavior(PREFIX + name, body)
    for entry in data['reviewed_templates']:
        registry.register_assemble_reaction_source(AssembleReactionSource(entry['card_id'], entry['event'],
            entry['original_behavior_id'], entry['condition_id']))
        registry.register_assemble_template(AssembleTemplate(entry['card_id'],
            AssemblePrefix(entry['event'], tuple(Keyword(k) for k in entry['keywords']),
                condition_id=entry['condition_id'], hand_actions=tuple(HandActionSpec(**spec) for spec in entry['hand_actions'])),
            AssembleSuffix(entry['body_behavior_id'], tuple(entry['allowed_timings']))))
