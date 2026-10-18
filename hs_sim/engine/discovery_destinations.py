"""One original spell discovery with a subsequent finite destination decision."""
from dataclasses import dataclass,replace
from .effects import AddToHand,ChoiceOption,Effect,RequestChoice
from .errors import ResolutionError
from .model import CardType,ChoicePurpose,ChoiceResult,Zone
from .pools import DiscoverFromPool,PoolQuery

MODE='hand_or_opponent_top'
QUERY=PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current')
OPTIONS=('EDR_517A','EDR_517B')
PROMPT='选择法术去向'


def validate_spec(spec):
    if type(spec)is not DiscoverFromPool or spec.destination!=MODE or type(spec.source_id)is not int or spec.source_id<1:
        raise ValueError('Spell destination requires an original source-bound pool discovery')
    plain=DiscoverFromPool(spec.player_id,spec.pool_id,QUERY,source_id=spec.source_id)
    if replace(spec,destination='hand')!=plain:
        raise ValueError('Spell destination supports one plain current-class spell discovery only')


@dataclass(frozen=True)
class DeliverDiscoveredSpell(Effect):
    discovery: object
    keep: bool
    decision: ChoiceResult | None = None
    def __post_init__(self):
        from .discovery import ResolvePoolDiscovery
        if type(self.discovery)is not ResolvePoolDiscovery or type(self.keep)is not bool:
            raise ValueError('Spell destination requires its original pool selection and branch')
        self.discovery.__post_init__();validate_spec(self.discovery.batch.spec)
        if self.discovery.choice_result is None:raise ValueError('Spell destination requires an already committed discovery')
        if self.decision is not None:
            if type(self.decision)is not ChoiceResult:raise ValueError('Spell destination requires its complete decision')
            self.decision.__post_init__();q=self.decision.choice
            if ((q.purpose,q.player_id,q.source_id,q.prompt,q.min_count,q.max_count,q.repeat_key)!=
                    (ChoicePurpose.EFFECT,self.player_id,self.source_id,PROMPT,1,1,None) or
                    self.decision.selected_ids!=(OPTIONS[0 if self.keep else 1],)):
                raise ValueError('Spell destination decision borrowed another player, source or branch')
    @property
    def player_id(self):return self.discovery.batch.spec.player_id
    @property
    def source_id(self):return self.discovery.batch.spec.source_id
    @property
    def card_id(self):return self.discovery.selection.card_id
    @property
    def result(self):return self.discovery.choice_result


def options_for(registry,discovery):
    rows=[]
    for cid,keep in zip(OPTIONS,(True,False)):
        card=registry.card(cid)
        if not card.choice_only or card.kind!=CardType.SPELL:raise ValueError('Destination option must be its real nonphysical spell face')
        rows.append(ChoiceOption(cid,card.name,(DeliverDiscoveredSpell(discovery,keep),),card_id=cid))
    return tuple(rows)


def validate_original(state,registry,context,effect):
    from .card_discoveries import require_original_result
    from .discovery import validate_selection
    effect.__post_init__();validate_selection(registry,context,effect.discovery)
    require_original_result(state,effect.result)
    if effect.decision is not None and effect.decision.choice.options!=tuple(o.item for o in options_for(registry,effect.discovery)):
        raise ValueError('Spell destination changed its complete original two-option menu')


def begin(r,discovery):
    effect=DeliverDiscoveredSpell(discovery,True)
    validate_original(r.state,r.registry,r.game._generation_context,effect)
    return (RequestChoice(effect.player_id,options_for(r.registry,discovery),effect.source_id,prompt=PROMPT),)


def deliver(r,effect):
    validate_original(r.state,r.registry,r.game._generation_context,effect)
    if effect.decision is None:raise ResolutionError('Spell destination has no actual final decision')
    from .discovery_delivery import MaterializeDiscoveredCard
    return (MaterializeDiscoveredCard(effect.result,effect),)


def materialize(r,effect):
    validate_original(r.state,r.registry,r.game._generation_context,effect)
    if effect.decision is None:raise ResolutionError('Spell destination creation has no actual decision')
    if effect.keep:
        from .opening import create_hand_card
        return create_hand_card(r,AddToHand(effect.player_id,effect.card_id,effect.source_id))
    from .zones import AddToDeck,create_deck_card
    return create_deck_card(r,AddToDeck(3-effect.player_id,effect.card_id,'top',effect.source_id))


def validate_completion(completion,registry):
    effect=completion.recipe
    if type(effect)is not DeliverDiscoveredSpell:return
    if effect.decision is None or effect.result!=completion.result:
        raise ValueError('Spell destination completion lost its original discovery or decision')
    if effect.decision.choice.options!=tuple(o.item for o in options_for(registry,effect.discovery)):
        raise ValueError('Spell destination completion changed its original menu')
    fact=completion.recipient;recipient=effect.player_id if effect.keep else 3-effect.player_id
    if fact is not None and ((fact.owner,fact.controller,fact.card_id,fact.kind)!=(recipient,recipient,effect.card_id,CardType.SPELL)or
            fact.zone not in ((Zone.HAND,Zone.GRAVEYARD)if effect.keep else(Zone.DECK,))):
        raise ValueError('Spell destination completion changed its actual original recipient')


def validate_boundary(game):
    frame=game._frame
    if frame is None:return
    matches=[e for o in frame.options for e in o.effects if type(e)is DeliverDiscoveredSpell]
    if not matches:return
    first=matches[0];q=game._state.pending_choice
    validate_original(game._state,game.registry,game._generation_context,first)
    if (frame.on_select is not None or frame.options!=options_for(game.registry,first.discovery)or
            (q.purpose,q.player_id,q.source_id,q.prompt,q.min_count,q.max_count,q.repeat_key)!=
            (ChoicePurpose.EFFECT,first.player_id,first.source_id,PROMPT,1,1,None)):
        raise ValueError('Pending spell destination lost its original full menu')


def register(mechanics):mechanics.register(DeliverDiscoveredSpell,deliver)
