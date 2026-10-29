"""Connect an attributed pool entry to its already accepted attack window."""
from dataclasses import dataclass, replace

from .allocation_facts import SourceAllocationFact, validate_allocation
from .model import ActionWindow, CardType, Zone
from .effects import Effect


@dataclass(frozen=True)
class TransformAttackedMinion(Effect):
    window: ActionWindow
    source: SourceAllocationFact
    target: SourceAllocationFact

    def __post_init__(self):
        if type(self.window) is not ActionWindow or any(type(x) is not SourceAllocationFact for x in (self.source,self.target)):
            raise ValueError('Attacked transformation requires its original window and physical allocations')
        self.window.__post_init__();self.source.__post_init__();self.target.__post_init__()
        if (self.window.kind!='attack' or self.window.attack_target_presence is None or
                self.window.target_id!=self.target.entity_id or self.target.kind!=CardType.MINION or self.target.zone!=Zone.BOARD or
                self.source.kind!=CardType.SPELL or self.source.zone!=Zone.GRAVEYARD or self.target.controller!=self.source.controller):
            raise ValueError('Attacked transformation lost its captured friendly defender and revealed Secret')

    def validate_in_state(self,state,registry,events=None):
        self.__post_init__()
        for fact in (self.source,self.target):validate_allocation(state,registry,fact)
        validate_original_window(state,self.window)
        if registry.card(self.source.card_id).secret is None or self.window.attack_target_presence.presence_id>=state.next_order:
            raise ValueError('Attacked transformation borrowed an unknown Secret or future residence')
        if events is not None:
            validate_acceptance_window(state,self.window,self.source,events)


def transform_attacked(r,effect):
    effect.validate_in_state(r.state,r.registry,r.game._events)
    from .board_presence import resolve_board_presence
    from .sacrifice import MinionReference
    from .cross_zone import TransformMinionFromPool
    entity=resolve_board_presence(r.state,effect.window.attack_target_presence)
    if entity is None or not entity.active or entity.health<=0 or entity.doomed:
        return ()
    return (TransformMinionFromPool(MinionReference.capture(entity),'constructed.cards',3,
        cost_basis='local',source_id=effect.source.entity_id),)


def validate_original_window(state,window):
    from .character_attacks import record
    row=record(state,window.id);original=row.declaration
    if (replace(window,target_id=original.target_id,attack_target_presence=original.attack_target_presence,
            combat_relation=original.combat_relation)!=original or window.id>=state.next_window_id):
        raise ValueError('Defender effect borrowed a foreign original attack window')
    return row


def validate_acceptance_window(state,window,source,events):
    from .attack_redirects import validate_reveal
    from .hero_health_history import effective_events
    from .model import BoardPresenceReference
    validate_reveal(state,window.id,source,events)
    row=validate_original_window(state,window);selected=row.declaration
    effective=effective_events(events)
    reveal=next(e for e in effective if e.kind=='secret_revealed' and
        (e.source_id,e.player_id)==(source.entity_id,source.controller) and e.sequence>row.declaration_event_cursor)
    for event in effective:
        if event.sequence>=reveal.sequence:break
        data=dict(event.data)
        if event.kind!='attack_redirected' or data.get('window_id')!=window.id:continue
        ident=data.get('target_presence_id');presence=None if ident is None else BoardPresenceReference(event.target_id,ident)
        relation='any_characters' if data.get('secret_attack_redirect') is True else 'opponent' if data.get('native_random_target') is True else selected.combat_relation
        selected=replace(selected,target_id=event.target_id,attack_target_presence=presence,combat_relation=relation)
    if selected!=window:
        raise ValueError('Defender effect changed the original window accepted by this Secret')


def validate_shape(window, source):
    if type(window) is not ActionWindow or type(source) is not SourceAllocationFact:
        raise ValueError('Summoned defender requires the original attack and complete revealed source')
    window.__post_init__(); source.__post_init__()
    if (window.kind != 'attack' or window.attack_target_presence is not None or
            source.kind != CardType.SPELL or source.zone != Zone.GRAVEYARD or
            source.controller == window.player_id):
        raise ValueError('Summoned defender lost its opposing original hero attack policy')


def validate_binding(state, registry, window, source, player_id, *, closed=False):
    validate_shape(window, source)
    validate_allocation(state, registry, source, closed=closed)
    if source.controller != player_id or registry.card(source.card_id).secret is None:
        raise ValueError('Summoned defender borrowed another player or non-Secret source')
    if closed:
        return  # Closed producer facts may precede a genuine Retry of the live timeline.
    validate_original_window(state,window)
    target = state.entities.get(window.target_id)
    if target is None or target.kind != CardType.HERO or target.owner != player_id:
        raise ValueError('Summoned defender lost its original protected physical hero')


def validate_request(state, registry, request, events=None):
    if request.attack_window is None:
        return
    request.__post_init__()
    validate_binding(state, registry, request.attack_window, request.cause.source, request.player_id)
    if events is not None:
        validate_acceptance_window(state,request.attack_window,request.cause.source,events)


def live_request(r, request):
    validate_request(r.state, r.registry, request, r.game._events)
    from .interrupts import find_window, attack_live
    current = find_window(r.state, request.attack_window.id)
    return current == request.attack_window and attack_live(r.state, current)


def redirect_delivery(r, root, index, entity):
    basis = root.request.pool_basis
    window = None if basis is None else getattr(basis, 'attack_window', None)
    if window is None or index != 0:
        return
    # The original main body owns the target. Quantity copies remain ordinary
    # deliveries; a later copy never substitutes for a departed main body.
    from .interrupts import find_window, attack_live, redirect, RedirectAttack
    current = find_window(r.state, window.id)
    if current != window or not attack_live(r.state, current):
        return
    redirect(r, RedirectAttack(window.id, entity.id))


def window_from_dict(value):
    if value is None:
        return None
    from .serialization import _row, _list
    from .model import BoardPresenceReference, TriggerCandidate
    row = _row(value, ActionWindow)
    for name in ('attack_source_presence', 'attack_target_presence'):
        row[name] = None if row[name] is None else BoardPresenceReference(**_row(row[name], BoardPresenceReference))
    row['spellburst_candidates'] = tuple(TriggerCandidate(**_row(x, TriggerCandidate))
        for x in _list(row['spellburst_candidates'], 'summoned defender original spellburst basis'))
    return ActionWindow(**row)


def register(mechanics):
    mechanics.register(TransformAttackedMinion,transform_attacked)
