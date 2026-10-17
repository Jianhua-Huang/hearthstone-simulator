"""Repeated version-pool discoveries with explicit delivery timing and receipts."""
from dataclasses import dataclass, fields, is_dataclass, replace
from itertools import permutations
import json

from .construction import ids, name
from .effects import AddToHand, ChoiceOption, Effect, Heal, RequestChoice
from .errors import ResolutionError, ResolutionLimitExceeded
from .model import CardClass, CardPreview, CardType, ChoicePurpose, ChoiceResult, CostSpec, GameState
from .card_creation import DiscoveryMinionGift
from .pools import (DiscoverFromPool, GenerationContext, generation_candidates, resolve_candidates,
                    sample_candidates, deliver_generated)


@dataclass(frozen=True)
class DiscoveryPick:
    card_id: str
    hero_class: CardClass | None = None
    source_card_id: str | None = None
    gift: DiscoveryMinionGift | None = None

    def __post_init__(self):
        name(self.card_id, 'discovered card')
        if self.hero_class is not None and type(self.hero_class) is not CardClass:
            raise ValueError('Invalid captured discovery class')
        if self.source_card_id is not None: name(self.source_card_id, 'captured discovery source')
        if self.gift is not None:
            if type(self.gift) is not DiscoveryMinionGift:raise ValueError('Expected immutable discovery gift receipt')
            self.gift.__post_init__()


@dataclass(frozen=True)
class ContinuePoolDiscovery(Effect):
    spec: DiscoverFromPool
    selections: tuple[DiscoveryPick, ...] = ()
    producer_id: int | None = None

    def __post_init__(self):
        if type(self.spec) is not DiscoverFromPool: raise ValueError('Expected discovery specification')
        self.spec.__post_init__()
        attributed_board=self.spec.cause is not None and self.spec.destination=='board'
        if (self.producer_id is not None)!=attributed_board:raise ValueError('Discovery progress requires its original board attribution')
        if self.producer_id is not None:
            from .effects import _integer
            _integer(self.producer_id,'discovery producer',1)
        if type(self.selections) is not tuple or len(self.selections) > self.spec.discoveries:
            raise ValueError('Invalid discovery progress')
        for pick in self.selections:
            if type(pick) is not DiscoveryPick: raise ValueError('Expected immutable discovery receipt')
            pick.__post_init__()


@dataclass(frozen=True)
class ResolvePoolDiscovery(Effect):
    batch: ContinuePoolDiscovery
    offered_card_ids: tuple[str, ...]
    selection: DiscoveryPick
    choice_result: ChoiceResult | None = None
    offered_gifts: tuple[DiscoveryMinionGift, ...] = ()

    def __post_init__(self):
        if type(self.batch) is not ContinuePoolDiscovery: raise ValueError('Expected discovery batch')
        self.batch.__post_init__()
        ids(self.offered_card_ids, 'offered discovery cards', unique=True)
        if not 1 <= len(self.offered_card_ids) <= self.batch.spec.count:
            raise ValueError('Invalid offered discovery count')
        if type(self.selection) is not DiscoveryPick: raise ValueError('Expected discovery receipt')
        self.selection.__post_init__()
        if type(self.offered_gifts) is not tuple or any(type(g) is not DiscoveryMinionGift for g in self.offered_gifts):
            raise ValueError('Expected complete ordered discovery gift bindings')
        for gift in self.offered_gifts:gift.__post_init__()
        if self.batch.spec.gift_pool is None:
            if self.offered_gifts or self.selection.gift is not None:raise ValueError('Ordinary discovery cannot claim gifts')
        elif (len(self.offered_gifts) != len(self.offered_card_ids) or
                len({g.id for g in self.offered_gifts}) != len(self.offered_gifts)):
            raise ValueError('Gift discovery requires different gifts bound to every offered card')
        if self.choice_result is not None:
            if type(self.choice_result)is not ChoiceResult or (self.batch.producer_id is None and self.batch.spec.gift_pool is None and not self.batch.spec.heal_hero_by_printed_cost and self.batch.spec.summon_copy_stats is None and not self.batch.spec.shuffle_unselected_into_deck):raise ValueError('Actual result requires attributed discovery or a declared selected outcome')
            self.choice_result.__post_init__()
        if (self.selection.card_id not in self.offered_card_ids or
                len(self.batch.selections) >= self.batch.spec.discoveries):
            raise ValueError('Discovery selection exceeds its offered batch')


@dataclass(frozen=True)
class HealHeroFromDiscoveredSpell(Effect):
    discovery: ResolvePoolDiscovery
    context: GenerationContext

    def __post_init__(self):
        if type(self.discovery)is not ResolvePoolDiscovery or type(self.context)is not GenerationContext:
            raise ValueError('Discovered healing requires the original typed selection and context')
        self.discovery.__post_init__();self.context.__post_init__()
        if not self.discovery.batch.spec.heal_hero_by_printed_cost or self.discovery.choice_result is None:
            raise ValueError('Discovered healing requires an actual declared selection result')


@dataclass(frozen=True)
class DeliverAndSummonDiscoveredMinion(Effect):
    discovery:ResolvePoolDiscovery
    context:GenerationContext
    def __post_init__(self):
        if type(self.discovery)is not ResolvePoolDiscovery or type(self.context)is not GenerationContext:
            raise ValueError('Discovered copy requires original typed selection/context')
        self.discovery.__post_init__();self.context.__post_init__()
        if self.discovery.batch.spec.summon_copy_stats is None or self.discovery.choice_result is None:
            raise ValueError('Discovered copy requires its actual declared selection result')


def validate_selected_copy(registry,effect):
    effect.__post_init__();validate_selection(registry,effect.context,effect.discovery)


def deliver_and_summon_copy(r,effect):
    validate_selected_copy(r.registry,effect)
    if effect.context!=r.game._generation_context:raise ValueError('Discovered copy context changed')
    spec=effect.discovery.batch.spec
    from .summon_quantities import SummonByCard,SummonEntryMaterial,validate_cause,accept
    validate_cause(r.state,r.registry,spec.cause)
    if spec.cause.source.entity_id!=spec.source_id:raise ValueError('Discovered copy borrowed another cause')
    from .effects import AddToHand
    from .opening import create_hand_card
    from .model import Zone
    entity=create_hand_card(r,AddToHand(spec.player_id,effect.discovery.selection.card_id,spec.source_id))
    if entity.zone==Zone.HAND:
        from .copy_materials import CopyEntryMaterial
        material=CopyEntryMaterial.capture(r.state,entity,'stored_copy','current',spec.summon_copy_stats,
            registry=r.registry,player_id=spec.player_id)
    else:material=SummonEntryMaterial(entity.card_id,spec.summon_copy_stats)
    # The actual created object and its material/quantity are accepted before
    # acquisition reactions. Public creation and summon checkpoints still run.
    return accept(r,SummonByCard(spec.player_id,(material,),spec.cause))


def validate_cost_healing(registry,effect):
    effect.__post_init__()
    validate_selection(registry,effect.context,effect.discovery)


def heal_discovered_spell(r,effect):
    validate_cost_healing(r.registry,effect)
    if effect.context!=r.game._generation_context:raise ValueError('Discovered healing context changed')
    spec=effect.discovery.batch.spec
    if spec.source_id not in r.state.entities:raise ValueError('Discovered healing source does not exist')
    card=r.registry.card(effect.discovery.selection.card_id)
    return(Heal(r.player(spec.player_id).hero_id,card.cost,spec.source_id),)


def validate_gift_candidates(registry, context, spec, candidates):
    pool=spec.gift_pool
    if pool is None:return
    pool.__post_init__()
    if context is None or (pool.generation_target,pool.mode)!=(context.target_id,context.mode):
        raise ValueError('Discovery gift inventory differs from the generation context')
    if any(registry.card(m.card_id).kind != CardType.MINION for m in candidates):
        raise ValueError('Every gift discovery candidate must be a minion')


def validate_pick_gift(registry, spec, pick):
    pool=spec.gift_pool
    if pool is None:
        if pick.gift is not None:raise ValueError('Ordinary discovery cannot inherit a gift receipt')
    elif pick.gift not in pool.members or not pick.gift.eligible(registry.card(pick.card_id)):
        raise ValueError('Discovery gift differs from its declared recipe or printed eligibility')


def gift_preview(registry, card_id, gift, spec=None):
    card=registry.card(card_id);grant=gift.grant
    health=max(1,card.health+grant.health)
    source_delta = spec.cost.delta if spec is not None and spec.cost is not None else 0
    return CardPreview(max(0,card.cost+gift.cost_delta+source_delta),max(0,card.attack+grant.attack),health,health,0,
        tuple(sorted(set((*card.keywords,*grant.keywords)),key=lambda k:k.value)))


def options_for(registry, batch, offered, hero_class, source_card, gifts=()):
    options=[]
    for n,cid in enumerate(offered,1):
        gift=gifts[n-1] if gifts else None
        pick=DiscoveryPick(cid,hero_class,source_card,gift)
        options.append(ChoiceOption(f'generated-{n}',registry.card(cid).name if gift is None else
            registry.card(cid).name+' · '+gift.label+('（置于牌库顶）' if gift.destination=='deck_top' else ''),
            (ResolvePoolDiscovery(batch,offered,pick,offered_gifts=gifts),),card_id=cid,
            preview=None if gift is None else gift_preview(registry,cid,gift,batch.spec)))
    return tuple(options)


def sample_gifts(r, spec, offered):
    if spec.gift_pool is None:return ()
    return sample_eligible_gifts(r, spec.gift_pool.members, tuple(r.registry.card(cid) for cid in offered))


def sample_eligible_gifts(r, members, faces):
    """Share the original feasible-binding sampler with physical stored faces."""
    members=tuple(sorted(members,key=lambda g:g.id))
    # Uniform over feasible ordered bindings. Conditional gifts cannot silently
    # remove a minion, and a greedy assignment cannot lose a valid binding.
    possible=tuple(gs for gs in permutations(members,len(faces))
        if all(g.eligible(face) for face,g in zip(faces,gs)))
    if not possible:raise ResolutionError('No distinct eligible gift binding for the offered minions')
    return r.game._rng.choice(possible)


def deliver_pick(spec, pick):
    if pick.gift is None:return deliver_generated(spec,(pick.card_id,))
    gift=pick.gift
    delta=gift.cost_delta+(spec.cost.delta if spec.cost is not None else 0)
    cost=CostSpec(delta=delta) if delta else None
    grant=replace(gift.grant,identity=gift.id)
    hand=AddToHand(spec.player_id,pick.card_id,spec.source_id,cost=cost,minion_grant=grant)
    if gift.destination=='deck_top':
        from .zones import AddToDeck
        original=AddToDeck(spec.player_id,pick.card_id,'top',spec.source_id,cost=cost,minion_grant=grant)
    else:original=hand
    # Both immutable recipes are accepted before acquisition reactions. The
    # ordinary creation layer allocates fresh identities and attachment lifetimes.
    return (original,hand) if spec.gift_copy_to_hand else (original,)


def eligible(registry, context, spec, pick):
    if (spec.query.class_mode in ('current','other')) != (pick.hero_class is not None):
        raise ValueError('Discovery receipt class policy disagrees with query')
    if (spec.source_id is None) != (pick.source_card_id is None):
        raise ValueError('Discovery receipt source policy disagrees with query')
    if pick.source_card_id is not None: registry.card(pick.source_card_id)
    candidates = resolve_candidates(registry, context, spec.pool_id, spec.query,
        current_class=pick.hero_class, source_card_id=pick.source_card_id, policy=spec.policy, player_id=spec.player_id,
        exclude_source_by_rule=True)
    for member in candidates:
        definition=registry.card(member.card_id)
        if (definition.choice_only or (definition.kind != CardType.MINION if spec.destination=='board'
                                      else not definition.hand_playable)):
            raise ValueError('Discovery candidate cannot enter its declared destination')
    from .card_creation import validate_candidates
    validate_candidates(spec, (registry.card(m.card_id) for m in candidates))
    validate_gift_candidates(registry,context,spec,candidates)
    validate_pick_gift(registry,spec,pick)
    return candidates


def validate_batch(registry, context, batch):
    batch.__post_init__(); used=set()
    for pick in batch.selections:
        if pick.card_id not in {m.card_id for m in eligible(registry,context,batch.spec,pick)}:
            raise ValueError('Prior discovery is not a valid captured candidate')
        identity=registry.pool_card(pick.card_id).generation_identity
        if not batch.spec.replacement and identity in used:
            raise ValueError('Non-replacement discovery repeats an identity')
        used.add(identity)
    return used


def validate_selection(registry, context, effect):
    effect.__post_init__(); batch=effect.batch; spec=batch.spec
    used=validate_batch(registry,context,batch)
    candidates=eligible(registry,context,spec,effect.selection)
    if not spec.replacement:
        candidates=tuple(m for m in candidates if registry.pool_card(m.card_id).generation_identity not in used)
    allowed={m.card_id for m in candidates}
    offered=effect.offered_card_ids
    identities={registry.pool_card(i).generation_identity for i in offered}
    if (not set(offered).issubset(allowed) or len(offered)!=min(spec.count,len(candidates)) or
            len(identities)!=len(offered)):
        raise ValueError('Offered discovery candidates disagree with declared pool')
    if spec.gift_pool is not None:
        for cid,gift in zip(offered,effect.offered_gifts):
            validate_pick_gift(registry,spec,DiscoveryPick(cid,effect.selection.hero_class,effect.selection.source_card_id,gift))
        if effect.selection.gift != effect.offered_gifts[offered.index(effect.selection.card_id)]:
            raise ValueError('Selected gift belongs to another offered minion')
    if effect.choice_result is not None and(spec.gift_pool is not None or spec.heal_hero_by_printed_cost or spec.summon_copy_stats is not None or spec.shuffle_unselected_into_deck):
        result=effect.choice_result;choice=result.choice
        expected=tuple(o.item for o in options_for(registry,batch,offered,
            effect.selection.hero_class,effect.selection.source_card_id,effect.offered_gifts))
        if (choice.purpose!=ChoicePurpose.POOL_DISCOVERY or choice.options!=expected or
                (choice.player_id,choice.source_id,choice.prompt,choice.min_count,choice.max_count,choice.repeat_key)!=
                (spec.player_id,spec.source_id,spec.prompt,1,1,None) or
                result.selected_ids!=(f'generated-{offered.index(effect.selection.card_id)+1}',)):
            raise ValueError('Pool receipt differs from the actual complete discovery choice/result')


def start(r, effect):
    if effect.destination=='board'and effect.cause is None:
        from .summon_quantities import reject_ambiguous
        reject_ambiguous(r)
    effect.__post_init__()
    if effect.count > r.rules.max_choice_options:
        raise ResolutionLimitExceeded('Discover exceeds the offered choice limit')
    if effect.discoveries > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Discover repetitions exceed resolution budget')
    # Even a zero-round request cannot conceal missing context/content.
    candidates=generation_candidates(r,effect)
    validate_gift_candidates(r.registry,r.game._generation_context,effect,candidates)
    from .costs import validate_creation_cost
    validate_creation_cost(r.state,effect,(r.registry.card(m.card_id) for m in candidates))
    if effect.cause is not None and effect.destination=='board':
        from .discovery_summons import start as start_attributed
        return start_attributed(r,effect,candidates)
    return (ContinuePoolDiscovery(effect),) if effect.discoveries else ()


def continue_discovery(r, batch):
    if batch.spec.destination=='board'and batch.spec.cause is None:
        from .summon_quantities import reject_ambiguous
        reject_ambiguous(r)
    used=validate_batch(r.registry,r.game._generation_context,batch); spec=batch.spec
    if len(batch.selections)==spec.discoveries:
        if batch.producer_id is not None:
            from .discovery_summons import ready
            return ready(r,batch)
        return deliver_generated(spec,tuple(x.card_id for x in batch.selections)) if spec.delivery=='after_all' else ()
    candidates=generation_candidates(r,spec)
    validate_gift_candidates(r.registry,r.game._generation_context,spec,candidates)
    from .costs import validate_creation_cost
    validate_creation_cost(r.state,spec,(r.registry.card(m.card_id) for m in candidates))
    if batch.producer_id is not None:
        from .discovery_summons import make_offer
        offer=make_offer(r,batch,candidates);offered=offer.offered
    else:
        if not spec.replacement:
            candidates=tuple(m for m in candidates if r.registry.pool_card(m.card_id).generation_identity not in used)
        offered=sample_candidates(r.game._rng,candidates,spec.count,replacement=False)
    if not offered:
        if batch.producer_id is not None:
            from .discovery_summons import ready
            return ready(r,batch)
        return deliver_generated(spec,tuple(x.card_id for x in batch.selections)) if spec.delivery=='after_all' else ()
    hero_class=r.player(spec.player_id).hero_class if spec.query.class_mode in ('current','other') else None
    source_card=r.state.entities[spec.source_id].card_id if spec.source_id is not None else None
    options=options_for(r.registry,batch,offered,hero_class,source_card,sample_gifts(r,spec,offered))
    return (RequestChoice(spec.player_id,options,source_id=spec.source_id,prompt=spec.prompt,
                          purpose=ChoicePurpose.POOL_DISCOVERY),)


def resolve_discovery(r, effect):
    if effect.batch.spec.destination=='board'and effect.batch.spec.cause is None:
        from .summon_quantities import reject_ambiguous
        reject_ambiguous(r)
    validate_selection(r.registry,r.game._generation_context,effect)
    batch=effect.batch; spec=batch.spec
    if spec.summon_copy_stats is not None and effect.choice_result is None:
        raise ValueError('Discovered copy requires the actual complete choice result')
    if spec.heal_hero_by_printed_cost and effect.choice_result is None:
        raise ValueError('Discovery cost healing requires the actual complete choice result')
    if spec.gift_pool is not None:
        if effect.choice_result is None:raise ValueError('Gift delivery requires the actual discovery result')
        from .continuations import FrameCodec
        r.emit('pool_discovery_picked',source_id=spec.source_id,player_id=spec.player_id,
            choice_id=effect.choice_result.choice.id,card_id=effect.selection.card_id,gift_id=effect.selection.gift.id,
            receipt=json.dumps(FrameCodec(r.game.mechanics,r.registry).encode(effect),ensure_ascii=False,
                sort_keys=True,separators=(',',':')),_capture=False)
    continued=ContinuePoolDiscovery(spec,(*batch.selections,effect.selection),batch.producer_id)
    if batch.producer_id is not None:
        from .discovery_summons import select_offer
        delivery=select_offer(r,effect)
    elif spec.shuffle_unselected_into_deck:
        from .discovery_remainders import begin
        delivery=begin(r,effect)
    elif spec.summon_copy_stats is not None:delivery=(DeliverAndSummonDiscoveredMinion(effect,r.game._generation_context),)
    else:delivery=deliver_pick(spec,effect.selection) if spec.delivery=='after_each' else ()
    healing=(HealHeroFromDiscoveredSpell(effect,r.game._generation_context),)if spec.heal_hero_by_printed_cost else()
    return (*delivery,*healing,continued)


def validate_boundary(game):
    from .discovery_remainders import validate_boundary as validate_remainders
    validate_remainders(game)
    frame=game._frame; choice=game._state.pending_choice
    if frame is None:return
    def visit(value,depth=0):
        from .continuations import FrameCodec
        if depth>FrameCodec.MAX_DEPTH:raise ValueError('Discovery outcome frame depth exceeded')
        if type(value)is HealHeroFromDiscoveredSpell:
            validate_cost_healing(game.registry,value)
            if value.context!=game._generation_context or value.discovery.batch.spec.source_id not in game._state.entities:
                raise ValueError('Discovered healing context or source differs from its queued outcome')
            return
        if type(value)is DeliverAndSummonDiscoveredMinion:
            validate_selected_copy(game.registry,value)
            if value.context!=game._generation_context:raise ValueError('Discovered copy context differs from queued outcome')
            from .summon_quantities import validate_cause
            validate_cause(game._state,game.registry,value.discovery.batch.spec.cause)
            return
        if type(value)is GameState:return
        if type(value)in(tuple,list):
            for child in value:visit(child,depth+1)
        elif is_dataclass(value):
            for field in fields(value):visit(getattr(value,field.name),depth+1)
    visit(frame)
    for work in (*frame.prefix,*frame.continuation):
        if type(work) is ContinuePoolDiscovery:validate_batch(game.registry,game._generation_context,work)
        if type(work) is ResolvePoolDiscovery:validate_selection(game.registry,game._generation_context,work)
    if choice.purpose != ChoicePurpose.POOL_DISCOVERY:return
    if choice.min_count!=1 or choice.max_count!=1 or choice.repeat_key is not None or frame.on_select is not None:
        raise ValueError('Invalid pool discovery choice structure')
    first=None; offered=tuple(o.card_id for o in frame.options)
    for n,option in enumerate(frame.options,1):
        if len(option.effects)!=1 or type(option.effects[0]) is not ResolvePoolDiscovery:
            raise ValueError('Pool discovery requires a typed selection branch')
        effect=option.effects[0]; validate_selection(game.registry,game._generation_context,effect)
        spec=effect.batch.spec
        expected=options_for(game.registry,effect.batch,effect.offered_card_ids,
            effect.selection.hero_class,effect.selection.source_card_id,effect.offered_gifts)[n-1]
        if (option.id!=f'generated-{n}' or option.card_id!=effect.selection.card_id or
                effect.offered_card_ids!=offered or option.entity_id is not None or option.preview!=expected.preview or
                option.label!=expected.label or effect.choice_result is not None or
                (choice.player_id,choice.source_id,choice.prompt)!=(spec.player_id,spec.source_id,spec.prompt) or
                first is not None and (effect.batch,effect.selection.hero_class,effect.selection.source_card_id,effect.offered_gifts)!=first):
            raise ValueError('Discovery option metadata and captured branches disagree')
        first=(effect.batch,effect.selection.hero_class,effect.selection.source_card_id,effect.offered_gifts)
    if first is None:raise ValueError('Pool discovery cannot offer an empty choice')


def register(mechanics):
    mechanics.register_payload_type(DiscoveryPick)
    mechanics.register(ContinuePoolDiscovery,continue_discovery)
    mechanics.register(ResolvePoolDiscovery,resolve_discovery)
    mechanics.register(HealHeroFromDiscoveredSpell,heal_discovered_spell)
    mechanics.register(DeliverAndSummonDiscoveredMinion,deliver_and_summon_copy)
    from .discovery_remainders import register as register_remainders
    register_remainders(mechanics)
