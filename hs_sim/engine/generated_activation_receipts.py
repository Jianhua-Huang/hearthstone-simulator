"""Independent acceptance of a real generated whole-card primary body.

This receipt is host-only. The currently executable origin is whole-card history
with generated_after_install_v1; source-specific repetition policies are separate.
Neither the selected historical occurrence nor this activation is a paid play.
Pending work rederives the receipt from the complete original acceptance state.
Compact settled receipts preserve consistency, not unsigned-save authenticity.
"""
from dataclasses import dataclass, fields

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .model import CardType, Zone
from .whole_card_history import integer
from .whole_card_replay_ledger import ReplayCasterFact


ORIGIN = 'whole_card_history'
PROFILE = 'generated_after_install_v1'
REPEAT_PROFILE = 'generated_battlecry_repeat_after_install_v1'
FAMILY_PROFILE = 'generated_family_repeat_after_install_v1'
RETAINED_PROFILE = 'generated_retained_family_after_install_v1'


@dataclass(frozen=True)
class GeneratedActivationReceipt:
    origin: str
    profile_id: str
    root_id: int
    child_id: int
    occurrence_id: int
    parent_child_id: int | None
    player_id: int
    issuer: ReplayCasterFact
    source: SourceAllocationFact
    turn: int
    action: int
    owner_turn_id: int
    owner_clocks: tuple[int, int]
    before_play_id: int
    combo_play_ids: tuple[int, ...]
    max_mana: int
    target_id: int | None
    combo: bool
    manathirst: bool

    def __post_init__(self):
        if self.origin != ORIGIN or self.profile_id not in (PROFILE, REPEAT_PROFILE, FAMILY_PROFILE, RETAINED_PROFILE):
            raise ValueError('Unknown generated activation origin/profile')
        for name in ('root_id', 'child_id', 'occurrence_id', 'turn', 'owner_turn_id', 'before_play_id'):
            integer(getattr(self, name), 'generated activation ' + name)
        for name in ('action', 'max_mana'):
            integer(getattr(self, name), 'generated activation ' + name, 0)
        for name in ('parent_child_id', 'target_id'):
            if getattr(self, name) is not None: integer(getattr(self, name), name)
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Generated executor requires its independent player seat')
        if type(self.issuer) is not ReplayCasterFact or type(self.source) is not SourceAllocationFact:
            raise ValueError('Generated activation lost its separate issuer/primary allocation')
        self.issuer.__post_init__(); self.source.__post_init__()
        if (self.source.controller != self.player_id or self.source.kind not in
                (CardType.MINION, CardType.WEAPON, CardType.LOCATION, CardType.HERO)
                or self.source.zone != (Zone.HERO if self.source.kind == CardType.HERO else
                    Zone.WEAPON if self.source.kind == CardType.WEAPON else Zone.BOARD)):
            raise ValueError('Generated acceptance requires its actual installed primary carrier')
        if type(self.owner_clocks) is not tuple or len(self.owner_clocks) != 2:
            raise ValueError('Generated acceptance requires both original owner clocks')
        for clock in self.owner_clocks: integer(clock, 'accepted owner clock', 0)
        if type(self.combo_play_ids) is not tuple:
            raise ValueError('Generated Combo requires its complete immutable paid-history prefix')
        for identity in self.combo_play_ids: integer(identity, 'Combo prerequisite play')
        if (tuple(sorted(set(self.combo_play_ids))) != self.combo_play_ids
                or any(i >= self.before_play_id for i in self.combo_play_ids)
                or type(self.combo) is not bool or type(self.manathirst) is not bool
                or self.combo != bool(self.combo_play_ids)):
            raise ValueError('Generated Combo differs from its exact accepted paid-history prefix')

    @property
    def key(self):
        return self.origin, self.root_id, self.child_id


def owner_clocks(state, before_owner_id):
    return tuple(max((row.owner_index for row in state.owner_turn_history[:before_owner_id]
        if row.player_id == player), default=0) for player in (1, 2))


def prerequisite_plays(state, player_id, turn, before_play_id):
    from .play_history import played_cards
    return tuple(p.id for p in played_cards(state, player_id, turn=turn, before_id=before_play_id))


def capture(state, registry, root, child, source, target_id, profile_id=PROFILE):
    from .owner_turns import current_owner_turn
    interval = current_owner_turn(state)
    before_play_id = len(state.play_history) + 1
    plays = prerequisite_plays(state, root.player_id, state.turn, before_play_id)
    card = registry.card(source.card_id)
    max_mana = state.players[root.player_id].max_mana
    receipt = GeneratedActivationReceipt(ORIGIN, profile_id, root.id, child.id, child.occurrence_id,
        root.parent_child_id, root.player_id, root.caster, source, state.turn, state.action_number,
        interval.id, owner_clocks(state, interval.id), before_play_id, plays, max_mana, target_id,
        bool(plays), card.manathirst is not None and max_mana >= card.manathirst)
    validate(state, registry, receipt, root, child)
    return receipt


def validate(state, registry, receipt, root, child):
    """Validate frozen operands without recapturing a later entity or policy."""
    if type(receipt) is not GeneratedActivationReceipt: raise ValueError('Missing independent generated acceptance')
    receipt.__post_init__(); validate_allocation(state, registry, receipt.source)
    if ((receipt.root_id, receipt.child_id, receipt.occurrence_id, receipt.parent_child_id,
            receipt.player_id, receipt.issuer) !=
            (root.id, child.id, child.occurrence_id, root.parent_child_id, root.player_id, root.caster)
            or (receipt.source.card_id, receipt.source.kind) != (child.card_id, child.kind)
            or root.runtime_route != 'cards_v1'):
        raise ValueError('Generated acceptance borrowed another root/child/source occurrence')
    if (receipt.turn < root.accepted_turn or receipt.turn > state.turn
            or receipt.action < root.accepted_action or receipt.action > state.action_number
            or receipt.owner_turn_id > len(state.owner_turn_history)
            or receipt.owner_turn_id < root.owner_turn_id
            or receipt.before_play_id > len(state.play_history) + 1):
        raise ValueError('Generated acceptance changed its original history/clock bounds')
    interval = state.owner_turn_history[receipt.owner_turn_id - 1]
    if (interval.turn != receipt.turn or receipt.action < interval.start_action
            or interval.closed_action is not None and receipt.action > interval.closed_action
            or receipt.owner_clocks != owner_clocks(state, receipt.owner_turn_id)):
        raise ValueError('Generated activation lost its actual owner interval and clocks')
    # All earlier roots are committed before this window, including countered
    # plays. A later root/choice action must never become an old prerequisite.
    prefix = state.play_history[:receipt.before_play_id - 1]
    if (any(p.turn > receipt.turn or p.action > receipt.action for p in prefix)
            or receipt.before_play_id <= len(state.play_history) and
                state.play_history[receipt.before_play_id - 1].action <= receipt.action
            or receipt.combo_play_ids != prerequisite_plays(state, receipt.player_id,
                receipt.turn, receipt.before_play_id)):
        raise ValueError('Generated acceptance erased or borrowed a paid-history prerequisite')
    card = registry.card(receipt.source.card_id)
    if receipt.manathirst != (card.manathirst is not None and receipt.max_mana >= card.manathirst):
        raise ValueError('Generated Manathirst differs from its frozen maximum mana')
    if receipt.target_id is not None and receipt.target_id not in state.entities:
        raise ValueError('Generated acceptance lost its original physical target')


def receipt_from_dict(value):
    if type(value) is not dict or set(value) != {f.name for f in fields(GeneratedActivationReceipt)}:
        raise ValueError('Generated acceptance requires exactly its complete wire fields')
    data = dict(value)
    if type(data['issuer']) is not dict or set(data['issuer']) != {f.name for f in fields(ReplayCasterFact)}:
        raise ValueError('Generated issuer requires its complete original caster fields')
    issuer = dict(data['issuer']); issuer['kind'] = CardType(issuer['kind']); issuer['zone'] = Zone(issuer['zone'])
    data['issuer'] = ReplayCasterFact(**issuer)
    data['source'] = allocation_from_dict(data['source'])
    for name in ('owner_clocks', 'combo_play_ids'):
        if type(data[name]) is not list: raise ValueError('Generated acceptance requires complete ordered arrays')
        data[name] = tuple(data[name])
    return GeneratedActivationReceipt(**data)
