"""Fixed-pool assembly sampling and typed, recoverable half selection.

Experimental empty/small/keep policies are explicit. This is not a declaration
of the complete official pool, exact fragment inventory or CN calibration.
"""
from copy import deepcopy
from dataclasses import dataclass,replace
from random import Random

from .assemble_faces import AssembleRecipe,validate_template
from .effects import Effect,AddToHand,ChoiceOption,RequestChoice,_player,_source
from .card_creation import CreatedMinionGrant,validate_minion_grant
from .errors import ResolutionError
from .model import CardClass,CardType,ChoicePurpose,ChoiceResult,CostSpec,GameState,Keyword,_name,validate_end_turn_rng,validate_invariants
from .pool_offers import preview
from .pools import PoolQuery,resolve_candidates,sample_candidates

@dataclass(frozen=True)
class Assemble(Effect):
    player_id: int
    pool_id: str
    source_id: int|None=None
    primary_query: PoolQuery=PoolQuery()
    primary_trait: str='any'
    empty_policy: str='error'
    small_policy: str='error'
    keep_policy: str='forbid'
    prompt: str='选择要替换的半段文本'
    cost: CostSpec|None=None
    minion_grant: CreatedMinionGrant|None=None
    secondary_min_cost: int|None=None
    passive_power_template_id: str|None=None

    def __post_init__(self):
        _player(self.player_id);_source(self.source_id);_name(self.pool_id,'assembly pool');_name(self.prompt,'assembly prompt')
        if type(self.primary_query)is not PoolQuery:raise ValueError('Assembly requires explicit PoolQuery')
        self.primary_query.__post_init__()
        if self.primary_query.kinds not in((),(CardType.MINION,)) or self.primary_query.class_mode not in('any','current','specified','other'):
            raise ValueError('Assembly primary query requires the ordinary or explicitly specified class minion domain')
        if self.primary_query.class_mode in('specified','other') and self.source_id is None:
            raise ValueError('Specified-class assembly requires its original source')
        if self.primary_query.class_mode=='other'and self.primary_query.include_neutral:
            raise ValueError('Other-class primary assembly excludes Neutral explicitly')
        if self.secondary_min_cost is not None and (type(self.secondary_min_cost)is not int or
                self.secondary_min_cost<0 or self.source_id is None):
            raise ValueError('Assembly absolute secondary cost floor requires a nonnegative integer and original source')
        if self.primary_trait not in('any','battlecry','deathrattle','end_turn','taunt'):raise ValueError('Unsupported assembly primary trait')
        if self.empty_policy not in('error','skip')or self.small_policy not in('error','available')or self.keep_policy not in('forbid','offer'):
            raise ValueError('Unsupported explicit assembly offer policy')
        if self.cost is not None:
            if type(self.cost)is not CostSpec:raise ValueError('Assembly cost requires a typed ordinary reduction')
            self.cost.__post_init__()
            if self.cost.delta>=0 or self.cost!=CostSpec(delta=self.cost.delta):
                raise ValueError('Assembly only supports a plain creation-time cost reduction')
        validate_minion_grant(self.minion_grant)
        if self.minion_grant is not None:
            grant=self.minion_grant
            periodic=grant==CreatedMinionGrant(special='hand_turn_end_discount')
            if not periodic and (grant.attack<0 or grant.health<0 or grant.keywords or grant.reborn_policy is not None or
                    grant.identity is not None or grant.special is not None):
                raise ValueError('Assembly supports a plain stat bonus or an independent owner-end hand discount')
        if self.cost is not None or self.minion_grant is not None:
            if self.source_id is None or self.cost is not None and self.minion_grant is not None:
                raise ValueError('Assembly delivery requires one independent original source-bound grant')
        if self.passive_power_template_id is not None:
            _name(self.passive_power_template_id, 'assembly passive power template')
            if (self.source_id is None or self.primary_query != PoolQuery() or self.primary_trait != 'any' or
                    self.cost is not None or self.minion_grant is not None or self.secondary_min_cost is not None):
                raise ValueError('Passive assembly requires its independent original curated domain and no hand grant')

@dataclass(frozen=True)
class AssembleOffer:
    spec: Assemble
    before: GameState
    primary_candidates: tuple[str,...]
    primary_card_id: str
    secondary_candidates: tuple[str,...]
    secondary_card_ids: tuple[str,...]
    rng_before: tuple
    rng_after: tuple

    def __post_init__(self):
        if type(self.spec)is not Assemble or type(self.before)is not GameState:raise ValueError('Typed assembly acceptance required')
        self.spec.__post_init__();_name(self.primary_card_id,'assembly primary')
        for name in('primary_candidates','secondary_candidates','secondary_card_ids'):
            values=getattr(self,name)
            if type(values)is not tuple or any(type(x)is not str or not x for x in values)or len(values)!=len(set(values)):
                raise ValueError('Assembly inventories require ordered unique card IDs')
        if self.primary_card_id not in self.primary_candidates or len(self.secondary_card_ids)>2:
            raise ValueError('Assembly selection lost its original inventory')
        validate_end_turn_rng(self.rng_before);validate_end_turn_rng(self.rng_after)

@dataclass(frozen=True)
class ResolveAssemble(Effect):
    offer: AssembleOffer
    option_id: str
    result: ChoiceResult|None=None

    def __post_init__(self):
        if type(self.offer)is not AssembleOffer:raise ValueError('Assembly branch requires its original offer')
        self.offer.__post_init__();_name(self.option_id,'assembly selected option')
        if self.result is not None:
            if type(self.result)is not ChoiceResult:raise ValueError('Assembly branch requires real ChoiceResult')
            self.result.__post_init__()

def source_card(state,spec):
    if spec.source_id is None:return None
    if spec.source_id not in state.entities:raise ValueError('Missing assembly source')
    return state.entities[spec.source_id].card_id

def candidates(registry,context,state,spec,primary=None):
    spec.__post_init__();source=source_card(state,spec);hero=state.players[spec.player_id].hero_class
    passive=spec.passive_power_template_id is not None
    if passive:
        from .assembled_powers import request_profile
        passive_profile=request_profile(registry,state,spec)
    if type(hero)is not CardClass or hero==CardClass.NEUTRAL:raise ValueError('Assembly requires a known current hero class')
    if primary is None:
        mode=spec.primary_query.class_mode
        query=replace(spec.primary_query,kinds=(CardType.MINION,),
            class_mode='any'if passive else mode if mode in('specified','other')else'current')
    else:
        cost=registry.card(primary).cost
        query=(PoolQuery(kinds=(CardType.MINION,),class_mode='current',min_cost=spec.secondary_min_cost)
            if spec.secondary_min_cost is not None else
            PoolQuery(kinds=(CardType.MINION,),class_mode='current',min_cost=8 if cost in(9,10)else cost,max_cost=cost+2))
        if passive:query=replace(query,class_mode='any')
    rows=resolve_candidates(registry,context,spec.pool_id,query,current_class=hero,source_card_id=source,player_id=spec.player_id)
    result=[]
    for row in rows:
        card=registry.card(row.card_id)
        if card.kind!=CardType.MINION or card.choice_only or not card.hand_playable:raise ValueError('Assembly pool contains a nonphysical minion')
        # Candidate availability is checked before a trait or pairing policy can
        # omit it. Missing adapters/templates never masquerade as ineligibility.
        template=registry.assemble_templates.get(row.card_id)
        if template is None:raise ValueError('Eligible assembly minion lacks reviewed text halves: '+row.card_id)
        validate_template(registry,template)
        if passive:
            from .assembled_powers import passive_minion
            if row.card_id not in passive_profile.reviewed_fragment_ids:
                raise ValueError('Eligible passive assembly minion lacks reviewed power-context compatibility: '+row.card_id)
            passive_minion(card)
        if primary is None:
            if spec.primary_trait!='any':
                match=(Keyword.TAUNT in card.keywords)if spec.primary_trait=='taunt'else template.prefix.timing==spec.primary_trait
                if not match:continue
        else:
            if not recipe_options(registry,primary,row.card_id,spec.passive_power_template_id):continue
        result.append(row)
    return tuple(result)

def recipe_options(registry,primary,secondary,passive_power_template_id=None):
    first=registry.assemble_templates[primary];second=registry.assemble_templates[secondary]
    options=[]
    for half in('top','bottom'):
        prefix=second.prefix if half=='top'else first.prefix
        suffix=second.suffix if half=='bottom'else first.suffix
        if prefix.timing not in suffix.allowed_timings:continue
        cid=AssembleRecipe(primary,secondary,half).card_id;card=registry.card(cid)
        if replace(card,id=primary)==registry.card(primary):continue
        if passive_power_template_id is not None:
            from .assembled_powers import power_id
            cid=power_id(registry,passive_power_template_id,cid)
        options.append((half,cid))
    return tuple(options)

def draw(registry,context,state,spec,rng):
    primary_rows=candidates(registry,context,state,spec)
    if not primary_rows:
        if spec.empty_policy=='skip':return None
        raise ValueError('Assembly primary pool is empty under the declared policy')
    chosen=sample_candidates(rng,primary_rows,1,replacement=False)[0]
    secondary_rows=candidates(registry,context,state,spec,chosen)
    if len(secondary_rows)<2 and spec.small_policy=='error':raise ValueError('Assembly needs two distinct reviewed secondary candidates')
    selected=sample_candidates(rng,secondary_rows,2,replacement=False)
    if not selected and spec.keep_policy!='offer':raise ValueError('Assembly has no legal half replacements')
    return(tuple(m.card_id for m in primary_rows),chosen,tuple(m.card_id for m in secondary_rows),selected)

def validate_offer(registry,context,offer):
    offer.__post_init__();validate_invariants(offer.before,registry)
    rng=Random();rng.setstate(offer.rng_before)
    expected=draw(registry,context,offer.before,offer.spec,rng)
    if expected!=(offer.primary_candidates,offer.primary_card_id,offer.secondary_candidates,offer.secondary_card_ids)or rng.getstate()!=offer.rng_after:
        raise ValueError('Assembly offer changed original candidates, selection or RNG')

def option_rows(registry,offer):
    rows=[]
    for index,cid in enumerate(offer.secondary_card_ids,1):
        for half,result_id in recipe_options(registry,offer.primary_card_id,cid,offer.spec.passive_power_template_id):
            label=registry.card(cid).name+'：'+('替换上半段'if half=='top'else'替换下半段')
            rows.append((str(index)+'-'+half,label,result_id))
    if offer.spec.keep_policy=='offer':rows.append(('keep','保留原文本',offer.primary_card_id))
    return tuple(rows)

def options_for(registry,offer):
    return tuple(ChoiceOption(oid,label,(ResolveAssemble(offer,oid),),card_id=cid,
        preview=preview(registry.card(cid),registry.card(cid).cost))for oid,label,cid in option_rows(registry,offer))

def assemble(r,spec):
    spec.__post_init__();before=deepcopy(r.state);rng_before=r.game._rng.getstate()
    data=draw(r.registry,r.game._generation_context,before,spec,r.game._rng)
    if data is None:return ()
    offer=AssembleOffer(spec,before,*data,rng_before,r.game._rng.getstate());validate_offer(r.registry,r.game._generation_context,offer)
    return(RequestChoice(spec.player_id,options_for(r.registry,offer),spec.source_id,spec.prompt,purpose=ChoicePurpose.ASSEMBLE),)

def validate_current(offer,state):
    before=offer.before
    for field in('turn','action_number','next_entity_id','next_order','next_attachment_id','next_choice_id'):
        if getattr(before,field)>getattr(state,field):raise ValueError('Assembly acceptance belongs to a future state')
    if offer.spec.source_id is not None and offer.spec.source_id not in state.entities:
        raise ValueError('Assembly lost its original physical source')
    for pid in(1,2):
        if before.players[pid].original_deck!=state.players[pid].original_deck:
            raise ValueError('Assembly acceptance changed original deck facts')

def resolve(r,effect):
    effect.__post_init__();validate_offer(r.registry,r.game._generation_context,effect.offer)
    validate_current(effect.offer,r.state)
    if effect.result is None:raise ValueError('Assembly delivery requires the actual selected choice')
    spec=effect.offer.spec;choice=effect.result.choice
    if ((choice.player_id,choice.source_id,choice.prompt,choice.min_count,choice.max_count,choice.purpose,choice.repeat_key)!=
            (spec.player_id,spec.source_id,spec.prompt,1,1,ChoicePurpose.ASSEMBLE,None)):
        raise ValueError('Assembly result changed its actor or choice contract')
    if choice.options!=tuple(o.item for o in options_for(r.registry,effect.offer))or effect.result.selected_ids!=(effect.option_id,):
        raise ValueError('Assembly result changed the complete offered half sequence')
    cid=next((cid for oid,_,cid in option_rows(r.registry,effect.offer)if oid==effect.option_id),None)
    if cid is None:raise ValueError('Unknown assembly half selection')
    if spec.passive_power_template_id is not None:
        from .effects import ReplaceHeroPower
        return(ReplaceHeroPower(spec.player_id,cid,source_id=spec.source_id),)
    return(AddToHand(spec.player_id,cid,spec.source_id,cost=spec.cost,minion_grant=spec.minion_grant),)

def validate_boundary(game):
    frame=game._frame
    if frame is None:return
    selected=[e for o in frame.options for e in o.effects if type(e)is ResolveAssemble]
    choice=game._state.pending_choice
    if not selected and choice.purpose!=ChoicePurpose.ASSEMBLE:return
    if not selected or frame.on_select is not None:raise ValueError('Assembly lost its typed selection branches')
    offer=selected[0].offer;validate_offer(game.registry,game._generation_context,offer)
    validate_current(offer,game._state)
    expected=RequestChoice(offer.spec.player_id,options_for(game.registry,offer),offer.spec.source_id,
        offer.spec.prompt,purpose=ChoicePurpose.ASSEMBLE)
    if frame.options!=expected.options or tuple(o.item for o in expected.options)!=choice.options:
        raise ValueError('Assembly pending options differ from the original offer')
    if((choice.player_id,choice.source_id,choice.prompt,choice.min_count,choice.max_count,choice.purpose,choice.repeat_key)!=
            (offer.spec.player_id,offer.spec.source_id,offer.spec.prompt,1,1,ChoicePurpose.ASSEMBLE,None)):
        raise ValueError('Assembly pending choice changed its original actor or purpose')

def register(mechanics):
    mechanics.register_payload_type(AssembleOffer)
    mechanics.register(Assemble,assemble);mechanics.register(ResolveAssemble,resolve)
