"""Damage preparation and immutable outcomes; mutation remains in the resolver."""
from dataclasses import dataclass

from .health_rules import PreparedHealth
from .model import CardType, Keyword, Zone, validate_combat_relation
from .attack_policies import has_action_remaining, attack_policy_error,ignores_taunt


def combat_relation_matches(attacker, defender, relation):
    """Pure structural relation, shared by capture, replacement and delivery."""
    validate_combat_relation(relation)
    if attacker.id == defender.id:
        return False
    if relation == 'opponent':
        return attacker.controller != defender.controller
    if relation == 'any_minions':
        return attacker.kind == defender.kind == CardType.MINION
    return (attacker.kind == defender.kind == CardType.MINION and
            attacker.controller == defender.controller)


def is_immune(state, entity, *, combat=None):
    """Current immunity; attack scope reuses the original window/exchange.

    The window exists during declaration reactions. At delivery the original
    resolver closes it, so a validated simultaneous exchange supplies its own
    attacker role. A defender does not acquire that role by being hit.
    """
    if Keyword.IMMUNE in entity.keywords:
        return True
    if (state is None or Keyword.IMMUNE_WHILE_ATTACKING not in entity.keywords or
            not entity.active or not entity.is_character or entity.zone not in (Zone.BOARD, Zone.HERO)):
        return False
    if combat is not None and combat.attacker_id == entity.id:
        return True
    return any(w.kind == 'attack' and w.source_id == entity.id and
               (entity.kind == CardType.HERO or w.attack_source_presence is not None and
                w.attack_source_presence.presence_id == entity.board_presence_id)
               for w in state.action_windows)


def attack_error(state, attacker_id, defender_id, player_id, *, ignore_frozen=False, registry=None):
    attacker, defender = state.entities.get(attacker_id), state.entities.get(defender_id)
    if (attacker is not None and not attacker.is_character) or (defender is not None and not defender.is_character):
        return 'Only characters can attack or be attacked'
    if attacker is None or attacker.controller != player_id or attacker.zone not in (Zone.BOARD, Zone.HERO):
        return 'Invalid attacker'
    if defender is None or defender.controller == player_id or defender.zone not in (Zone.BOARD, Zone.HERO):
        return 'Invalid defender'
    if not attacker.active or not defender.active or attacker.attack <= 0 or attacker.health <= 0 or attacker.doomed or defender.health <= 0 or defender.doomed:
        return 'Attacker or defender cannot participate in combat'
    if Keyword.TITAN in attacker.keywords and any(a.kind == 'activated' and not a.consumed for a in attacker.abilities):
        return 'Titan must use its remaining abilities before attacking'
    if Keyword.OLD_GOD in attacker.keywords and any(a.kind == 'activated' and not a.consumed for a in attacker.abilities):
        return 'Old God must use its remaining abilities before attacking'
    if not ignore_frozen and attacker.frozen:
        return 'Frozen characters cannot attack'
    if is_immune(state, defender) or Keyword.STEALTH in defender.keywords:
        return 'Cannot attack an immune or stealthed character'
    if not has_action_remaining(state, attacker, registry):
        return 'No attacks remaining'
    reason = attack_policy_error(state, attacker, defender, registry)
    if reason is not None:
        return reason
    if attacker.zone == Zone.BOARD and attacker.summoned_turn == state.turn:
        if not attacker.keywords & {Keyword.CHARGE, Keyword.TITAN, Keyword.OLD_GOD}:
            if Keyword.RUSH not in attacker.keywords or defender.zone == Zone.HERO:
                return 'New minion cannot attack this target'
    enemy = state.players[defender.controller]
    taunts = [i for i in enemy.board if state.entities[i].active and Keyword.TAUNT in state.entities[i].keywords
              and not is_immune(state, state.entities[i]) and Keyword.STEALTH not in state.entities[i].keywords]
    if taunts and defender_id not in taunts and not ignores_taunt(state,attacker):
        return 'A taunt minion must be attacked first'
    return None


def can_be_frozen(entity):
    """Current status eligibility, separate from damage/target immunity."""
    return Keyword.CANT_BE_FROZEN not in entity.keywords


def freeze_deadline(state, entity, *, ending_turn=False, registry=None):
    """The earliest controller end-turn after a lost attack opportunity."""
    from .owner_turns import owner_turn_index
    index = owner_turn_index(state, entity.controller)
    if entity.controller != state.active_player:
        return index + 1
    enemy = state.players[3 - entity.controller]
    from .minion_abilities import action_opportunity
    could_attack = action_opportunity(entity, ignore_frozen=True, state=state, registry=registry) or any(attack_error(state, entity.id, target, entity.controller, ignore_frozen=True, registry=registry) is None
                       for target in (enemy.hero_id, *enemy.board))
    return max(1, index if could_attack and not ending_turn else index + 1)


def apply_healing(entity, amount):
    """Shared numeric healing primitive, including healing inside damage batches."""
    actual = min(entity.damage, amount)
    entity.damage -= actual
    return actual


@dataclass(frozen=True)
class DamageResult:
    packet: PreparedHealth
    armor_absorbed: int = 0
    health_damage: int = 0
    prevention: str | None = None
    floor_prevented: int = 0

    @property
    def dealt(self):
        # Includes overkill and armor, excludes prevented damage.
        return self.armor_absorbed + self.health_damage

    def event_data(self):
        return dict(damage_kind=self.packet.damage_kind.value,
                    health_damage=self.health_damage, armor_absorbed=self.armor_absorbed,
                    floor_prevented=self.floor_prevented,
                    **self.packet.event_data())


def calculate_damage(packet, target, *, state=None, combat=None):
    if packet.prevented:
        return DamageResult(packet, prevention='rule_prevention')
    if packet.amount == 0:
        return DamageResult(packet, prevention='zero_damage')
    if is_immune(state, target, combat=combat):
        return DamageResult(packet, prevention='immune')
    if Keyword.DIVINE_SHIELD in target.keywords:
        return DamageResult(packet, prevention='divine_shield')
    armor = min(target.armor, packet.amount)
    remainder = packet.amount - armor
    health_damage = (min(remainder, max(0, target.health-packet.floor_plan.floor))
                     if packet.floor_plan is not None else remainder)
    return DamageResult(packet, armor, health_damage, floor_prevented=remainder-health_damage)
