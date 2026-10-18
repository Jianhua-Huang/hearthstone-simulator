"""One current-turn player program; ordinary health rules own conversion."""
from .errors import ResolutionError
from .model import HealthFlow, HealthOp, HealthRule, Zone
from .player_effects import ConsumePlayerEffect, consume

KIND = 'next_healing_damage'
RULE = HealthRule(HealthFlow.HEALING, HealthOp.CONVERT, source_relation='friendly')


def claim(r, state, packets, rules, pending_events):
    """Freeze one whole original healing batch, then consume all matching uses.

    No target packet can consume the source independently. Intrinsic lifesteal
    restorations of the original batch enter this same path as a complete group.
    Removal notifications remain in the atomic health batch's event buffer.
    """
    owners = set()
    for packet in packets:
        target = state.entities.get(packet.original_target_id)
        if (packet.original_flow == HealthFlow.HEALING and packet.source_controller in (1, 2) and
                target is not None and target.active and target.is_character and
                target.zone in (Zone.HERO, Zone.BOARD) and target.health > 0 and not target.doomed):
            owners.add(packet.source_controller)
    additions = []
    for player_id in sorted(owners):
        instances = tuple(e for e in r.state.players[player_id].player_effects
                          if r.registry.player_effect(e.spec_id).kind == KIND)
        for instance in instances:
            if instance.created_turn != state.turn:
                raise ResolutionError('Stale pending next-healing conversion')
            consume(r, ConsumePlayerEffect(player_id, instance), pending_events=pending_events)
            additions.append((instance.id, instance.source_id, player_id, RULE))
    return tuple(sorted((*rules, *additions), key=lambda row: row[0])) if additions else rules
