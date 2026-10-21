"""Shared actual card admission and source-local ordinary action enumeration."""
from .actions import PlayCard
from .costs import payment_error, quote_cost
from .errors import IllegalAction
from .model import CardType
from .targeting import target_error, target_choices


def root_target_contract(game, action):
    """Original special root/legacy routing, before ordinary action admission."""
    if action.body_target_profile_id is not None:
        from .paid_body_targets import capture, root_definition
        capture(game._state, game.registry, action, game=game)
        return root_definition(game._state, game.registry, action)
    source = game._state.entities.get(action.entity_id)
    if source is not None and any(card_id == source.card_id for card_id, _ in game.registry.body_root_target_bindings):
        raise IllegalAction('This carrier requires its complete independent paid body target vector')
    if source is not None:
        from .indirect_body_targets import require_legacy_paid_scope
        require_legacy_paid_scope(game.registry,source)
    return None


def validate_hand_play(state, registry, rules, action, *, context=None, play_target_definition=None):
    """The actual per-card admission, independent of the global turn/choice gate."""
    player = state.players[action.player_id]
    if action.entity_id not in player.hand:
        raise IllegalAction('Card is not in the active player\'s hand')
    entity = state.entities[action.entity_id]
    from .prepare import play_error
    if reason := play_error(state, entity):
        raise IllegalAction(reason)
    definition = registry.card(entity.card_id)
    if not definition.hand_playable:
        raise IllegalAction('This card type cannot be played')
    if not definition.manual_playable:
        raise IllegalAction('This card cannot be manually played from hand')
    from .play_requirements import manual_requirement_error
    if reason := manual_requirement_error(state, registry, entity):
        raise IllegalAction(reason)
    from .player_effects import manual_play_allowed
    if not manual_play_allowed(state, registry, player.id, definition.kind):
        raise IllegalAction('Current-turn rule prohibits manually playing this card type')
    from .disguised import destination
    try:
        board_player_id = destination(definition, player.id, action.board_player_id)
    except ValueError as error:
        raise IllegalAction(str(error)) from error
    if definition.disguised and action.body_target_profile_id is not None:
        raise IllegalAction('Disguised independent play does not accept a special body target route')
    from .choose_one import selection_error
    if reason := selection_error(state,definition,player.id,action.branch_id,rules,entity=entity):
        raise IllegalAction(reason)
    from .quests import activation_error
    if reason := activation_error(state, registry, rules, player.id, entity.card_id):
        raise IllegalAction(reason)
    from .player_effects import activation_error as ongoing_error
    if reason := ongoing_error(state, registry, rules, player.id, entity.card_id):
        raise IllegalAction(reason)
    from .secrets import activation_error as secret_error
    if reason := secret_error(state, registry, rules, player.id, entity.card_id):
        raise IllegalAction(reason)
    if reason := payment_error(state, quote_cost(state, registry, entity)):
        raise IllegalAction(reason)
    if definition.kind in (CardType.MINION, CardType.LOCATION):
        from .magnetic import host_at_position
        board = state.players[board_player_id].board
        if len(board) >= rules.max_board and host_at_position(state,registry,entity,action.position) is None:
            raise IllegalAction('Board is full')
        if action.position is not None and action.position > len(board):
            raise IllegalAction('Invalid board position')
    elif action.position is not None:
        raise IllegalAction('Only minions and locations can specify a board position')
    from .magnetic import play_definition as placed_definition
    if play_target_definition is None:
        target_definition = placed_definition(state, registry, entity,action.position,branch_id=action.branch_id)
    else:
        from .model import CardDefinition
        if type(play_target_definition) is not CardDefinition or (
                play_target_definition.id, play_target_definition.kind) != (definition.id, definition.kind):
            raise IllegalAction('Internal root target contract differs from the actual carrier')
        target_definition = play_target_definition
    reason = target_error(state, registry, entity, target_definition, action.target_id, context_factory=context)
    if reason is not None:
        raise IllegalAction(reason)
    from .spell_target_groups import hand_selection
    try:
        hand_selection(state, registry, entity, action.target_ids)
    except ValueError as error:
        raise IllegalAction(str(error)) from error
    return


def hand_plays(game, source, *, validator, context=None, first_only=False):
    """Ordinary hand PlayCards for one source, shared with hypothetical admission."""
    from .player_api import context_factory
    state = game._state
    player = state.players[source.controller]
    enemy = state.players[3-player.id]
    entity_id = source.id
    definition = game.registry.card(source.card_id)
    if context is None:
        context = context_factory(game, player.id)
    result = []
    if not definition.manual_playable:
        return ()
    from .player_effects import manual_play_allowed
    if not manual_play_allowed(state, game.registry, player.id, definition.kind):
        return ()
    from .magnetic import play_definition as placed_definition
    from .choose_one import branches, effective
    from .body_player_commands import bound_profiles
    if bound_profiles(game,state.entities[entity_id]):return ()
    sides = (None, enemy.id) if definition.disguised else (None,)
    for board_player_id in sides:
        board = state.players[player.id if board_player_id is None else board_player_id].board
        positions = range(len(board) + 1) if definition.kind in (CardType.MINION, CardType.LOCATION) else [None]
        for position in positions:
            for branch_id in branches(state,definition,player.id,entity=state.entities[entity_id]):
                from .spell_target_groups import hand_plan, spell_target_group_selections
                group = hand_plan(state, game.registry, source)
                choices = ([(target, ()) for target in target_choices(state,game.registry,state.entities[entity_id],placed_definition(state,game.registry,state.entities[entity_id],position,branch_id=branch_id),context_factory=context)]
                    if group is None else ((row.target_ids[0], row.target_ids) for row in spell_target_group_selections(group)))
                for target, target_ids in choices:
                    candidate = PlayCard(player.id, entity_id, target, position, branch_id,
                        board_player_id=board_player_id, target_ids=target_ids)
                    try:
                        validator(candidate)
                    except IllegalAction:
                        continue
                    result.append(candidate)
                    if first_only:
                        return tuple(result)
    return tuple(result)
