"""Shared pure current attack policies; attachments own lifecycle and identity."""
from dataclasses import dataclass
import operator

from .effects import Effect, _grant
from .lifecycle import active_abilities, attachment_id
from .model import (AbilityInstance, AttackPolicySpec, AttackPolicyCondition, CurrentTurnFactQuery,
                    AttackSourceBinding, AttackSourcePolicy, BoardPresenceReference, CardType, Keyword, Zone)
from .board_presence import attack_source_enabled, resolve_board_presence, validate_attack_source_binding


def _current_value(state, attacker, attribute, registry=None, *, condition=None):
    if attribute in ('attack', 'health', 'damage'):
        return getattr(attacker, attribute)
    if state is None:
        raise ValueError('Controller attack conditions require a current state')
    player = state.players[attacker.controller]
    if attribute == 'current_turn_fact_count':
        if type(condition) is not AttackPolicyCondition:
            raise ValueError('Current-turn count requires its typed condition')
        condition.__post_init__()
        from .turn_facts import current_turn_fact_count
        return current_turn_fact_count(state, attacker.controller, condition.turn_fact)
    if attribute == 'battlefield_minion_count':
        if type(condition) is not AttackPolicyCondition:
            raise ValueError('Battlefield count requires its typed condition')
        condition.__post_init__()
        owners = ((attacker.controller,) if condition.board_scope == 'friendly' else
                  (3 - attacker.controller,) if condition.board_scope == 'opponent' else (1, 2))
        count = 0
        for owner in owners:
            for entity_id in state.players[owner].board:
                entity = state.entities[entity_id]
                if entity.zone != Zone.BOARD or entity.kind != CardType.MINION:
                    continue
                if condition.board_presence != 'board_present' and (entity.health <= 0 or entity.doomed):
                    continue
                if condition.board_presence == 'active' and not entity.active:
                    continue
                count += 1
        return count
    if attribute == 'controller_armor':
        return state.entities[player.hero_id].armor
    if attribute == 'controller_hand_size':
        # Public size only. Never inspect hidden card names or modifiers.
        return len(player.hand)
    if attribute == 'controller_spell_damage':
        from .health_rules import spell_bonus
        if player.player_effects and registry is None:
            raise ValueError('Player effect spell damage conditions require the fixed registry')
        return spell_bonus(state, attacker.controller, registry)
    raise ValueError('Unsupported attack policy condition attribute')


def _enabled(state, attacker, spec, registry=None):
    comparisons = {'lt': operator.lt, 'le': operator.le, 'eq': operator.eq,
                   'ne': operator.ne, 'ge': operator.ge, 'gt': operator.gt}
    return all(comparisons[c.comparison](_current_value(state, attacker, c.attribute, registry, condition=c), c.value)
               for c in spec.conditions)


def current_policies(state, attacker, registry=None):
    """Hero weapon contributions are live views, never permanent hero grants."""
    carriers = [attacker]
    if state is not None and attacker.kind == CardType.HERO and attacker.controller == state.active_player:
        weapon = state.entities.get(state.players[attacker.controller].weapon_id)
        if (weapon is not None and weapon.kind == CardType.WEAPON and weapon.zone == Zone.WEAPON
                and weapon.controller == attacker.controller and weapon.durability > 0 and not weapon.doomed):
            carriers.append(weapon)
    from .printed_attack_permits import permitted_rows
    permits = {carrier.id: permitted_rows(state, carrier, registry) for carrier in carriers}
    return tuple(a.attack_policy for carrier in carriers
                 for a in active_abilities(carrier, 'attack_policy')
                 if a.id not in permits[carrier.id]
                 if (a.attack_source_binding is None or attack_source_enabled(state, a.attack_source_binding))
                 and _enabled(state, attacker, a.attack_policy, registry))


def attack_limit(state, attacker, registry=None):
    """Current total maximum: finite policies use max, None means unbounded."""
    limit = 4 if Keyword.MEGA_WINDFURY in attacker.keywords else 2 if Keyword.WINDFURY in attacker.keywords else 1
    for policy in current_policies(state, attacker, registry):
        if policy.mode == 'attacks_per_turn':
            if policy.attacks_per_turn is None:
                return None
            limit = max(limit, policy.attacks_per_turn)
    return limit


def has_action_remaining(state, attacker, registry=None):
    limit = attack_limit(state, attacker, registry)
    return limit is None or attacker.attacks_this_turn < limit


def attack_policy_error(state, attacker, defender, registry=None):
    """Restrictions concern voluntary attack submission, not Titan abilities."""
    policies = current_policies(state, attacker, registry)
    if any(p.mode == 'cannot_attack' for p in policies):
        return 'Current policy prevents attacking'
    if defender.kind == CardType.HERO and any(p.mode == 'cannot_attack_heroes' for p in policies):
        return 'Current policy prevents attacking heroes'
    return None


@dataclass(frozen=True)
class GrantAttackPolicy(Effect):
    target_id: int
    spec: AttackPolicySpec
    source_id: int | None = None
    expires_turn: int | None = None
    source_binding: AttackSourceBinding | None = None

    def __post_init__(self):
        _grant(self.target_id, self.source_id, self.expires_turn)
        if type(self.spec) is not AttackPolicySpec:
            raise ValueError('GrantAttackPolicy requires AttackPolicySpec')
        self.spec.__post_init__()
        if self.source_binding is not None:
            if type(self.source_binding) is not AttackSourceBinding:
                raise ValueError('GrantAttackPolicy requires typed source binding')
            self.source_binding.__post_init__()
            if self.source_id != self.source_binding.reference.entity_id:
                raise ValueError('Bound attack grant must identify its captured physical source')


def grant(r, effect):
    from .resolver import validate_attachment_source
    validate_attachment_source(r, effect.source_id, effect.expires_turn)
    if effect.source_binding is not None:
        validate_attack_source_binding(r.state, effect.source_binding)
        if resolve_board_presence(r.state, effect.source_binding.reference) is None:
            r.stale(effect, effect.source_id)
            return ()
    entity = r.state.entities.get(effect.target_id)
    if (entity is None or entity.kind not in (CardType.HERO, CardType.MINION, CardType.WEAPON)
            or entity.zone not in (Zone.HERO, Zone.BOARD, Zone.WEAPON) or not entity.active):
        r.stale(effect, effect.target_id)
        return ()
    ability = AbilityInstance(attachment_id(r.state), 'attack_policy', source_id=effect.source_id,
                             attack_policy=effect.spec, expires_turn=effect.expires_turn,
                             attack_source_binding=effect.source_binding)
    entity.abilities.append(ability)
    r.refresh_auras()
    r.emit('ability_granted', target_id=entity.id, source_id=effect.source_id,
           ability_id=ability.id, ability_kind=ability.kind)


def register(mechanics):
    from .printed_attack_permits import register as register_printed_permits
    register_printed_permits(mechanics)
    mechanics.register_payload_type(CurrentTurnFactQuery)
    mechanics.register_payload_type(AttackPolicyCondition)
    mechanics.register_payload_type(AttackPolicySpec)
    mechanics.register_payload_type(BoardPresenceReference)
    mechanics.register_payload_type(AttackSourcePolicy)
    mechanics.register_payload_type(AttackSourceBinding)
    mechanics.register(GrantAttackPolicy, grant)
