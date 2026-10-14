"""Seat-local physical body capabilities and bounded actual paid commands.

This module never sends its private identity keys, profiles or preflight receipts
to a player. Keys are resolved from actual current owned-hand declarations.
"""
from dataclasses import asdict,replace
from itertools import product
import json
import re

from .actions import PlayCard
from .body_grants import BodyReference
from .body_targets import body_target_declarations
from .errors import IllegalAction,ResolutionLimitExceeded
from .model import CardType,Zone


def bound_profiles(game,source):
    return tuple(sorted(profile for card,profile in game.registry.body_root_target_bindings if card==source.card_id))



def complete_profiles(game, source):
    """Match every physical body before exposing capabilities or candidates."""
    from .body_target_authority import matching_body_target_authorities
    from .body_root_targets import validate_root_binding
    result=[]
    for profile in bound_profiles(game,source):
        validate_root_binding(game.registry,game.registry.body_root_target_binding(source.card_id,profile))
        authorities=matching_body_target_authorities(game._state,game.registry,BodyReference.capture(source),profile)
        if authorities is not None:result.append((profile,authorities))
    return tuple(result)


def identity(profile,reference):
    value=asdict(reference)
    value['carrier']['zone']=reference.carrier.zone.value
    return json.dumps({'profile':profile,'reference':value},sort_keys=True,separators=(',',':'),ensure_ascii=False)


def current_bodies(game,viewer):
    result={}
    for entity_id in game._state.players[viewer].hand:
        source=game._state.entities[entity_id]
        if source.controller!=viewer or source.zone!=Zone.HAND:
            raise ValueError('Private body capability requires actual owned hand')
        for profile,authorities in complete_profiles(game,source):
            for authority in authorities:
                declaration=authority.declaration
                key=identity(profile,declaration.reference)
                if key in result:raise ValueError('Duplicate current private body identity')
                result[key]=(profile,declaration)
    return result



def empty_root_identity(profile, reference):
    value=asdict(reference);value['zone']=reference.zone.value
    return json.dumps({'profile':profile,'empty_root':value},sort_keys=True,separators=(',',':'),ensure_ascii=False)


def current_empty_roots(game,viewer):
    """Private physical hand routes with a complete, genuinely empty vector."""
    result={}
    for entity_id in game._state.players[viewer].hand:
        source=game._state.entities[entity_id]
        if source.controller!=viewer or source.zone!=Zone.HAND:
            raise ValueError('Private empty route requires actual owned hand')
        reference=BodyReference.capture(source)
        for profile,authorities in complete_profiles(game,source):
            if not authorities:result[empty_root_identity(profile,reference)]=(profile,reference)
    return result


def current_capabilities(game,viewer):
    # Same monotonic private ledger; an empty root is not a fabricated body.
    bodies=current_bodies(game,viewer);roots=current_empty_roots(game,viewer)
    if set(bodies)&set(roots):raise ValueError('Private body/root identity collision')
    return {**bodies,**roots}


def sync_body_handles(game,viewer,knowledge):
    current=current_capabilities(game,viewer)
    knowledge.body_refs={key:handle for key,handle in knowledge.body_refs.items() if key in current}
    for key in current:
        if key not in knowledge.body_refs:
            knowledge.body_refs[key]=f'b{viewer}_{knowledge.next_body_ref}'
            knowledge.next_body_ref+=1


def validate_body_handles(game,viewer,knowledge):
    if type(knowledge.next_body_ref) is not int or knowledge.next_body_ref<1 or type(knowledge.body_refs) is not dict:
        raise ValueError('Invalid private body capability ledger')
    if set(knowledge.body_refs)!=set(current_capabilities(game,viewer)):
        raise ValueError('Private body capabilities differ from complete current owned hand')
    handles=[]
    for handle in knowledge.body_refs.values():
        match=re.fullmatch(f'b{viewer}_([1-9][0-9]*)',handle) if type(handle) is str else None
        if match is None or int(match[1])>=knowledge.next_body_ref:
            raise ValueError('Invalid private body capability handle')
        handles.append(handle)
    if len(handles)!=len(set(handles)):raise ValueError('Duplicate private body capability handle')


def supported(game,source,profile):
    """Check all declarations and bound roots before candidate predicates/quote."""
    from .body_target_authority import body_target_authorities
    from .choose_one import effective
    from .information import PUBLIC_ZONES
    from .player_api import UnsupportedPlayerRule,_HAND_KINDS
    from .targeting import target_spec
    authorities=body_target_authorities(game._state,game.registry,BodyReference.capture(source),profile)
    binding=game.registry.body_root_target_binding(source.card_id,profile)
    definitions=[game.registry.card(a.declaration.contract.declaration_card_id) for a in authorities]
    raw=game.registry.card(source.card_id)
    roots=[effective(raw,b.id) for b in (*raw.choose_one.branches,raw.choose_one.combined)] if raw.choose_one else [raw]
    for root in roots:
        if binding.mode=='body_only':
            root=replace(root,requires_target=False,targeting=None,target_rule='any_entity')
        elif binding.mode=='explicit_root':
            root=replace(root,requires_target=False,targeting=binding.targeting,target_rule=binding.target_rule)
        definitions.append(root)
    for definition in definitions:
        if (game.registry.target_visibility(definition.target_rule)!='builtin'
                and game.registry.player_target_rule(definition.target_rule) is None):
            raise UnsupportedPlayerRule('unsupported_rule')
        domain=target_spec(definition)
        if domain is None:continue
        from .target_predicates import player_domain_supported
        if not player_domain_supported(game.registry,definition.target_rule,domain):
            raise UnsupportedPlayerRule('unsupported_target_domain')
        if set(domain.zones)-(PUBLIC_ZONES|{Zone.HAND}) or (
            Zone.HAND in domain.zones and domain.relation!='friendly' and not _HAND_KINDS<=set(domain.kinds)):
            raise UnsupportedPlayerRule('unsupported_target_domain')
    return authorities



def supported_profiles(game,source):
    """All complete alternatives, with consumer support checked before work."""
    alternatives=complete_profiles(game,source)
    if bound_profiles(game,source) and not alternatives:
        from .player_api import UnsupportedPlayerRule
        raise UnsupportedPlayerRule('unsupported_body_target_policy')
    return tuple((profile,supported(game,source,profile)) for profile,_ in alternatives)


def plans(game,source,position=None,branch=None):
    """All trusted alternatives for one real card/placement; no Cartesian work."""
    from .body_root_targets import paid_body_root_target_plan
    from .paid_body_targets import _facts,_root,_selection
    from .targeting import target_choices
    result=[]
    for profile,authorities in supported_profiles(game,source):
        raw=PlayCard(source.controller,source.id,None,position,branch)
        probe=replace(raw,body_target_profile_id=profile,
            body_targets=tuple(_selection(a.declaration.reference,None) for a in authorities))
        values,crystals=_facts(game._state,game.registry,source)
        definition=_root(game._state,game.registry,source,probe,values,crystals)
        from .player_api import context_factory
        root_choices=target_choices(game._state,game.registry,source,definition,
            context_factory=context_factory(game,source.controller))
        if not root_choices:continue
        plan=paid_body_root_target_plan(game,replace(raw,target_id=root_choices[0]),profile)
        if not all(requirement.target_choices for requirement in plan.bodies.requirements):continue
        result.append(plan)
    return tuple(result)


def project_plans(game,viewer,source,position=None,branch=None):
    from .player_api import visible_entities
    knowledge=game._information.players[viewer]
    visible=visible_entities(game.observe(viewer))
    def ref(entity_id):
        if entity_id is None:return None
        handle=knowledge.refs.get(str(entity_id))
        if handle not in visible:raise ValueError('Body target candidate must have a current visible reference')
        return handle
    result=[]
    for plan in plans(game,source,position,branch):
        bodies=[]
        for requirement in plan.bodies.requirements:
            declaration=requirement.declaration
            bodies.append({'body':knowledge.body_refs[identity(plan.bodies.profile_id,declaration.reference)],
                'family':declaration.reference.family,'declaration_card_id':declaration.reference.declaration_card_id,
                'targets':[ref(target) for target in requirement.target_choices],
                'active':requirement.target_active})
        route={'card':ref(source.id),'position':position,'branch':branch,
            'root_targets':[ref(target) for target in plan.root.target_choices],'bodies':bodies}
        if not bodies:
            route['body_route']=knowledge.body_refs[empty_root_identity(plan.bodies.profile_id,BodyReference.capture(source))]
        result.append(route)
    return result


def decode_entries(game,viewer,source,entries,target_resolver):
    from .paid_body_targets import _selection
    if type(entries) is not list or not entries:raise ValueError('Expected a complete nonempty body target list')
    actual=current_bodies(game,viewer)
    knowledge=game._information.players[viewer]
    reverse={handle:key for key,handle in knowledge.body_refs.items()}
    profiles=[];selected=[];seen=set()
    for entry in entries:
        if type(entry) is not dict or set(entry)!={'body','target'} or type(entry['body']) is not str:
            raise ValueError('Invalid player body target fields')
        handle=entry['body']
        if handle in seen or handle not in reverse:raise ValueError('Unavailable or duplicate private body capability')
        seen.add(handle)
        if reverse[handle] not in actual:raise ValueError('Empty route cannot be used as a physical body')
        profile,declaration=actual[reverse[handle]]
        if declaration.reference.carrier!=BodyReference.capture(source):raise ValueError('Body capability belongs to another current hand card')
        profiles.append(profile)
        selected.append(_selection(declaration.reference,target_resolver(entry['target'],optional=True)))
    if len(set(profiles))!=1:raise ValueError('Body vector borrowed another target policy')
    supported(game,source,profiles[0])
    return profiles[0],tuple(selected)



def decode_empty_route(game,viewer,source,handle,entries):
    if type(entries) is not list or entries or type(handle) is not str:
        raise ValueError('Empty route requires its exact empty vector and private handle')
    actual=current_empty_roots(game,viewer);knowledge=game._information.players[viewer]
    reverse={h:k for k,h in knowledge.body_refs.items()}
    key=reverse.get(handle)
    if key not in actual:raise ValueError('Unavailable empty body route')
    profile,reference=actual[key]
    if reference!=BodyReference.capture(source):raise ValueError('Empty route belongs to another physical hand card')
    if supported(game,source,profile):raise ValueError('Empty route has acquired physical bodies')
    return profile,()


def encode_empty_route(game,viewer,action):
    source=game._state.entities[action.entity_id]
    key=empty_root_identity(action.body_target_profile_id,BodyReference.capture(source))
    if action.body_targets or key not in current_empty_roots(game,viewer):
        raise ValueError('Only a complete actual empty route can be projected')
    return game._information.players[viewer].body_refs[key]


def encode_entries(game,viewer,action):
    source=game._state.entities[action.entity_id]
    knowledge=game._information.players[viewer]
    declarations=body_target_declarations(game._state,game.registry,BodyReference.capture(source),action.body_target_profile_id)
    by_id={d.reference.ability_id:d.reference for d in declarations}
    return [{'body':knowledge.body_refs[identity(action.body_target_profile_id,by_id[v.ability_id])],
             'target':None if v.target_id is None else knowledge.refs[str(v.target_id)]} for v in action.body_targets]


def independent_play_actions(game):
    """Actual bounded host actions, shared by the player projection."""
    from .choose_one import branches
    from .paid_body_targets import _selection
    result=[]
    state=game._state
    player=state.players[state.active_player]
    for entity_id in player.hand:
        source=state.entities[entity_id]
        if not bound_profiles(game,source):continue
        definition=game.registry.card(source.card_id)
        positions=range(len(player.board)+1) if source.kind in (CardType.MINION,CardType.LOCATION) else (None,)
        for position in positions:
            for branch in branches(state,definition,player.id,entity=source):
                try:alternatives=plans(game,source,position,branch)
                except IllegalAction:continue
                for plan in alternatives:
                    count=len(plan.root.target_choices)
                    for requirement in plan.bodies.requirements:count*=len(requirement.target_choices)
                    if len(result)+count>game.ruleset.max_choice_combinations:
                        raise ResolutionLimitExceeded('Independent body target enumeration exceeds combination limit; submit the complete vector directly')
                    for targets in product(plan.root.target_choices,*(r.target_choices for r in plan.bodies.requirements)):
                        action=replace(plan.bodies.action,target_id=targets[0],body_target_profile_id=plan.bodies.profile_id,
                            body_targets=tuple(_selection(r.declaration.reference,target) for r,target in zip(plan.bodies.requirements,targets[1:])))
                        game.validate(action)
                        result.append(action)
    return tuple(result)
