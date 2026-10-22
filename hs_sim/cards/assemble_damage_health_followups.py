"""Real damage predicates and independent public-effect assembly subjects."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.assemble_reactions import AssembleReactionSource
from hs_sim.engine.effects import AddToHand, Draw, GainArmor, RandomDamage, RandomDestroy, SwapStats
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardType, DamageKind, HealthFlow, Keyword, Zone
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .native_followup_cards import minions
from .reactive_growth_cards import buff_source

PREY, PAIN, TOWER, WASP, TORTOLLA, DESTROYER, HOURGLASS = SOURCES = (
    'BE_998', 'CORE_EX1_007', 'JAIL_440', 'TLC_630', 'EDR_471', 'FIR_955', 'TIME_050')
GHOUL, STINGER, GRUB = DEPENDENCIES = ('HERO_11bpt', 'TLC_630t', 'TLC_903t')
PREFIX = 'cards.assemble_damage_health.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-damage-health-followups-v1.json'
BATCH_HASH = '2cab27013101554a30cb02654b0f036daf6f69cda3a80b898423037bbc543648'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != SOURCES + DEPENDENCIES or
            tuple(row['card_id'] for row in data['reviewed_templates']) != SOURCES or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256']
                for row in data['existing_dependencies'])):
        raise TargetValidationError('Damage/health assembly requires seven full sources and three original named dependencies')
    return data


def register_assemble_damage_health_followups(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Damage/health assembly changed a complete original source or named dependency')
    for entry in data['reviewed_templates']:
        original = registry.card(entry['card_id'])
        if (len(original.triggers) != 1 or original.triggers[0].event != entry['event'] or
                original.triggers[0].behavior_id != entry['original_behavior_id']):
            raise TargetValidationError('Damage/health assembly lost its actual native ordinary trigger')
        registry.behavior(entry['original_behavior_id'])
    defaults = registry.behavior(registry.card(PAIN).triggers[0].behavior_id).__defaults__
    economy = dict(steps=[asdict(step) for step in defaults[0]], is_spell=defaults[1], trigger=defaults[2])
    if canonical_digest(economy) != canonical_digest(data['economy_callback_defaults']):
        raise TargetValidationError('Damage/health assembly changed the original Acolyte economy steps')

    def self_damage(c):
        if c.event is None or c.event.kind != 'damage_dealt':
            raise ResolutionError('Damage assembly requires its actual damage event')
        return c.event.target_id == c.source_id and c.event.amount > 0

    def settled(c):
        if c.event is None or c.event.kind != 'health_resolved' or c.health_result is None:
            raise ResolutionError('Health assembly requires its original settled health result')
        return c.health_result

    def self_health_damage(c):
        result = settled(c)
        return result.target_id == c.source_id and result.flow == HealthFlow.DAMAGE.value and result.damage_dealt > 0

    def own_hero_damage_own_turn(c):
        result = settled(c)
        return (living_source(c) and result.flow == HealthFlow.DAMAGE.value and result.damage_dealt > 0 and
            result.active_player == c.player_id and result.target_kind == CardType.HERO.value and
            result.target_controller == c.player_id and result.target_id == c.state.players[c.player_id].hero_id)

    def surviving_self_damage(c):
        result = settled(c)
        source = c.source
        return (result.flow == HealthFlow.DAMAGE.value and result.damage_dealt > 0 and
            result.target_id == c.source_id and result.health_after > 0 and not result.doomed_after and
            source.zone == Zone.BOARD and source.active and source.health > 0 and not source.doomed and
            (result.target_zone_epoch, result.target_entered_order) == (source.zone_epoch, source.entered_order))

    def two_ghouls(c):
        request = SummonByCard(c.player_id, (SummonEntryMaterial(GHOUL),), SummonCause.capture(c))
        return request, request

    def armor_attack(c):
        # Preserve the original physical capture even for lethal settled damage.
        # A borrowed natural death body can still grant armor after removal.
        buff = (buff_source(c, 1),) if c.source.kind == CardType.MINION and c.source.zone == Zone.BOARD else ()
        return GainArmor(c.player_id, 1), *buff

    for name, handler in (('self_damage', self_damage), ('self_health_damage', self_health_damage),
            ('own_hero_damage_own_turn', own_hero_damage_own_turn), ('surviving_self_damage', surviving_self_damage)):
        registry.register_trigger_condition(PREFIX + name, handler)
    bodies = {
        'destroy_random': lambda c: (RandomDestroy(minions(c, registry, 3-c.player_id), c.source_id),),
        'draw': lambda c: (Draw(c.player_id, source_id=c.source_id),),
        'two_ghouls': two_ghouls,
        'stinger': lambda c: (AddToHand(c.player_id, STINGER, c.source_id),),
        'armor_attack': armor_attack,
        'damage_three': lambda c: (RandomDamage(minions(c, registry, 3-c.player_id), 3,
            c.source_id, DamageKind.MINION_ABILITY),),
        'swap_stats': lambda c: (SwapStats(c.source_id, c.source_id),),
    }
    for name, handler in bodies.items():
        registry.register_behavior(PREFIX + name, handler)
    for entry in data['reviewed_templates']:
        registry.register_assemble_reaction_source(AssembleReactionSource(entry['card_id'], entry['event'],
            entry['original_behavior_id'], entry['condition_id']))
        registry.register_assemble_template(AssembleTemplate(entry['card_id'],
            AssemblePrefix(entry['event'], tuple(Keyword(key) for key in entry['keywords']), condition_id=entry['condition_id']),
            AssembleSuffix(entry['body_behavior_id'], tuple(entry['allowed_timings']))))
