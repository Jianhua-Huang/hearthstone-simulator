"""Initial board destination of a physical hand play, separate from its actor."""
from .model import CardType


def validate_definition(definition):
    if type(definition.disguised) is not bool:
        raise ValueError('Disguised must be an explicit boolean')
    if definition.disguised and (
            definition.kind != CardType.MINION or not definition.hand_playable or
            definition.starship_for or definition.magnetic_tribes or definition.colossal or
            definition.choose_one is not None or definition.requires_target or
            definition.targeting is not None):
        raise ValueError('Disguised requires an ordinary minion without an unsupported placement or target contract')


def destination(definition, player_id, board_player_id=None):
    """Omitted destination always means the actor's side, including replays."""
    if type(player_id) is not int or player_id not in (1, 2):
        raise ValueError('Invalid hand play actor')
    if board_player_id is None:
        return player_id
    if type(board_player_id) is not int or board_player_id not in (1, 2):
        raise ValueError('Invalid hand play board player')
    if not definition.disguised or definition.kind != CardType.MINION:
        raise ValueError('Only Disguised hand minions can select a board side')
    return board_player_id


def play_destination(registry, play):
    return destination(registry.card(play.card_id), play.player_id, play.board_player_id)
