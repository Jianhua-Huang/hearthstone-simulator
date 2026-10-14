"""Pure references to original physical board residence, independent of control and face."""
from .model import AttackSourceBinding, BoardPresenceReference, CardType, Zone


def capture_board_presence(state, entity_id):
    if type(entity_id) is not int or entity_id <= 0:
        raise ValueError('Board source identity must be a positive integer')
    entity = state.entities.get(entity_id)
    if entity is None:
        raise ValueError('Unknown physical board source')
    if (entity.zone != Zone.BOARD or entity.kind != CardType.MINION or
            type(entity.board_presence_id) is not int or entity.board_presence_id <= 0):
        raise ValueError('A physical board source must be captured during its board residence')
    return BoardPresenceReference(entity.id, entity.board_presence_id)


def validate_attack_source_binding(state, binding):
    if type(binding) is not AttackSourceBinding:
        raise ValueError('Expected AttackSourceBinding')
    binding.__post_init__()
    source = state.entities.get(binding.reference.entity_id)
    if source is None:
        raise ValueError('Unknown bound physical source')
    if binding.reference.presence_id >= state.next_order:
        raise ValueError('Bound residence identity has not been allocated')
    if binding.captured_zone_epoch is not None and binding.captured_zone_epoch > source.zone_epoch:
        raise ValueError('Bound source face epoch is in the future')


def resolve_board_presence(state, reference):
    if type(reference) is not BoardPresenceReference:
        raise ValueError('Expected BoardPresenceReference')
    reference.__post_init__()
    source = state.entities.get(reference.entity_id)
    if source is None:
        raise ValueError('Unknown original physical source')
    if (source.zone != Zone.BOARD or source.kind != CardType.MINION or
            source.board_presence_id != reference.presence_id):
        return None
    return source


def attack_source_enabled(state, binding):
    """Stale residence never rebinds; gates examine only that resident's current public facts."""
    if state is None:
        raise ValueError('Bound attack policies require the current state')
    validate_attack_source_binding(state, binding)
    source = resolve_board_presence(state, binding.reference)
    if source is None:
        return False
    policy = binding.policy
    if policy.presence != 'board_present' and (source.health <= 0 or source.doomed):
        return False
    if policy.presence == 'active' and not source.active:
        return False
    if policy.transform == 'captured_epoch' and source.zone_epoch != binding.captured_zone_epoch:
        return False
    return policy.silence == 'ignore' or not source.silenced
