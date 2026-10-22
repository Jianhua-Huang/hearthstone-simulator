"""Finite real skill families: physical producers, completion and local keywords.

An invocation is neither a spell CAST nor another minion action. All health,
randomness, summons, choices and interpreter scheduling remain shared.
"""
from copy import deepcopy
from dataclasses import dataclass, replace
import json

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .effects import Effect, ChoiceOption, RequestChoice, _integer, _player, _source
from .model import CardType, ChoiceResult, DamageKind, Event, GameState, Keyword, _name

ACCEPTED = 'family_ability_accepted'
COMPLETED = 'family_ability_completed'
SELECTED = 'family_ability_selected'


@dataclass(frozen=True)
class AbilityFamilyProfile:
    id: str
    native_card_id: str
    ability_card_ids: tuple[str, ...]
    behavior_ids: tuple[str, ...]
    trigger_card_ids: tuple[str, ...]
    keywords: tuple[tuple[Keyword, ...], ...]
    multiplier: int = 3

    def __post_init__(self):
        _name(self.id, 'ability family'); _name(self.native_card_id, 'native family source')
        for name in ('ability_card_ids', 'behavior_ids', 'trigger_card_ids'):
            rows = getattr(self, name)
            if type(rows) is not tuple or not rows or len(rows) != len(set(rows)):
                raise ValueError('Ability family requires complete unique declarations')
            for row in rows: _name(row, name)
        if (len(self.ability_card_ids) != 4 or len(self.behavior_ids) != 4 or
                self.native_card_id in self.trigger_card_ids or
                type(self.multiplier) is not int or self.multiplier != 3 or
                type(self.keywords) is not tuple or len(self.keywords) != 4):
            raise ValueError('Only the real four-skill family and its native triple policy are supported')
        for row in self.keywords:
            if type(row) is not tuple or row not in ((), (Keyword.LIFESTEAL,)):
                raise ValueError('Family skill keywords support only local Lifesteal')


def validate_profile(registry, profile):
    if type(profile) is not AbilityFamilyProfile: raise ValueError('Expected a typed skill family')
    profile.__post_init__()
    native = registry.card(profile.native_card_id)
    if (native.kind != CardType.MINION or Keyword.OLD_GOD not in native.keywords or
            tuple(a.card_id for a in native.activated_abilities) != profile.ability_card_ids):
        raise ValueError('Skill family requires its original four Old God activations')
    for cid, body, keywords in zip(profile.ability_card_ids, profile.behavior_ids, profile.keywords):
        card = registry.card(cid); registry.behavior(body)
        if (card.kind != CardType.SPELL or card.hand_playable or not card.choice_only or
                card.keywords):
            raise ValueError('Skill descriptors are finite non-playable choices, not additional CASTs')
    for cid in profile.trigger_card_ids:
        if registry.card(cid).kind not in (CardType.MINION, CardType.SPELL, CardType.WEAPON):
            raise ValueError('Unsupported physical family producer')


@dataclass(frozen=True)
class AbilityTriggerRequest:
    family_id: str
    player_id: int
    source: SourceAllocationFact
    ability_card_id: str
    native: bool = False
    target_id: int | None = None
    native_event: Event | None = None
    selection: ChoiceResult | None = None
    target_selection: ChoiceResult | None = None
    battlecry_id: int | None = None

    def __post_init__(self):
        _name(self.family_id, 'skill family'); _name(self.ability_card_id, 'skill descriptor')
        _player(self.player_id); _source(self.target_id); _source(self.battlecry_id)
        if self.native and self.battlecry_id is not None:raise ValueError('Native skill cannot borrow a Battlecry')
        if type(self.source) is not SourceAllocationFact: raise ValueError('Skill lost its actual physical source')
        self.source.__post_init__()
        if type(self.native) is not bool: raise ValueError('Native skill policy must be boolean')
        if self.native:
            e = self.native_event
            if (type(e) is not Event or e.kind != 'minion_ability_started' or self.selection is not None or
                    (e.source_id, e.player_id) != (self.source.entity_id, self.player_id) or
                    dict(e.data).get('ability_card_id') != self.ability_card_id):
                raise ValueError('Native skill requires its real original activation event')
        elif self.native_event is not None:
            raise ValueError('External skill cannot borrow a native activation')
        if self.selection is not None:
            if type(self.selection) is not ChoiceResult: raise ValueError('Skill choice lost its original result')
            self.selection.__post_init__()
            if ((self.selection.choice.player_id, self.selection.choice.source_id) !=
                    (self.player_id, self.source.entity_id) or
                    self.selection.selected_ids != (self.ability_card_id,)):
                raise ValueError('Skill choice changed the selected family member or actor')
        if self.target_selection is not None:
            value=self.target_selection
            if (self.native or self.selection is None or type(value)is not ChoiceResult or
                    value.selected_ids!=(str(self.target_id),) or
                    (value.choice.source_id,value.choice.player_id)!=(self.source.entity_id,self.player_id)):
                raise ValueError('Skill target lost its original separate committed selection')
            value.__post_init__()


@dataclass(frozen=True)
class AbilityTriggerRecord:
    id: int
    request: AbilityTriggerRequest
    turn: int
    action: int
    prior_completed: tuple[str, ...]
    multiplier: int
    source_keywords: tuple[Keyword, ...]
    completed: bool = False

    def __post_init__(self):
        _integer(self.id, 'skill invocation', 1); _integer(self.turn, 'skill turn', 1)
        _integer(self.action, 'skill action', 0)
        if type(self.request) is not AbilityTriggerRequest: raise ValueError('Skill history lost its complete request')
        self.request.__post_init__()
        if (type(self.prior_completed) is not tuple or len(set(self.prior_completed)) != len(self.prior_completed) or
                any(type(x) is not str for x in self.prior_completed) or type(self.multiplier) is not int or
                self.multiplier not in (1, 3) or type(self.completed) is not bool or
                type(self.source_keywords) is not tuple or
                any(type(k) is not Keyword for k in self.source_keywords) or
                self.source_keywords != tuple(sorted(set(self.source_keywords), key=lambda k: k.value))):
            raise ValueError('Invalid original skill completion or local source material')


@dataclass(frozen=True)
class AbilityAcceptanceProof:
    state: GameState
    record: AbilityTriggerRecord


@dataclass(frozen=True)
class TriggerFamilyAbility(Effect):
    request: AbilityTriggerRequest


@dataclass(frozen=True)
class FinishFamilyAbility(Effect):
    proof: AbilityAcceptanceProof


@dataclass(frozen=True)
class ChooseFamilyAbilities(Effect):
    request: AbilityTriggerRequest
    count: int = 1
    selected: tuple[str, ...] = ()

    def __post_init__(self):
        self.request.__post_init__()
        if (self.request.native or self.request.target_id is not None or self.request.selection is not None or
                type(self.count) is not int or self.count not in (1, 2) or
                type(self.selected) is not tuple or len(set(self.selected)) != len(self.selected) or
                len(self.selected) > self.count):
            raise ValueError('Family choices support one or two distinct actual skills')


@dataclass(frozen=True)
class SelectFamilyAbility(Effect):
    offer: ChooseFamilyAbilities
    ability_card_id: str
    result: ChoiceResult | None = None


@dataclass(frozen=True)
class SelectFamilyTarget(Effect):
    request: AbilityTriggerRequest
    target_id: int
    result: ChoiceResult | None = None


def assembled_trigger_source(registry, profile, card_id, *, battlecry_behavior=None):
    """Recognize an immutable face carrying an approved original family body.

    Physical source and activation IDs remain the actual ones. The original
    donor authorizes the body; a prefix, a name or an unregistered recipe does
    not authorize a family skill.
    """
    from .assemble_faces import PREFIX,recipe_from_id,text_source
    if not card_id.startswith(PREFIX):return False
    try:
        recipe=recipe_from_id(card_id)
        donor_id=recipe.secondary_card_id if recipe.half=='bottom' else recipe.primary_card_id
        if donor_id not in profile.trigger_card_ids:return False
        donor=registry.card(donor_id);template=text_source(registry,donor_id)
        if donor.battlecry is None or template.suffix.behavior_id!=donor.battlecry:return False
        face=registry.card(card_id)
        return (face.kind==CardType.MINION and
            (battlecry_behavior is None or face.battlecry==battlecry_behavior))
    except (KeyError,TypeError,ValueError):return False


def profile_for(registry, request):
    request.__post_init__()
    try: profile = registry.ability_family_profiles[request.family_id]
    except KeyError: raise ValueError('Unknown skill family') from None
    if request.ability_card_id not in profile.ability_card_ids:
        raise ValueError('Skill is not a declared family member')
    allowed = (profile.native_card_id,) if request.native else profile.trigger_card_ids
    if request.source.card_id not in allowed and not (not request.native and request.source.kind==CardType.MINION and
            (request.battlecry_id is not None or assembled_trigger_source(registry,profile,request.source.card_id))):
        raise ValueError('Skill was attributed to an undeclared physical producer')
    return profile


def completed_ids(state, profile, player_id, *, before=None):
    rows = state.ability_trigger_history if before is None else state.ability_trigger_history[:before]
    used = {r.request.ability_card_id for r in rows if r.completed and
            (r.request.family_id, r.request.player_id) == (profile.id, player_id)}
    return tuple(cid for cid in profile.ability_card_ids if cid in used)


def make_record(state, registry, request):
    profile = profile_for(registry, request)
    validate_allocation(state, registry, request.source)
    if request.battlecry_id is not None:
        from .battlecries import battlecry_record
        original=battlecry_record(state,request.battlecry_id)
        if ((original.source_id,original.player_id)!=(request.source.entity_id,request.player_id) or
                (original.payload.card_id not in profile.trigger_card_ids and not assembled_trigger_source(
                    registry,profile,original.payload.card_id,battlecry_behavior=original.payload.behavior_id)) or not original.payload_started or
                original.failure is not None or original.completed or original.interrupted):
            raise ValueError('Family skill lost its actual original or borrowed Battlecry')
    source = state.entities[request.source.entity_id]
    prior = completed_ids(state, profile, request.player_id)
    index = profile.ability_card_ids.index(request.ability_card_id)
    keywords = tuple(sorted(set(source.keywords) | set(profile.keywords[index]), key=lambda k: k.value))
    return AbilityTriggerRecord(len(state.ability_trigger_history)+1, request, state.turn,
        state.action_number, prior, profile.multiplier if request.native and len(prior) == 4 else 1, keywords)


def encode(game, value):
    from .continuations import FrameCodec
    return json.dumps(FrameCodec(game.mechanics, game.registry).encode(value), ensure_ascii=False,
                      sort_keys=True, separators=(',', ':'))


def decode(game, value):
    from .continuations import FrameCodec
    if type(value) is not str: raise ValueError('Skill witness requires its complete encoded payload')
    return FrameCodec(game.mechanics, game.registry).decode(json.loads(value))


def trigger(r, effect):
    original = deepcopy(r.state)
    record = make_record(original, r.registry, effect.request)
    proof = AbilityAcceptanceProof(original, record)
    r.state.ability_trigger_history.append(record)
    event = r.emit(ACCEPTED, source_id=record.request.source.entity_id, player_id=record.request.player_id,
        target_id=record.request.target_id, trigger_id=record.id, proof=encode(r.game, proof), _capture=False)
    profile = profile_for(r.registry, record.request)
    body = profile.behavior_ids[profile.ability_card_ids.index(record.request.ability_card_id)]
    return (r.call(body, record.request.source.entity_id, record.request.player_id,
                   record.request.target_id, event=event), FinishFamilyAbility(proof))


def finish(r, effect):
    proof = effect.proof; validate_proof(r.registry, proof)
    record = proof.record
    if r.state.ability_trigger_history[record.id-1] != record:
        raise ValueError('Skill completion lost or reused its original invocation')
    r.state.ability_trigger_history[record.id-1] = replace(record, completed=True)
    r.emit(COMPLETED, source_id=record.request.source.entity_id, player_id=record.request.player_id,
        target_id=record.request.target_id, trigger_id=record.id, _capture=False)


def context_record(context):
    if context.event is None or context.event.kind != ACCEPTED:
        raise ValueError('Skill body requires its actual accepted invocation')
    identity = dict(context.event.data)['trigger_id']
    _integer(identity, 'skill context identity', 1)
    record = context.state.ability_trigger_history[identity-1]
    if (record.completed or (record.request.source.entity_id, record.request.player_id, record.request.target_id) !=
            (context.source_id, context.player_id, context.target_id)):
        raise ValueError('Skill body borrowed another invocation')
    return record


def health_source(state, registry, trigger_id, source_id, kind):
    _integer(trigger_id, 'skill health identity', 1)
    if trigger_id > len(state.ability_trigger_history): raise ValueError('Unknown skill health invocation')
    record = state.ability_trigger_history[trigger_id-1]; request = record.request
    profile=profile_for(registry, request); validate_allocation(state, registry, request.source)
    expected = DamageKind.MINION_ABILITY if request.source.kind == CardType.MINION else DamageKind.EFFECT
    if record.completed or request.source.entity_id != source_id or kind != expected:
        raise ValueError('Skill health changed its original physical attribution or kind')
    # Ordinary physical keywords still follow the existing per-health-batch
    # window. Only the descriptor's intrinsic keyword is local to this skill.
    keywords=frozenset(state.entities[source_id].keywords)|frozenset(
        profile.keywords[profile.ability_card_ids.index(request.ability_card_id)])
    return request.source, request.player_id, keywords


def request_from_context(context, family_id, ability_card_id, *, native=False):
    return AbilityTriggerRequest(family_id, context.player_id,
        SourceAllocationFact.capture(context.state, context.source), ability_card_id,
        native=native, target_id=context.target_id if native else None,
        native_event=context.event if native else None,
        battlecry_id=context.battlecry.id if context.battlecry is not None else None)


def ability_targets(r, request):
    from .targeting import legal_target_ids
    profile = profile_for(r.registry, request)
    native = r.registry.card(profile.native_card_id)
    spec = next(a for a in native.activated_abilities if a.card_id == request.ability_card_id)
    if spec.targeting is None: return None
    # A skill target domain is a minion ability even when a spell/weapon caused
    # it. This is a pure query using the real source ID, never a fake entity.
    definition = replace(native, requires_target=False, targeting=spec.targeting, target_rule=spec.target_rule)
    source = replace(r.state.entities[request.source.entity_id], controller=request.player_id)
    return legal_target_ids(r.state, r.registry, source, definition)


def choose(r, effect):
    effect.__post_init__(); profile = profile_for(r.registry, effect.request)
    if any(cid not in profile.ability_card_ids for cid in effect.selected):
        raise ValueError('Family continuation contains another family member')
    if len(effect.selected) == effect.count: return ()
    options = tuple(ChoiceOption(cid, r.registry.card(cid).name,
        (SelectFamilyAbility(effect, cid),), card_id=cid)
        for cid in profile.ability_card_ids if cid not in effect.selected)
    return (RequestChoice(effect.request.player_id, options, effect.request.source.entity_id,
                          prompt='Choose an ability'),)


def select(r, effect):
    effect.offer.__post_init__()
    if type(effect.result) is not ChoiceResult: raise ValueError('Family selection lacks its committed result')
    request = replace(effect.offer.request, ability_card_id=effect.ability_card_id, selection=effect.result)
    request.__post_init__()
    if effect.ability_card_id in effect.offer.selected: raise ValueError('Family choice repeated an earlier skill')
    following = replace(effect.offer, selected=(*effect.offer.selected, effect.ability_card_id))
    targets = ability_targets(r, request)
    if targets:
        options = tuple(ChoiceOption(str(t), r.registry.card(r.state.entities[t].card_id).name,
            (SelectFamilyTarget(request, t),), entity_id=t) for t in targets)
        first = RequestChoice(request.player_id, options, request.source.entity_id, prompt='Choose a minion')
    else:
        first = TriggerFamilyAbility(request)
    return first, following


def select_target(r, effect):
    if (type(effect.result) is not ChoiceResult or effect.result.selected_ids != (str(effect.target_id),) or
            (effect.result.choice.source_id, effect.result.choice.player_id) !=
            (effect.request.source.entity_id, effect.request.player_id)):
        raise ValueError('Skill target lost its original actor or committed selection')
    return (TriggerFamilyAbility(replace(effect.request, target_id=effect.target_id, target_selection=effect.result)),)


def selected(r, result, options):
    chosen=[o for o in options if o.id in result.selected_ids]
    if len(chosen)!=1 or len(chosen[0].effects)!=1:return
    work=chosen[0].effects[0]
    if type(work) not in (SelectFamilyAbility,SelectFamilyTarget):return
    work=replace(work,result=result)
    r.emit(SELECTED,source_id=result.choice.source_id,player_id=result.choice.player_id,
        choice_id=result.choice.id,work=encode(r.game,work),_capture=False)


def validate_proof(registry, proof):
    if type(proof) is not AbilityAcceptanceProof or type(proof.state) is not GameState:
        raise ValueError('Skill lost its original acceptance window')
    if type(proof.record) is not AbilityTriggerRecord or make_record(proof.state, registry, proof.record.request) != proof.record:
        raise ValueError('Skill changed its original completed set, multiplier or physical source')


def validate_state(state, registry):
    if type(state.ability_trigger_history) is not list: raise ValueError('Invalid skill history')
    for index, row in enumerate(state.ability_trigger_history, 1):
        if type(row) is not AbilityTriggerRecord: raise ValueError('Skill history requires typed original rows')
        row.__post_init__(); profile = profile_for(registry, row.request)
        validate_allocation(state, registry, row.request.source)
        if (row.id != index or row.turn > state.turn or row.action > state.action_number or
                any(cid not in profile.ability_card_ids for cid in row.prior_completed) or
                row.multiplier != (3 if row.request.native and len(row.prior_completed) == 4 else 1)):
            raise ValueError('Skill history changed its original chronology or native reward')

    for health in (*state.damage_history,*state.healing_history):
        result=health.health_result;identity=result.ability_trigger_id
        if identity is None:continue
        if identity>len(state.ability_trigger_history):raise ValueError("Health result lost its actual skill")
        row=state.ability_trigger_history[identity-1];source=row.request.source
        if (result.source_id,result.source_card_id,result.source_controller,result.source_zone_epoch,result.source_entered_order)!=(
                source.entity_id,source.card_id,row.request.player_id,source.zone_epoch,source.entered_order):
            raise ValueError("Health result changed its original skill source")


def validate_boundary(game):
    from .hero_health_history import effective_events
    from .resolver import BehaviorCall
    profiles=game.registry.ability_family_profiles
    rows=game._state.ability_trigger_history
    if not profiles and not rows:return
    events=effective_events(game._events)
    skill_ids={cid for profile in profiles.values() for cid in profile.ability_card_ids}
    relevant=[e for e in events if e.kind in (ACCEPTED,COMPLETED,SELECTED)]
    native_events=[e for e in events if e.kind in ('minion_ability_started','minion_ability_used') and
                   dict(e.data).get('ability_card_id') in skill_ids]
    public_choices=[e for e in events if len(tuple(dict(e.data).get('option_ids',())))==1 and
                    tuple(dict(e.data)['option_ids'])[0] in skill_ids]
    if not rows and not relevant and not native_events and not public_choices:return
    accepted={};completed=set();selections={};used_selections=set();native_rows={}
    by_sequence={e.sequence:e for e in events}
    for event in relevant:
        data=dict(event.data)
        if event.kind==SELECTED:
            if set(data)!={'choice_id','work'}:raise ValueError('Family selection lost its complete original work')
            identity=data['choice_id'];_integer(identity,'family selection',1)
            work=decode(game,data['work'])
            if type(work) not in (SelectFamilyAbility,SelectFamilyTarget) or type(work.result)is not ChoiceResult:
                raise ValueError('Family selection requires its actual typed result')
            result=work.result;result.__post_init__()
            if identity in selections or result.choice.id!=identity:
                raise ValueError('Family selection reused another committed result')
            if type(work)is SelectFamilyAbility:
                work.offer.__post_init__();request=replace(work.offer.request,
                    ability_card_id=work.ability_card_id,selection=result)
                profile=profile_for(game.registry,request)
                expected=tuple(cid for cid in profile.ability_card_ids if cid not in work.offer.selected)
                if (tuple(o.id for o in result.choice.options)!=expected or
                        tuple(o.card_id for o in result.choice.options)!=expected or
                        work.ability_card_id in work.offer.selected):
                    raise ValueError('Family choice changed its original distinct skill domain')
            else:
                request=replace(work.request,target_id=work.target_id,target_selection=result)
                profile_for(game.registry,request)
                if any(o.entity_id is None or o.id!=str(o.entity_id) for o in result.choice.options):
                    raise ValueError('Skill target lost its original physical options')
            if (result.choice.min_count,result.choice.max_count)!=(1,1) or event.target_id is not None or event.amount!=0 or (
                    event.source_id,event.player_id)!=(request.source.entity_id,request.player_id):
                raise ValueError('Family selection changed its original actor or cardinality')
            selections[identity]=work
            continue
        identity=data.get('trigger_id');_integer(identity,'original skill witness',1)
        if event.kind==ACCEPTED:
            if set(data)!={'trigger_id','proof'} or identity!=len(accepted)+1:
                raise ValueError('Skill acceptance was duplicated or truncated')
            proof=decode(game,data['proof']);validate_proof(game.registry,proof);row=proof.record
            if row.id!=identity or tuple(proof.state.ability_trigger_history)!=tuple(
                    replace(accepted[i].record,completed=i in completed) for i in range(1,identity)):
                raise ValueError('Skill acceptance lost its complete original history prefix')
            request=row.request
            if request.native:
                cause=request.native_event
                if by_sequence.get(cause.sequence)!=cause or cause.sequence>=event.sequence or cause.sequence in native_rows:
                    raise ValueError('Native skill borrowed or lost its actual activation')
                native_rows[cause.sequence]=row
            else:
                result=request.selection
                work=selections.get(result.choice.id) if result is not None else None
                if (type(work)is not SelectFamilyAbility or result!=work.result or
                        replace(work.offer.request,ability_card_id=work.ability_card_id,selection=result)!=
                        replace(request,target_id=None,target_selection=None)):
                    raise ValueError('Family skill lost its original committed skill selection')
                if result.choice.id in used_selections:raise ValueError('Family skill reused its original selection')
                used_selections.add(result.choice.id)
                if request.target_selection is not None:
                    result=request.target_selection;work=selections.get(result.choice.id)
                    if (type(work)is not SelectFamilyTarget or result!=work.result or
                            replace(work.request,target_id=work.target_id,target_selection=result)!=request or
                            result.choice.id in used_selections):
                        raise ValueError('Family skill changed its separately committed target')
                    used_selections.add(result.choice.id)
            accepted[identity]=proof
        else:
            if set(data)!={'trigger_id'} or identity not in accepted or identity in completed:
                raise ValueError('Skill completion lost or reused its unique acceptance')
            row=accepted[identity].record;completed.add(identity)
        request=row.request
        if (event.source_id,event.player_id,event.target_id,event.amount)!=(
                request.source.entity_id,request.player_id,request.target_id,0):
            raise ValueError('Skill witness changed its original actor or target')
    expected=[replace(accepted[i].record,completed=i in completed)for i in range(1,len(accepted)+1)]
    if rows!=expected:raise ValueError('Skill history lost or added an original invocation')
    queued=() if game._frame is None else (*game._frame.prefix,*game._frame.continuation)
    found=[];pending_selections=set();pending_native=set()
    def pending(work):
        if type(work)is FinishFamilyAbility:
            validate_proof(game.registry,work.proof);found.append(work.proof.record.id)
        elif type(work)is BehaviorCall:
            event=work.context.event
            if event is not None and event.kind=='minion_ability_started':pending_native.add(event.sequence)
        elif type(work)is SelectFamilyAbility and work.result is not None:
            pending_selections.add(work.result.choice.id)
        elif type(work)in(TriggerFamilyAbility,SelectFamilyTarget):
            request=work.request
            for result in (request.selection,request.target_selection,getattr(work,'result',None)):
                if result is not None:pending_selections.add(result.choice.id)
        elif type(work)is RequestChoice:
            for option in work.options:
                for child in option.effects:pending(child)
    for work in queued:pending(work)
    if game._frame is not None:
        for option in game._frame.options:
            for work in option.effects:
                if type(work)in(SelectFamilyAbility,SelectFamilyTarget):pending(work)
    if game._state.status=='playing':
        if sorted(found)!=sorted(row.id for row in rows if not row.completed):
            raise ValueError('Suspended skill lost or duplicated its owed completion')
        if set(selections)-used_selections!=pending_selections-used_selections:
            raise ValueError('Family skill lost its original selected continuation')
    for event in public_choices:
        work=selections.get(dict(event.data).get('choice_id'))
        # A public selection reaction can suspend before its selected work starts.
        if work is None or (work.result.selected_ids!=tuple(dict(event.data)['option_ids']) or
                (work.result.choice.source_id,work.result.choice.player_id)!=(event.source_id,event.player_id)):
            raise ValueError('Family skill lost all private witnesses for a real public selection')
    starts={e.sequence:e for e in native_events if e.kind=='minion_ability_started'};used=set()
    for event in native_events:
        if event.kind=='minion_ability_started':
            if game._state.status=='playing' and event.sequence not in native_rows and event.sequence not in pending_native:
                raise ValueError('Native activation lost its actual skill invocation')
            continue
        candidates=[e for seq,e in starts.items() if seq<event.sequence and seq not in used and
            (e.source_id,e.player_id,e.target_id,dict(e.data).get('ability_card_id'))==
            (event.source_id,event.player_id,event.target_id,dict(event.data).get('ability_card_id'))]
        if not candidates:raise ValueError('Native completion lost its original activation')
        cause=max(candidates,key=lambda e:e.sequence);used.add(cause.sequence)
        row=native_rows.get(cause.sequence)
        if row is None or row.id not in completed:
            raise ValueError('Native completion lost its actual completed family invocation')


def rows_from_dict(value):
    from .serialization import _list, _row, event_from_dict, choice_from_dict
    def choice_result_from_dict(raw):
        row=_row(raw,ChoiceResult);row["choice"]=choice_from_dict(row["choice"]);row["selected_ids"]=tuple(row["selected_ids"])
        return ChoiceResult(**row)
    rows = []
    for item in _list(value['ability_trigger_history'], 'skill family history'):
        row = _row(item, AbilityTriggerRecord); request = _row(row['request'], AbilityTriggerRequest)
        request['source'] = allocation_from_dict(request['source'])
        request['native_event'] = event_from_dict(request['native_event']) if request['native_event'] is not None else None
        request['selection'] = choice_result_from_dict(request['selection']) if request['selection'] is not None else None
        request['target_selection'] = choice_result_from_dict(request['target_selection']) if request['target_selection'] is not None else None
        row['request'] = AbilityTriggerRequest(**request)
        row['prior_completed'] = tuple(row['prior_completed'])
        row['source_keywords'] = tuple(Keyword(k) for k in row['source_keywords'])
        rows.append(AbilityTriggerRecord(**row))
    value['ability_trigger_history'] = rows


def register(mechanics):
    for kind in (AbilityTriggerRequest, AbilityTriggerRecord, AbilityAcceptanceProof):
        mechanics.register_payload_type(kind)
    for kind, handler in ((TriggerFamilyAbility, trigger), (FinishFamilyAbility, finish),
            (ChooseFamilyAbilities, choose), (SelectFamilyAbility, select), (SelectFamilyTarget, select_target)):
        mechanics.register(kind, handler)
