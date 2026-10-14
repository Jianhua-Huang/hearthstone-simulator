"""Source-independent player Battlecry counts, finite uses and global-turn expiry.

Matching policies combine by max with board auras; every matching finite policy
is consumed once at hand-payload capture, independently of repetition/outcomes.
These policies do not occupy objective, sigil, secret or board capacity (R-115).
"""
from dataclasses import dataclass, replace
from .effects import Effect, _integer, _player, _source
from .errors import ResolutionError
from .lifecycle import attachment_id
from .model import BattlecryRepeatModifier, BattlecryRepeatSpec


@dataclass(frozen=True)
class AddBattlecryRepeatModifier(Effect):
    player_id: int
    spec: BattlecryRepeatSpec = BattlecryRepeatSpec()
    source_id: int | None = None
    uses: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _player(self.player_id); _source(self.source_id)
        if type(self.spec) is not BattlecryRepeatSpec: raise ValueError('Player Battlecry modifier requires repeat specification')
        self.spec.__post_init__()
        if self.spec.scope != 'friendly':
            raise ValueError('Player Battlecry policies cannot require a physical self carrier')
        if self.spec.match is not None and self.spec.match.source_eligibility is not None:
            raise ValueError('Player Battlecry policies cannot require a physical board carrier')
        if self.uses is not None: _integer(self.uses, 'Battlecry modifier uses', 1)
        if self.expires_turn is not None: _integer(self.expires_turn, 'Battlecry modifier expiry', 1)


@dataclass(frozen=True)
class RemoveBattlecryRepeatModifier(Effect):
    player_id: int
    modifier_id: int

    def __post_init__(self):
        _player(self.player_id); _integer(self.modifier_id, 'Battlecry modifier', 1)


def public_modifier(modifier, *, uses_remaining=None, consumed=False):
    """Public rule facts only; no attachment identity or hidden source identity."""
    from .battlecry_matching import battlecry_match_public_to_dict
    return dict(repetitions=modifier.spec.repetitions, kinds=[k.value for k in modifier.spec.kinds],
        scope=modifier.spec.scope, match=battlecry_match_public_to_dict(modifier.spec.match),
        uses_remaining=uses_remaining if consumed else modifier.uses_remaining,
        expires_turn=modifier.expires_turn)


def emit_change(r, kind, player_id, modifier, *, uses_remaining=None, play_id=None):
    # Keep host provenance in diagnostic fields, not source/target slots. Public
    # event projection intentionally whitelists only the rule facts above.
    r.emit(kind, player_id=player_id, modifier_id=modifier.id, policy_source_id=modifier.source_id,
        play_id=play_id, **public_modifier(modifier,uses_remaining=uses_remaining,consumed=kind=='battlecry_modifier_used'))


def add(r, effect):
    from .resolver import validate_attachment_source
    effect.__post_init__()
    validate_attachment_source(r,effect.source_id,effect.expires_turn)
    source=r.state.entities.get(effect.source_id)
    modifier=BattlecryRepeatModifier(attachment_id(r.state),effect.spec,effect.source_id,
        source.card_id if source else None,r.state.turn,effect.uses,effect.expires_turn)
    r.player(effect.player_id).battlecry_modifiers.append(modifier)
    emit_change(r,'battlecry_modifier_added',effect.player_id,modifier)


def remove(r, effect):
    player=r.player(effect.player_id)
    modifier=next((m for m in player.battlecry_modifiers if m.id==effect.modifier_id),None)
    if modifier is None:return
    player.battlecry_modifiers.remove(modifier)
    emit_change(r,'battlecry_modifier_removed',player.id,modifier)


def consume(r, player_id, plan, play_id):
    """Capture is already frozen; matching finite policies consume atomically."""
    from .play_history import play_record
    from .battlecry_policy_uses import consume as consume_uses
    accepted = play_record(r.state, play_id).battlecry_acceptance
    if accepted is None or accepted.player_id != player_id or accepted.plan != plan:
        raise ResolutionError('Battlecry consumption lost its original paid acceptance')
    _, changes = consume_uses(r, origin='paid_hand', origin_id=play_id, player_id=player_id,
        recipient=accepted.recipient, plan=plan)
    for modifier,remaining in changes:
        emit_change(r,'battlecry_modifier_used',player_id,modifier,uses_remaining=remaining,play_id=play_id)


def expire(r, turn):
    expired=[]
    for player in r.state.players.values():
        keep=[]
        for modifier in player.battlecry_modifiers:
            if modifier.expires_turn is not None and modifier.expires_turn<=turn:
                expired.append((player.id,modifier))
            else:keep.append(modifier)
        player.battlecry_modifiers=keep
    for player_id,modifier in expired:emit_change(r,'battlecry_modifier_expired',player_id,modifier)
    return bool(expired)


def register(mechanics):
    mechanics.register(AddBattlecryRepeatModifier,add)
    mechanics.register(RemoveBattlecryRepeatModifier,remove)
