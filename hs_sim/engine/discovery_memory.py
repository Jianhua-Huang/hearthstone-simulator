"""Original pool selections stored on native Deathrattle attachments.

The shared pool/choice pipeline owns the discovery. Ordinary Buff and
SummonByCard own its actual effects; no hidden hand card is manufactured.
"""
from dataclasses import dataclass, fields, replace

from .effects import Buff, _integer
from .model import CardType, ChoicePurpose, Keyword, NativeDeathrattleSpec, Rarity, RememberedDiscovery
from .pools import DiscoverFromPool, PoolQuery
from .sacrifice import MinionReference, live_minion, reference_value

PROFILE = NativeDeathrattleSpec('discovery_summon')
QUERY = PoolQuery(kinds=(CardType.MINION,), collectible=True, class_mode='any',
                  rarities=(Rarity.LEGENDARY,), tribes_any=('beast',), keywords_none=(Keyword.COLOSSAL,))


@dataclass(frozen=True)
class DeathrattleDiscoveryTarget:
    battlecry_id: int
    reference: MinionReference | None
    ability_ids: tuple[int, ...]

    def __post_init__(self):
        _integer(self.battlecry_id, 'original discovery Battlecry', 1)
        if self.reference is not None: reference_value(self.reference)
        if type(self.ability_ids) is not tuple or len(set(self.ability_ids)) != len(self.ability_ids):
            raise ValueError('Discovery memory requires distinct original ability identities')
        for value in self.ability_ids: _integer(value, 'original discovery memory ability', 1)
        if self.reference is None and self.ability_ids:
            raise ValueError('A departed source cannot claim later memory abilities')


def validate_spec(spec):
    from .discovered_deathrattles import DiscoveredDeathrattleTarget,validate_spec as validate_printed
    if type(spec)is DiscoverFromPool and type(spec.memory_target)is DiscoveredDeathrattleTarget:
        return validate_printed(spec)
    from .colossal_crew import ColossalCrewTarget, validate_spec as validate_crew
    if type(spec) is DiscoverFromPool and type(spec.memory_target) is ColossalCrewTarget:
        return validate_crew(spec)
    from .discovery_guesses import DiscoveryGuessTarget, validate_spec as validate_guess
    if type(spec) is DiscoverFromPool and type(spec.memory_target) is DiscoveryGuessTarget:
        return validate_guess(spec)
    from .student_teaching import StudentTeachingTarget,validate_spec as validate_student
    if type(spec)is DiscoverFromPool and type(spec.memory_target)is StudentTeachingTarget:
        return validate_student(spec)
    if type(spec) is not DiscoverFromPool or type(spec.memory_target) is not DeathrattleDiscoveryTarget:
        raise ValueError('Memory discovery requires its typed original native target')
    spec.memory_target.__post_init__()
    plain = DiscoverFromPool(spec.player_id, spec.pool_id, QUERY,
        source_id=spec.source_id, prompt=spec.prompt)
    if (spec.destination != 'memory' or spec.source_id is None or
            any(getattr(spec, f.name) != getattr(plain, f.name)
                for f in fields(spec) if f.name not in ('destination', 'memory_target'))):
        raise ValueError('Native memory supports one plain any-class Legendary Beast discovery')


def validate_target(state, registry, spec, *, active=True):
    from .discovered_deathrattles import DiscoveredDeathrattleTarget,validate_target as validate_printed
    if type(spec.memory_target)is DiscoveredDeathrattleTarget:
        return validate_printed(state,registry,spec,active=active)
    from .colossal_crew import ColossalCrewTarget, validate_target as validate_crew
    if type(spec.memory_target) is ColossalCrewTarget:
        return validate_crew(state, registry, spec, active=active)
    from .discovery_guesses import DiscoveryGuessTarget, validate_target as validate_guess
    if type(spec.memory_target) is DiscoveryGuessTarget:
        return validate_guess(state, registry, spec, active=active)
    from .student_teaching import StudentTeachingTarget,validate_target as validate_student
    if type(spec.memory_target)is StudentTeachingTarget:
        return validate_student(state,registry,spec,active=active)
    validate_spec(spec); target = spec.memory_target
    from .battlecries import battlecry_record
    from .deathrattle_memory import validate_reference
    row = battlecry_record(state, target.battlecry_id)
    if ((row.source_id, row.player_id) != (spec.source_id, spec.player_id) or
            registry.card(row.payload.card_id).native_deathrattle != PROFILE or
            not row.payload_started or row.failure is not None or
            active and (row.completed or row.interrupted)):
        raise ValueError('Memory discovery lost its original native Battlecry')
    if target.reference is not None:
        if target.reference.entity_id != row.source_id:
            raise ValueError('Memory discovery borrowed another original physical source')
        validate_reference(state, target.reference, target.ability_ids)
    return row


def validate_link(state, registry, link):
    if type(link) is not RememberedDiscovery:
        raise ValueError('Expected a typed original discovered summon')
    link.__post_init__()
    from .battlecries import battlecry_record
    row = battlecry_record(state, link.battlecry_id)
    if not 1 <= link.discovery_id <= len(state.card_discovery_history):
        raise ValueError('Remembered discovery exceeds original selection history')
    discovery = state.card_discovery_history[link.discovery_id-1]
    result = discovery.result
    if (discovery.id != link.discovery_id or discovery.is_control or
            result.choice.purpose != ChoicePurpose.POOL_DISCOVERY or
            (result.choice.source_id, result.choice.player_id) != (row.source_id, row.player_id) or
            len(result.selected) != 1 or result.selected[0].card_id != link.card_id or
            not row.payload_started or row.failure is not None or
            registry.card(row.payload.card_id).native_deathrattle != PROFILE or
            registry.card(link.card_id).kind != CardType.MINION):
        raise ValueError('Remembered discovery differs from its original native selection')
    return row, discovery


def apply_selection(r, effect):
    spec = effect.batch.spec
    from .discovered_deathrattles import DiscoveredDeathrattleTarget,apply_selection as apply_printed
    if type(spec.memory_target)is DiscoveredDeathrattleTarget:return apply_printed(r,effect)
    from .colossal_crew import ColossalCrewTarget, apply_selection as apply_crew
    if type(spec.memory_target) is ColossalCrewTarget:
        return apply_crew(r, effect)
    from .discovery_guesses import DiscoveryGuessTarget, apply_selection as apply_guess
    if type(spec.memory_target) is DiscoveryGuessTarget:
        return apply_guess(r, effect)
    from .student_teaching import StudentTeachingTarget,apply_selection as teach_student
    if type(spec.memory_target)is StudentTeachingTarget:return teach_student(r,effect)
    validate_target(r.state, r.registry, spec)
    from .card_discoveries import require_original_result
    from .deathrattle_memory import validate_ability
    from .discovery_delivery import DiscoveryCompletion, FinishCardDiscovery, queue
    original = require_original_result(r.state, effect.choice_result)
    link = RememberedDiscovery(spec.memory_target.battlecry_id, original.id, effect.selection.card_id)
    validate_link(r.state, r.registry, link)
    target = spec.memory_target
    source = None if target.reference is None else live_minion(r.state, target.reference)
    work = ()
    if source is not None:
        replacements = {}
        for ability in source.abilities:
            if ability.id not in target.ability_ids: continue
            validate_ability(r.state, r.registry, ability)
            memory = ability.deathrattle_memory
            if memory is None or memory.spec != PROFILE:
                raise ValueError('Original discovered summon ability changed its native declaration')
            replacements[ability.id] = replace(ability, deathrattle_memory=replace(memory,
                discoveries=(*memory.discoveries, link)))
        # Store before ordinary stat notifications, which may kill this source.
        source.abilities = [replacements.get(a.id, a) for a in source.abilities]
        card = r.registry.card(link.card_id)
        work = (Buff(source.id, attack=card.attack, health=card.health, source_id=spec.source_id),)
    finish = queue(r, FinishCardDiscovery(DiscoveryCompletion(effect.choice_result, None)))
    return (*work, finish)


def validate_boundary(game):
    from .discovered_deathrattles import validate_boundary as validate_printed
    validate_printed(game)
    from .discovery_guesses import validate_boundary as validate_guesses
    validate_guesses(game)
    state = game._state
    memories = [a.deathrattle_memory for e in state.entities.values() for a in e.abilities]
    memories += [a.deathrattle_memory for death in state.death_history for a in death.abilities]
    memories += [row.capture.ability.deathrattle_memory for row in state.deathrattle_history]
    links = {link for memory in memories if memory is not None for link in memory.discoveries}
    if not links: return
    from .discovery import ResolvePoolDiscovery, validate_selection
    from .discovery_offers import offer_for_result
    for link in links:
        from .colossal_crew import is_crew_link, validate_link as validate_crew_link
        validator = validate_crew_link if is_crew_link(state, game.registry, link) else validate_link
        _, original = validator(state, game.registry, link)
        offer = offer_for_result(game, original.result)
        option = next(o for o in offer.options if o.id == original.result.selected_ids[0])
        if len(option.effects) != 1 or type(option.effects[0]) is not ResolvePoolDiscovery:
            raise ValueError('Remembered summon lost its original pool selection recipe')
        effect = option.effects[0]; spec = effect.batch.spec
        validate_target(state, game.registry, spec, active=False)
        if spec.memory_target.battlecry_id != link.battlecry_id or effect.selection.card_id != link.card_id:
            raise ValueError('Remembered summon borrowed another original Battlecry or selected face')
        validate_selection(game.registry, game._generation_context,
            replace(effect, choice_result=original.result))


def register(mechanics):
    from .discovered_deathrattles import register as register_printed
    register_printed(mechanics)
    from .discovery_guesses import register as register_guesses
    register_guesses(mechanics)
    mechanics.register_payload_type(DeathrattleDiscoveryTarget)
    from .colossal_crew import ColossalCrewTarget
    mechanics.register_payload_type(ColossalCrewTarget)
