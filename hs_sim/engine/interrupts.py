"""Serializable spell/attack windows, counters and explicit target replacement."""
from dataclasses import dataclass, replace

from .effects import Effect, Summon
from .errors import ResolutionError
from .model import ActionWindow, BoardPresenceReference, CardType, Zone, _int


def open_window(r, kind, player_id, source_id, target_id=None, forced=False, play_id=None,
                *, combat_relation='opponent', excess_to_hero=False):
    from .limited_triggers import spellburst_candidates
    candidates=spellburst_candidates(r.state,player_id) if kind=='spell' else ()
    presence = (BoardPresenceReference.capture(r.state, source_id)
                if kind == 'attack' and r.state.entities[source_id].kind == CardType.MINION else None)
    target_presence = (BoardPresenceReference.capture(r.state, target_id)
                if kind == 'attack' and r.state.entities[target_id].kind == CardType.MINION else None)
    window = ActionWindow(r.state.next_window_id, kind, player_id, source_id, target_id, forced,
                          play_id=play_id, spellburst_candidates=candidates, combat_relation=combat_relation,
                          attack_source_presence=presence, attack_target_presence=target_presence,
                          excess_to_hero=excess_to_hero)
    r.state.next_window_id += 1
    r.state.action_windows.append(window)
    return window


def find_window(state, window_id):
    return next((w for w in state.action_windows if w.id == window_id), None)


def attack_live(state, window):
    if window is None or window.kind != 'attack':
        return False
    attacker, defender = state.entities[window.source_id], state.entities[window.target_id]
    from .combat import combat_relation_matches
    from .board_presence import resolve_board_presence
    if any(ref is not None and resolve_board_presence(state, ref) is None
           for ref in (window.attack_source_presence, window.attack_target_presence)):
        return False
    return (all(e.active and e.is_character and e.zone in (Zone.BOARD, Zone.HERO) and e.health > 0 and not e.doomed
                for e in (attacker, defender)) and
            combat_relation_matches(attacker, defender, window.combat_relation))


def replaced_combatant(state, window):
    """Keep existing left-play handling; an old window never hits a new resident."""
    from .board_presence import resolve_board_presence
    for label, reference in (('attacker', window.attack_source_presence),
                             ('defender', window.attack_target_presence)):
        if reference is not None and state.entities[reference.entity_id].zone == Zone.BOARD and \
                resolve_board_presence(state, reference) is None:
            return label + '_left_original_board_residence'
    return None


def close_window(r, window_id):
    if not r.state.action_windows or r.state.action_windows[-1].id != window_id:
        raise ResolutionError('Action windows must close in stack order')
    return r.state.action_windows.pop()


@dataclass(frozen=True)
class WindowEffect(Effect):
    window_id: int

    def __post_init__(self):
        _int(self.window_id, 'action window', 1)


@dataclass(frozen=True)
class CounterCard(WindowEffect):
    """Counter a pending hand spell or minion; does not destroy an entity."""
    pass


@dataclass(frozen=True)
class CounterSpell(CounterCard):
    pass


@dataclass(frozen=True)
class CounterMinion(CounterCard):
    pass


@dataclass(frozen=True)
class ResolveSpell(WindowEffect):
    pass


@dataclass(frozen=True)
class SpellTargetPhase(WindowEffect):
    pass


@dataclass(frozen=True)
class ResolveAttack(WindowEffect):
    pass


@dataclass(frozen=True)
class RedirectAttack(WindowEffect):
    target_id: int

    def __post_init__(self):
        super().__post_init__()
        _int(self.target_id, 'new attack target', 1)


@dataclass(frozen=True)
class SummonAttackTarget(WindowEffect):
    player_id: int
    card_id: str

    def __post_init__(self):
        super().__post_init__()
        Summon(self.player_id, self.card_id)


@dataclass(frozen=True)
class RedirectSpellTarget(RedirectAttack):
    pass


@dataclass(frozen=True)
class SummonSpellTarget(SummonAttackTarget):
    pass


def counter(r, effect):
    kinds = ('spell',) if type(effect) is CounterSpell else ('minion',) if type(effect) is CounterMinion else ('spell', 'minion')
    window = mark_counter(r, effect.window_id, kinds)
    if window is not None:
        announce_counter(r, window)


def mark_counter(r, window_id, kinds=('spell', 'minion')):
    """Commit only; callers can spend a matching policy before publishing facts."""
    window = find_window(r.state, window_id)
    if window is None or window.kind not in kinds or window.countered:
        return None
    r.state.action_windows[r.state.action_windows.index(window)] = replace(window, countered=True)
    from .play_history import update_play
    update_play(r.state, window.play_id, countered=True)
    return window


def announce_counter(r, window):
    r.emit('spell_countered' if window.kind == 'spell' else 'minion_countered',
           source_id=window.source_id, player_id=window.player_id)


def spell_target_phase(r, effect):
    window = find_window(r.state, effect.window_id)
    if window is None or window.kind != 'spell' or window.target_phase or r.state.action_windows[-1].id != window.id:
        raise ResolutionError('Invalid spell target phase')
    window = replace(window, target_phase=True)
    r.state.action_windows[-1] = window
    from .native_target_acceptance import accept as accept_native_target,FinishNativeTarget
    native=accept_native_target(r,'manual_card',window) if not window.countered else None
    if native is not None:
        window=replace(window,target_id=native.selection.target_id)
        r.state.action_windows[-1]=window
    if not window.countered and window.target_id is not None:
        r.emit('spell_targeted', source_id=window.source_id, target_id=window.target_id,
               player_id=window.player_id, window_id=window.id)
    return [ResolveSpell(window.id),*(()if native is None else(FinishNativeTarget(native),))]


def resolve_spell(r, effect):
    from .lifecycle import active_abilities
    from .resolver import FinishPlay
    window = close_window(r, effect.window_id)
    if window.kind != 'spell':
        raise ResolutionError('Expected spell window')
    entity = r.state.entities[window.source_id]
    from .play_history import play_record
    from .spell_repeats import begin, payload
    record = play_record(r.state, window.play_id)
    from .spell_acceptance import accept_resolution
    record = accept_resolution(r, record, window.target_id)
    work = []
    if not window.countered:
        behaviors = record.spell_payload.behavior_ids
        count = record.spell_payload.casts
        work = (begin(r, record, window.target_id, count, behaviors) if count > 1 else
                payload(r, record, window.target_id, behaviors))
    else:
        from .spell_casts import begin_played
        begin_played(r, record, window.target_id, countered=True)
    work.append(FinishPlay(entity.id, window.player_id, window.target_id, record.id, window.spellburst_candidates))
    return work


def resolve_attack(r, effect):
    from .resolver import CombatDamage
    window = close_window(r, effect.window_id)
    if window.kind != 'attack':
        raise ResolutionError('Expected attack window')
    from .hero_attack_history import delivery
    link = delivery(r, window)
    from .character_attacks import delivery as deliver_character_attack
    character_window = deliver_character_attack(r, window)
    work = CombatDamage(window.source_id, window.target_id, window.forced,
                        combat_relation=window.combat_relation, hero_attack=link,
                        attack_window_id=character_window, excess_to_hero=window.excess_to_hero)
    reason = replaced_combatant(r.state, window)
    if reason is not None:
        from .hero_attack_history import cancel
        cancel(r, work, reason)
        from .character_attacks import cancel as cancel_character_attack
        cancel_character_attack(r, work, reason)
        r.emit('attack_cancelled', source_id=window.source_id, target_id=window.target_id, reason=reason)
        return []
    return [work]


def redirect(r, effect):
    from .combat import combat_relation_matches
    window = find_window(r.state, effect.window_id)
    target = r.state.entities.get(effect.target_id)
    if (not attack_live(r.state, window) or target is None or not target.active or not target.is_character or
            target.zone not in (Zone.BOARD, Zone.HERO) or target.health <= 0 or target.doomed or
            not combat_relation_matches(r.state.entities[window.source_id], target, window.combat_relation)):
        return
    presence = BoardPresenceReference.capture(r.state, target.id) if target.kind == CardType.MINION else None
    r.state.action_windows[r.state.action_windows.index(window)] = replace(window, target_id=target.id,
        attack_target_presence=presence)
    r.emit('attack_redirected', source_id=window.source_id, target_id=target.id, player_id=window.player_id,
           window_id=window.id, target_presence_id=None if presence is None else presence.presence_id)


def redirect_spell(r, effect):
    from .targeting import effective_target_spec
    window = find_window(r.state, effect.window_id)
    target = r.state.entities.get(effect.target_id)
    if window is None or window.kind != 'spell' or window.countered or not window.target_phase or window.target_id is None:
        return
    from .play_history import play_record, play_definition
    source=r.state.entities[window.source_id]
    spec = effective_target_spec(r.state,r.registry,source,play_definition(r.state,r.registry,source,play_record(r.state,window.play_id)))
    if (spec is None or target is None or not target.active or target.zone not in spec.zones or
            target.kind not in spec.kinds or not target.is_character or target.health <= 0 or target.doomed):
        return
    # Replacement is not voluntary targeting: retain the structural domain, but
    # do not rerun friendly/enemy, stealth, or selection-only card predicates.
    r.state.action_windows[r.state.action_windows.index(window)] = replace(window, target_id=target.id)
    r.emit('spell_redirected', source_id=window.source_id, target_id=target.id, player_id=window.player_id)


def summon_target(r, effect):
    from .resolver import summon_entity
    window = find_window(r.state, effect.window_id)
    if not attack_live(r.state, window):
        return
    same = effect.player_id == r.state.entities[window.source_id].controller
    if (window.combat_relation == 'opponent' and same or
            window.combat_relation == 'friendly_minions' and not same):
        raise ResolutionError('Summoned attack target does not match the captured combat relation')
    entity = summon_entity(r, Summon(effect.player_id, effect.card_id))
    if entity is not None:
        # Use the returned entity, never a guessed ID or a scan of the board.
        redirect(r, RedirectAttack(window.id, entity.id))
        from .colossal import enter_minion
        return enter_minion(r,entity,'summon')


def summon_spell_target(r, effect):
    from .resolver import summon_entity
    window = find_window(r.state, effect.window_id)
    if window is None or window.kind != 'spell' or window.countered or not window.target_phase or window.target_id is None:
        return
    entity = summon_entity(r, Summon(effect.player_id, effect.card_id))
    if entity is not None:
        redirect_spell(r, RedirectSpellTarget(window.id, entity.id))
        from .colossal import enter_minion
        return enter_minion(r,entity,'summon')


def register_interrupts(mechanics):
    from .minion_plays import register
    register(mechanics)
    for effect, handler in ((CounterCard, counter), (CounterMinion, counter), (CounterSpell, counter), (SpellTargetPhase, spell_target_phase), (ResolveSpell, resolve_spell),
            (ResolveAttack, resolve_attack), (RedirectAttack, redirect), (SummonAttackTarget, summon_target),
            (RedirectSpellTarget, redirect_spell), (SummonSpellTarget, summon_spell_target)):
        mechanics.register(effect, handler)
