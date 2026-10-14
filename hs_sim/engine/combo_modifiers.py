"""Source-independent Combo policies with explicit two-window receipts."""
from dataclasses import dataclass, replace
from .effects import Effect, _integer, _player, _source
from .errors import ResolutionError
from .lifecycle import attachment_id
from .model import ComboRepeatModifier, ComboRepeatSpec, ComboPolicyReceipt, CardType


@dataclass(frozen=True)
class AddComboRepeatModifier(Effect):
    player_id: int
    spec: ComboRepeatSpec = ComboRepeatSpec()
    source_id: int | None = None
    uses: int | None = None
    expires_turn: int | None = None
    trigger: str = 'play'

    def __post_init__(self):
        if self.trigger not in ('play', 'activation'): raise ValueError('Unknown Combo policy trigger')
        _player(self.player_id); _source(self.source_id)
        if type(self.spec) is not ComboRepeatSpec: raise ValueError('Player Combo modifier requires repeat specification')
        self.spec.__post_init__()
        if self.spec.scope != 'friendly' or self.spec.match is not None and self.spec.match.source_eligibility is not None:
            raise ValueError('Player Combo policies have no physical board carrier')
        if self.uses is not None: _integer(self.uses, 'Combo modifier uses', 1)
        if self.expires_turn is not None: _integer(self.expires_turn, 'Combo modifier expiry', 1)


@dataclass(frozen=True)
class RemoveComboRepeatModifier(Effect):
    player_id: int
    modifier_id: int

    def __post_init__(self):
        _player(self.player_id); _integer(self.modifier_id, 'Combo modifier', 1)


def public_modifier(modifier, *, uses_remaining=None, consumed=False):
    from .combo_matching import combo_match_public_to_dict
    return dict(repetitions=modifier.spec.repetitions, kinds=[k.value for k in modifier.spec.kinds],
        scope=modifier.spec.scope, match=combo_match_public_to_dict(modifier.spec.match),
        uses_remaining=uses_remaining if consumed else modifier.uses_remaining,
        expires_turn=modifier.expires_turn, trigger=modifier.trigger)


def emit_change(r, kind, player_id, modifier, *, uses_remaining=None, play_id=None):
    r.emit(kind, player_id=player_id, modifier_id=modifier.id, policy_source_id=modifier.source_id,
        play_id=play_id, **public_modifier(modifier, uses_remaining=uses_remaining, consumed=kind=='combo_modifier_used'))


def add(r, effect):
    from .resolver import validate_attachment_source
    from .repeat_source_conditions import validate_source_declaration
    effect.__post_init__(); validate_source_declaration(r.registry, effect.spec, allow_source=False)
    validate_attachment_source(r, effect.source_id, effect.expires_turn)
    source=r.state.entities.get(effect.source_id)
    modifier=ComboRepeatModifier(attachment_id(r.state),effect.spec,effect.source_id,
        source.card_id if source else None,r.state.turn,effect.uses,effect.expires_turn,effect.trigger)
    r.player(effect.player_id).combo_modifiers.append(modifier)
    emit_change(r,'combo_modifier_added',effect.player_id,modifier)


def remove(r, effect):
    player=r.player(effect.player_id)
    modifier=next((m for m in player.combo_modifiers if m.id==effect.modifier_id),None)
    if modifier is None:return
    player.combo_modifiers.remove(modifier)
    emit_change(r,'combo_modifier_removed',player.id,modifier)


def receipt_at(state, receipt_id):
    _integer(receipt_id, 'Combo receipt', 1)
    if receipt_id > len(state.combo_policy_receipts): raise ValueError('Unknown Combo policy receipt')
    return state.combo_policy_receipts[receipt_id-1]


def receipt_player_id(state, receipt):
    receipt.__post_init__()
    if receipt.origin == 'generated_body': return receipt.player_id
    from .play_history import play_record
    return play_record(state, receipt.play_id).player_id


def captured_modifiers(state, play_id, phase=None):
    return tuple(m for receipt in state.combo_policy_receipts if receipt.play_id==play_id and
                 (phase is None or receipt.phase==phase) for m in receipt.modifiers)


def capture_from_state(state, registry, play, phase, recipient, eligible):
    from .combo_matching import validate_recipient
    from .combo_acceptance_matching import capture_player_modifiers
    if phase not in ('play', 'activation') or type(eligible) is not bool:
        raise ValueError('Invalid Combo policy acceptance phase or gate')
    validate_recipient(state, registry, recipient, play)
    return capture_player_modifiers(state, registry, play.player_id, phase, recipient, eligible)


def capture(r, play, phase, recipient, eligible):
    if play.kind not in (CardType.MINION,CardType.WEAPON,CardType.HERO):
        raise ResolutionError('Combo policy receipt requires a physical paid root')
    if any(x.play_id==play.id and x.phase==phase for x in r.state.combo_policy_receipts):
        raise ResolutionError('Combo policies were already captured for this phase')
    if any(not x.consumption_applied for x in r.state.combo_policy_receipts):
        raise ResolutionError('Previous Combo policy receipt has not consumed its accepted uses')
    modifiers=capture_from_state(r.state,r.registry,play,phase,recipient,eligible)
    receipt=ComboPolicyReceipt(len(r.state.combo_policy_receipts)+1,play.id,phase,
        r.state.turn,r.state.action_number,recipient,eligible,modifiers,False)
    r.state.combo_policy_receipts.append(receipt)
    return receipt


def consume(r, receipt):
    if receipt_at(r.state,receipt.id)!=receipt or receipt.consumption_applied:
        raise ResolutionError('Combo policy acceptance can consume its uses only once')
    player=r.player(receipt_player_id(r.state, receipt))
    original={m.id:m for m in receipt.modifiers}
    current={m.id:m for m in player.combo_modifiers}
    if any(current.get(identity)!=modifier for identity,modifier in original.items()):
        raise ResolutionError('Combo policy changed before its accepted consumption')
    changes=[];updated=[]
    for modifier in player.combo_modifiers:
        if modifier.id not in original or modifier.uses_remaining is None:
            updated.append(modifier);continue
        remaining=modifier.uses_remaining-1
        if remaining:updated.append(replace(modifier,uses_remaining=remaining))
        changes.append((modifier,remaining))
    player.combo_modifiers=updated
    r.state.combo_policy_receipts[receipt.id-1]=replace(receipt,consumption_applied=True)
    for modifier,remaining in changes:
        emit_change(r,'combo_modifier_used',player.id,modifier,uses_remaining=remaining,play_id=receipt.play_id)


def validate_receipts(state, registry):
    from .play_history import play_record
    from .combo_matching import validate_recipient, combo_repeat_recipient_matches
    from .repeat_source_conditions import validate_source_declaration
    from .spell_acceptance import _live_attachments
    if type(state.combo_policy_receipts) is not list:raise ValueError('Combo receipts require a list')
    keys=set();previous=(0,0);captured={};submissions={}
    for index,receipt in enumerate(state.combo_policy_receipts,1):
        if type(receipt) is not ComboPolicyReceipt:raise ValueError('Invalid Combo receipt')
        receipt.__post_init__()
        play = play_record(state, receipt.play_id) if receipt.origin == 'paid_hand' else None
        owner = receipt_player_id(state, receipt)
        key=(receipt.origin, receipt.play_id if play is not None else receipt.physical_child_id, receipt.phase)
        clock=(receipt.turn,receipt.action)
        if (receipt.id!=index or key in keys or not previous<=clock<=(state.turn,state.action_number) or
                play is not None and (receipt.turn!=play.turn or receipt.action<play.action) or
                not receipt.consumption_applied and index!=len(state.combo_policy_receipts)):
            raise ValueError('Invalid Combo receipt identity, capture chronology or staged position')
        definition=validate_recipient(state,registry,receipt.recipient,play)
        if play is None:
            from .generated_combo_repeats import validate_policy
            validate_policy(state, registry, receipt)
        elif receipt.phase=='play':
            if (play.combo_submission_receipt_id!=receipt.id or receipt.recipient.card_id!=play.card_id or
                    receipt.eligible!=bool(play.combos)):
                raise ValueError('Combo submission receipt differs from its submitted declaration')
            submissions[play.id]=receipt.id
        else:
            accepted=play.combo_acceptance
            if (play.id not in submissions or submissions[play.id]>=receipt.id or accepted is None or
                    accepted.policy_receipt_id!=receipt.id or accepted.recipient!=receipt.recipient or
                    receipt.eligible!=(accepted.status=='activated')):
                raise ValueError('Combo activation receipt differs from its accepted physical root')
        for modifier in receipt.modifiers:
            validate_source_declaration(registry,modifier.spec,allow_source=False)
            if (modifier.id>=state.next_attachment_id or modifier.created_turn>receipt.turn or
                    modifier.expires_turn is not None and modifier.expires_turn<receipt.turn or
                    modifier.source_id is not None and modifier.source_id not in state.entities or
                    not combo_repeat_recipient_matches(modifier.spec,recipient=receipt.recipient,recipient_definition=definition)):
                raise ValueError('Invalid captured Combo policy')
            if modifier.source_card_id is not None:registry.card(modifier.source_card_id)
            if modifier.id in captured:
                owner,old,applied=captured[modifier.id]
                remaining=old.uses_remaining
                if remaining is not None:remaining-=int(applied)
                if (owner!=receipt_player_id(state, receipt) or remaining is not None and remaining<1 or
                        modifier!=replace(old,uses_remaining=remaining)):
                    raise ValueError('Combo policy receipts disagree on remaining uses or owner')
            captured[modifier.id]=(receipt_player_id(state, receipt),modifier,receipt.consumption_applied)
        keys.add(key);previous=clock
    live=_live_attachments(state)
    for identity,(owner,old,applied) in captured.items():
        item=live.get(identity)
        if item is None:continue
        family,current_owner,current=item
        remaining=old.uses_remaining
        if remaining is not None:remaining-=int(applied)
        if (family!='combo_modifiers' or current_owner!=owner or remaining is not None and remaining<1 or
                current!=replace(old,uses_remaining=remaining)):
            raise ValueError('Surviving Combo policy differs from its last actual accepted use')


def expire(r, turn):
    expired=[]
    for player in r.state.players.values():
        keep=[]
        for modifier in player.combo_modifiers:
            if modifier.expires_turn is not None and modifier.expires_turn<=turn:
                expired.append((player.id,modifier))
            else:keep.append(modifier)
        player.combo_modifiers=keep
    for player_id,modifier in expired:emit_change(r,'combo_modifier_expired',player_id,modifier)
    return bool(expired)


def register(mechanics):
    mechanics.register(AddComboRepeatModifier,add)
    mechanics.register(RemoveComboRepeatModifier,remove)
