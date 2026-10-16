"""Choose one result from independently sampled groups, with frozen affordability.

Affordability uses the payment engine, not target/board legality. R-106 records
the Priest policy separately from the reusable grouped-offer contract.
"""
from dataclasses import dataclass
from .construction import ids, name, integer
from .costs import quote_generated_cost, payment_error, validate_creation_cost, matches_cost
from .effects import Effect, ChoiceOption, RequestChoice, AddToHand, _player, _source, validate_generated_cost
from .errors import ResolutionError, ResolutionLimitExceeded
from .model import CardClass, CardPreview, ChoicePurpose, CostSpec
from .pools import (PoolQuery, GenerationPolicy, GenerateFromPool, generation_candidates,
    resolve_candidates, sample_candidates, validate_policy)
from .temporary_cards import CreateTemporaryCard


@dataclass(frozen=True)
class PoolOfferGroup:
    pool_id: str
    query: PoolQuery = PoolQuery()
    count: int = 1

    def __post_init__(self):
        name(self.pool_id,'offer pool');integer(self.count,'group offer count')
        if type(self.query) is not PoolQuery:raise ValueError('Offer group requires PoolQuery')
        self.query.__post_init__()


@dataclass(frozen=True)
class ChooseFromPools(Effect):
    player_id: int
    groups: tuple[PoolOfferGroup,...]
    source_id: int | None = None
    cost: CostSpec | None = None
    expires_turn: int | None = None
    temporary_until: int | None = None
    minimum_cost: int = 0
    affordable: bool = False
    policy: GenerationPolicy = GenerationPolicy()
    prompt: str = '选择一张牌'

    def __post_init__(self):
        _player(self.player_id);_source(self.source_id);name(self.prompt,'offer prompt')
        if type(self.groups) is not tuple or not self.groups:raise ValueError('Expected nonempty offer groups')
        for group in self.groups:
            if type(group) is not PoolOfferGroup:raise ValueError('Expected PoolOfferGroup')
            group.__post_init__()
        validate_generated_cost(self.cost,self.expires_turn);validate_policy(self.policy)
        if self.temporary_until is not None:integer(self.temporary_until,'temporary deadline')
        integer(self.minimum_cost,'temporary cost floor',0)
        if self.minimum_cost and self.temporary_until is None:raise ValueError('A final cost floor requires a temporary card')
        if type(self.affordable) is not bool:raise ValueError('Affordability policy must be boolean')


@dataclass(frozen=True)
class OfferedPoolCard:
    card_id: str
    preview: CardPreview

    def __post_init__(self):
        name(self.card_id,'offered card')
        if type(self.preview) is not CardPreview:raise ValueError('Expected captured offer preview')
        self.preview.__post_init__()


@dataclass(frozen=True)
class CapturedOfferGroup:
    eligible_ids: tuple[str,...]
    offered: tuple[OfferedPoolCard,...]

    def __post_init__(self):
        ids(self.eligible_ids,'captured eligible cards',unique=True)
        if type(self.offered) is not tuple:raise ValueError('Expected frozen group results')
        for card in self.offered:
            if type(card) is not OfferedPoolCard:raise ValueError('Expected offered pool card')
            card.__post_init__()
        offered=tuple(c.card_id for c in self.offered)
        ids(offered,'group results',unique=True)
        if not set(offered).issubset(self.eligible_ids):raise ValueError('Offered card outside captured eligibility')


@dataclass(frozen=True)
class PoolOfferReceipt:
    spec: ChooseFromPools
    groups: tuple[CapturedOfferGroup,...]
    hero_class: CardClass | None
    source_card_id: str | None
    turn: int

    def __post_init__(self):
        if type(self.spec) is not ChooseFromPools:raise ValueError('Expected grouped offer specification')
        self.spec.__post_init__();integer(self.turn,'offer capture turn')
        if type(self.groups) is not tuple or len(self.groups)!=len(self.spec.groups):raise ValueError('Offer group count mismatch')
        for group in self.groups:
            if type(group) is not CapturedOfferGroup:raise ValueError('Expected captured offer group')
            group.__post_init__()
        needs_class=any(g.query.class_mode in ('current','other') for g in self.spec.groups)
        if needs_class != (self.hero_class is not None) or self.hero_class is not None and type(self.hero_class) is not CardClass:
            raise ValueError('Offer class capture disagrees with queries')
        if (self.spec.source_id is None)!=(self.source_card_id is None):raise ValueError('Offer source capture mismatch')
        if self.source_card_id is not None:name(self.source_card_id,'offer source card')
        if self.spec.temporary_until is not None and self.spec.temporary_until<self.turn:raise ValueError('Expired offer lifetime')
        if self.spec.expires_turn is not None and self.spec.expires_turn<self.turn:raise ValueError('Expired offer cost')


@dataclass(frozen=True)
class ResolvePoolOffer(Effect):
    receipt: PoolOfferReceipt
    group_index: int
    card_id: str

    def __post_init__(self):
        if type(self.receipt) is not PoolOfferReceipt:raise ValueError('Expected pool offer receipt')
        self.receipt.__post_init__();integer(self.group_index,'offer group index',0);name(self.card_id,'selected offer')
        if (self.group_index>=len(self.receipt.groups) or self.card_id not in
                {c.card_id for c in self.receipt.groups[self.group_index].offered}):
            raise ValueError('Selection outside captured offers')


def preview(definition, cost):
    return CardPreview(cost,definition.attack,definition.health,definition.health,definition.durability,
                       tuple(sorted(definition.keywords,key=lambda k:k.value)))


def candidates(r,spec,group):
    request=GenerateFromPool(spec.player_id,group.pool_id,group.query,source_id=spec.source_id,
        cost=spec.cost,expires_turn=spec.expires_turn,policy=spec.policy)
    rows=generation_candidates(r,request)
    validate_creation_cost(r.state,spec,(r.registry.card(m.card_id) for m in rows))
    quotes={m.card_id:quote_generated_cost(r.state,r.registry,spec.player_id,m.card_id,
        cost=spec.cost,minimum_cost=spec.minimum_cost) for m in rows}
    # Every eligible definition/cost is validated before filtering or RNG.
    return tuple(m for m in rows if not spec.affordable or payment_error(r.state,quotes[m.card_id]) is None),quotes


def choose_from_pools(r,spec):
    spec.__post_init__()
    if sum(g.count for g in spec.groups)>r.rules.max_choice_options:raise ResolutionLimitExceeded('Grouped offers exceed choice limit')
    if spec.temporary_until is not None and spec.temporary_until<r.state.turn:raise ResolutionError('Temporary offer has expired')
    prepared=[candidates(r,spec,group) for group in spec.groups]
    groups=[]
    for group,(rows,quotes) in zip(spec.groups,prepared):
        chosen=sample_candidates(r.game._rng,rows,group.count,replacement=False)
        groups.append(CapturedOfferGroup(tuple(m.card_id for m in rows),tuple(OfferedPoolCard(cid,
            preview(r.registry.card(cid),quotes[cid].amount)) for cid in chosen)))
    if not any(g.offered for g in groups):return ()
    hero_class=r.player(spec.player_id).hero_class if any(g.query.class_mode in ('current','other') for g in spec.groups) else None
    source=r.state.entities[spec.source_id].card_id if spec.source_id is not None else None
    receipt=PoolOfferReceipt(spec,tuple(groups),hero_class,source,r.state.turn)
    return (RequestChoice(spec.player_id,options(r.registry,receipt),spec.source_id,spec.prompt),)


def options(registry,receipt):
    return tuple(ChoiceOption(f'pool-{i+1}-{n+1}',registry.card(card.card_id).name,
        (ResolvePoolOffer(receipt,i,card.card_id),),card_id=card.card_id,preview=card.preview)
        for i,group in enumerate(receipt.groups) for n,card in enumerate(group.offered))


def validate_receipt(registry,context,receipt):
    receipt.__post_init__();spec=receipt.spec
    if receipt.source_card_id is not None:registry.card(receipt.source_card_id)
    for group,captured in zip(spec.groups,receipt.groups):
        rows=resolve_candidates(registry,context,group.pool_id,group.query,current_class=receipt.hero_class,
            source_card_id=receipt.source_card_id,policy=spec.policy,player_id=spec.player_id,exclude_source_by_rule=True)
        allowed=tuple(m.card_id for m in rows)
        if any(not registry.card(cid).hand_playable for cid in allowed):raise ValueError('Offer pool includes non-hand content')
        if spec.cost is not None and any(not matches_cost(spec.cost,registry.card(cid)) for cid in allowed):
            raise ValueError('Offer cost does not match every candidate')
        if (not set(captured.eligible_ids).issubset(allowed) or
            captured.eligible_ids!=tuple(cid for cid in allowed if cid in captured.eligible_ids) or
            not spec.affordable and captured.eligible_ids!=allowed or
            len(captured.offered)!=min(group.count,len(captured.eligible_ids))):
            raise ValueError('Captured group eligibility or offer size mismatch')
        for card in captured.offered:
            if card.preview!=preview(registry.card(card.card_id),card.preview.cost):raise ValueError('Offer preview differs from definition')
            if card.preview.cost<spec.minimum_cost:raise ValueError('Offer preview violates final cost floor')


def resolve_offer(r,effect):
    effect.__post_init__();validate_receipt(r.registry,r.game._generation_context,effect.receipt)
    spec=effect.receipt.spec
    if spec.temporary_until is not None:
        return (CreateTemporaryCard(spec.player_id,effect.card_id,spec.temporary_until,spec.minimum_cost,
            spec.source_id,spec.cost,spec.expires_turn),)
    return (AddToHand(spec.player_id,effect.card_id,spec.source_id,cost=spec.cost,expires_turn=spec.expires_turn),)


def validate_boundary(game):
    frame=game._frame
    if frame is None:return
    def check(work):
        if type(work) is ResolvePoolOffer:
            work.__post_init__();validate_receipt(game.registry,game._generation_context,work.receipt)
            spec=work.receipt.spec
            if work.receipt.turn>game._state.turn or spec.source_id is not None and spec.source_id not in game._state.entities:
                raise ValueError('Invalid captured offer source or chronology')
        elif type(work) is ChooseFromPools:
            work.__post_init__()
            for group in work.groups:game.registry.pool(group.pool_id,game._generation_context)
            if work.source_id is not None and work.source_id not in game._state.entities:raise ValueError('Missing offer source')
    for work in (*frame.prefix,*frame.continuation):check(work)
    selected=[]
    for option in frame.options:
        for work in option.effects:
            check(work)
            if type(work) is ResolvePoolOffer:selected.append(work)
    if not selected:return
    receipt=selected[0].receipt;spec=receipt.spec;choice=game._state.pending_choice
    if (frame.options!=options(game.registry,receipt) or frame.on_select is not None or
        (choice.player_id,choice.source_id,choice.prompt,choice.min_count,choice.max_count,choice.purpose,choice.repeat_key)!=
        (spec.player_id,spec.source_id,spec.prompt,1,1,ChoicePurpose.EFFECT,None)):
        raise ValueError('Grouped offer branches disagree with the public choice')


def register(mechanics):
    for cls in (PoolOfferGroup,OfferedPoolCard,CapturedOfferGroup,PoolOfferReceipt):mechanics.register_payload_type(cls)
    mechanics.register(ChooseFromPools,choose_from_pools)
    mechanics.register(ResolvePoolOffer,resolve_offer)
