"""Explicit paid Rewind producer with fresh physical authority and old selection.

The original manual profile and target IDs are preserved. Each retry captures a
new full target receipt at its actual normalized payment boundary; an initial
compact receipt is retained once, never recursively stacking earlier attempts.
This does not authorize fresh target selection or a generated whole origin.
"""
from copy import deepcopy
from dataclasses import replace
import json

from .actions import PlayCard
from .body_grants import BodyReference
from .body_target_authority import body_target_authorities
from .errors import IllegalAction
from .model import Keyword,PaidBodyTargetReceipt


def require_policy(state,registry,action):
    profile=registry.body_target_profile(action.body_target_profile_id)
    if profile.retry_targets!='reuse_original_selection':
        raise IllegalAction('Independent paid targets have no fresh Rewind retry producer')
    source=state.entities[action.entity_id]
    # Authorize every possible face structurally, without targets or callbacks.
    from .body_root_targets import validate_root_binding
    from .rewind import face_signature
    initial=registry.card(source.card_id);probe=deepcopy(state);entity=probe.entities[source.id]
    card=initial
    while True:
        validate_root_binding(registry,registry.body_root_target_binding(card.id,profile.id))
        body_target_authorities(probe,registry,BodyReference.capture(entity),profile.id)
        if card.rewind is None or card.rewind.next_card_id is None:break
        card=registry.card(card.rewind.next_card_id)
        if face_signature(card)!=face_signature(initial):raise IllegalAction('Retry face changed its underlying declaration')
        entity.card_id=card.id;entity.zone_epoch+=1
        if card.rewind is None:
            entity.abilities=[a for a in entity.abilities if not(a.kind=='keyword' and a.keyword==Keyword.REWIND)]
        from .lifecycle import refresh_entity
        refresh_entity(entity)


def retry_action(state,registry,original_action):
    """Only rebase a complete original vector; never choose, drop or add slots."""
    if type(original_action)is not PlayCard or original_action.body_target_profile_id is None:
        raise ValueError('Body retry requires its exact original paid action')
    original_action.__post_init__();require_policy(state,registry,original_action)
    source=state.entities[original_action.entity_id]
    authorities=body_target_authorities(state,registry,BodyReference.capture(source),original_action.body_target_profile_id)
    by_id={a.declaration.reference.ability_id:a.declaration.reference for a in authorities}
    if set(by_id)!={s.ability_id for s in original_action.body_targets}:
        raise IllegalAction('Body retry lost its complete original physical vector')
    from .paid_body_targets import _selection
    selected=[]
    for old in original_action.body_targets:
        new=_selection(by_id[old.ability_id],old.target_id)
        if replace(new,carrier_card_id=old.carrier_card_id,zone_epoch=old.zone_epoch)!=old:
            raise IllegalAction('Body retry substituted its original physical declaration')
        selected.append(new)
    return replace(original_action,body_targets=tuple(selected))


def attach_retry_origin(state,registry,receipt,quote,anchor,*,player_observation=None):
    from .rewind import HandSpellRewindAnchor,normalized_hand_play_retry
    if type(anchor)is not HandSpellRewindAnchor:raise ValueError('Body retry requires its actual typed Rewind session')
    anchor.__post_init__()
    if normalized_hand_play_retry(anchor,registry,state)!=state:
        raise ValueError('Body retry lost its exact normalized before/face/allocation boundary')
    expected=retry_action(state,registry,anchor.action)
    if receipt.action!=expected:raise ValueError('Body retry changed its original accepted selection')
    from .paid_body_targets import capture
    root=capture(anchor.before,registry,anchor.action,quote,player_observation=player_observation)
    result=replace(receipt,retry_root=root,retry_attempt=anchor.attempt,retry_event_start=anchor.event_start)
    result.__post_init__();return result


def accepted_zone_epoch(registry,play,receipt):
    paid=play.submitted_cost
    if receipt.retry_root is None:
        if paid.quote_origin=='rewind_root':raise ValueError('Body retry lost its original target root receipt')
        return paid.zone_epoch
    from .rewind import attempt_card_id
    root=receipt.retry_root;initial=json.loads(root.origin.source_json)
    card=registry.card(initial['card_id'])
    if card.rewind is None or receipt.retry_attempt>card.rewind.retries:
        raise ValueError('Body retry has no original remaining budget')
    if paid.quote_origin!='rewind_root' or attempt_card_id(registry,card.id,receipt.retry_attempt)!=play.card_id:
        raise ValueError('Body retry payment/card face differs from its original real attempt')
    # Each attempt restores the original face first, then applies exactly one
    # transition to that attempt's face; epochs do not accumulate discarded forms.
    return paid.zone_epoch+int(play.card_id!=card.id)


def validate_retry_origin(state,registry,play,original,source):
    receipt=play.body_targets;root=receipt.retry_root
    if root is None:return
    from .serialization import entity_from_dict
    initial=entity_from_dict(json.loads(root.origin.source_json));paid=play.submitted_cost
    if ((initial.card_id,initial.zone_epoch,root.origin.turn,root.origin.action)!=
        (paid.quote.quote_input.card_id,paid.zone_epoch,paid.turn,paid.action) or
        root.registry_fingerprint!=receipt.registry_fingerprint or root.origin.action>=receipt.origin.action):
        raise ValueError('Body retry root rewrote its original quotation face/window/registry')
    current=retry_action(original,registry,root.action)
    if current!=receipt.action:raise ValueError('Body retry rewrote its original profile or selected target vector')
    # Original declaration identity survives form progression. Revalidate the
    # complete initial target universe independently of the latest candidates.
    definition=registry.card(initial.card_id)
    initial_face=replace(play.played_face,card_id=initial.card_id,metadata=definition.metadata,spell_school=definition.spell_school)
    initial_copy=play.minion_copy_material
    if initial_copy is not None:
        from .permanent_minion_stats import value as permanent_value
        from .infused_battlecries import value as infused_value
        # Project the recipe with the same original hand face as this temporary
        # receipt view. The actual retry's stored recipe remains untouched.
        initial_copy=replace(initial_copy,source=replace(initial_copy.source,
            card_id=initial.card_id,kind=initial.kind,owner=initial.owner,controller=initial.controller,
            zone=initial.zone,zone_epoch=initial.zone_epoch,entered_order=initial.entered_order,
            next_entity_id=root.origin.next_entity_id),components=initial.components,jade_size=initial.jade_size,
            turn=root.origin.turn,action=root.origin.action,permanent_stats=permanent_value(initial),
            infused_damage=infused_value(initial))
    initial_play=replace(play,card_id=initial.card_id,action=root.origin.action,body_targets=root,played_face=initial_face,
        submitted_cost=replace(paid,quote_origin='current_hand'),battlecry_acceptance=None,combo_acceptance=None,
        paid_hand_close=None,paid_hand_interrupt=None,completed=False,interrupted=False,countered=False,
        combo_submission_receipt_id=None,minion_copy_material=initial_copy)
    from .paid_body_targets import validate_receipt
    validate_receipt(state,registry,initial_play)


def validate_retry_events(game):
    for play in game._state.play_history:
        receipt=play.body_targets
        if receipt is None or receipt.retry_root is None:continue
        start=receipt.retry_event_start
        if not 0<=start<=len(game._events):raise ValueError('Body retry event cursor exceeds actual history')
        markers=[e for e in game._events[start:] if e.kind=='timeline_rewound' and
            dict(e.data).get('event_start')==start and e.action<=play.action]
        if len(markers)!=receipt.retry_attempt or any(
            (e.amount,e.source_id,e.player_id)!=(n,play.source_id,play.player_id)
            for n,e in enumerate(markers,1)):
            raise ValueError('Body retry receipt differs from its actual original retry markers')


def receipt_from_dict(value,*,root=False):
    from .serialization import _row,_list
    from .actions import PlayBodyTarget,action_from_dict
    from .body_target_origin import origin_from_dict
    target=_row(value,PaidBodyTargetReceipt)
    if root and target['retry_root']is not None:raise ValueError('Body retry receipts cannot recursively nest attempts')
    action=_row(target['action'],PlayCard)
    # Internal receipts store all dataclass fields, including the empty plural
    # arrow sentinel. Public commands may only supply a nonempty target_ids.
    arrows=_list(action.pop('target_ids'),'receipt spell arrow targets')
    if arrows:action['target_ids']=arrows
    action['type']='play_card';target['action']=action_from_dict(action)
    target['selected']=tuple(PlayBodyTarget(**_row(v,PlayBodyTarget)) for v in _list(target['selected'],'selected bodies'))
    target['body_choices']=tuple(tuple(_list(v,'body candidates')) for v in _list(target['body_choices'],'body choices'))
    target['body_target_active']=tuple(_list(target['body_target_active'],'body activation flags'))
    target['root_choices']=tuple(_list(target['root_choices'],'root candidates'));target['origin']=origin_from_dict(target['origin'])
    if target['retry_root']is not None:target['retry_root']=receipt_from_dict(target['retry_root'],root=True)
    result=PaidBodyTargetReceipt(**target);result.__post_init__();return result
