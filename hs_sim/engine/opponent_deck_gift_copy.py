"""One real opponent-deck copy discovery, optionally with an atomic Dark Gift."""
from dataclasses import dataclass,replace
from .effects import ChoiceOption,Effect,RequestChoice,_integer,_player
from .model import CardPreview,CardType,ChoicePurpose,CostSpec,Zone
from .copy_materials import CapturedCardCopyMaterial,validate_captured_card_copy
from .dark_gifts import DARK_GIFTS
from .discovery import sample_eligible_gifts
from .stored_gift_discovery import eligible_face,gift_by_id,StoredGiftOffer,preview as gift_preview
from .zones import ChooseFromZone,CopyCard,CardReference,source_exists,sample_zone_choices
from .pools import PoolQuery
from .lifecycle import refresh_entity
from .card_conditions import has_battlecry

PROMPT='发现对手牌库中一张随从的复制'


def current_face(material, registry=None):
    entity=material.entity();refresh_entity(entity)
    return CardPreview.capture(entity, registry),has_battlecry(entity.abilities)


@dataclass(frozen=True)
class DiscoverOpponentDeckCopy(Effect):
    player_id: int
    source_id: int
    gift: bool = False
    def __post_init__(self):
        _player(self.player_id);_integer(self.source_id,'opponent copy source',1)
        if type(self.gift)is not bool:raise ValueError('Opponent copy requires the actual captured Combo flag')


@dataclass(frozen=True)
class DeckCopyOffer:
    material: CapturedCardCopyMaterial
    gift_id: str | None = None
    def __post_init__(self):
        if type(self.material)is not CapturedCardCopyMaterial:raise ValueError('Deck copy offer requires original immutable material')
        self.material.__post_init__()
        if self.material.origin.zone!=Zone.DECK or self.material.origin.kind!=CardType.MINION:
            raise ValueError('Deck copy requires its original deck minion')
        if self.gift_id is not None:
            face,cry=current_face(self.material)
            if not gift_by_id(self.gift_id).eligible(eligible_face(face,cry)):
                raise ValueError('Original copied minion is not eligible for its paired gift')
    @property
    def card_id(self):return self.material.origin.card_id


@dataclass(frozen=True)
class CopyOpponentDeckOffer(Effect):
    request: DiscoverOpponentDeckCopy
    offered: tuple[DeckCopyOffer,...]
    index: int
    def __post_init__(self):
        if type(self.request)is not DiscoverOpponentDeckCopy:raise ValueError('Deck copy requires its actual request')
        self.request.__post_init__()
        if type(self.offered)is not tuple or not 1<=len(self.offered)<=3:raise ValueError('Deck copy requires its complete finite offer')
        for offer in self.offered:
            if type(offer)is not DeckCopyOffer:raise ValueError('Deck copy requires typed material offers')
            offer.__post_init__()
            if offer.material.origin.controller!=3-self.player_id or (offer.gift_id is not None)!=self.request.gift:
                raise ValueError('Deck copy changed its original opponent or Combo gift policy')
        if len({o.card_id for o in self.offered})!=len(self.offered):raise ValueError('Deck copy offers must have distinct faces')
        if self.request.gift and len({o.gift_id for o in self.offered})!=len(self.offered):raise ValueError('Deck copy gifts must be distinct')
        _integer(self.index,'original deck copy index',0)
        if self.index>=len(self.offered):raise ValueError('Deck copy index is outside its original menu')
    @property
    def player_id(self):return self.request.player_id
    @property
    def source_id(self):return self.request.source_id
    @property
    def card_id(self):return self.offered[self.index].card_id


def options_for(registry,request,offered):
    rows=[]
    for i,offer in enumerate(offered):
        face,cry=current_face(offer.material, registry);label=face.display_name or registry.card(offer.card_id).name
        if offer.gift_id is not None:
            gift=gift_by_id(offer.gift_id);label+=' · '+gift.label+('（置于牌库顶）'if gift.destination=='deck_top'else'')
            ref=CardReference.capture(offer.material.entity())
            face=gift_preview(StoredGiftOffer(ref,face,cry,gift.id))
        rows.append(ChoiceOption('deck-copy-'+str(i+1),label,(CopyOpponentDeckOffer(request,offered,i),),card_id=offer.card_id,preview=face))
    return tuple(rows)


def validate_materials(state,registry,effect):
    effect.__post_init__()
    if effect.source_id not in state.entities:raise ValueError('Opponent copy source does not exist')
    for offer in effect.offered:validate_captured_card_copy(state,registry,offer.material)


def discover(r,effect):
    effect.__post_init__();source_exists(r,effect.source_id)
    refs=sample_zone_choices(r,ChooseFromZone(effect.player_id,3-effect.player_id,Zone.DECK,
        PoolQuery(kinds=(CardType.MINION,)),operation='copy_current',source_id=effect.source_id,discovery=True))
    if not refs:return ()
    materials=tuple(CapturedCardCopyMaterial.capture(r.state,r.state.entities[ref.entity_id])for ref in refs)
    faces=tuple(current_face(m, r.registry)for m in materials)
    gifts=sample_eligible_gifts(r,DARK_GIFTS,tuple(eligible_face(face,cry)for face,cry in faces))if effect.gift else(None,)*len(refs)
    offered=tuple(DeckCopyOffer(m,None if g is None else g.id)for m,g in zip(materials,gifts))
    return (RequestChoice(effect.player_id,options_for(r.registry,effect,offered),effect.source_id,prompt=PROMPT,purpose=ChoicePurpose.CARD_DISCOVERY),)


def validate_recipe(result,effect):
    effect.__post_init__();q=result.choice
    if ((q.purpose,q.player_id,q.source_id,q.prompt,q.min_count,q.max_count,q.repeat_key)!=
            (ChoicePurpose.CARD_DISCOVERY,effect.player_id,effect.source_id,PROMPT,1,1,None)or
            result.selected_ids!=('deck-copy-'+str(effect.index+1),)):
        raise ValueError('Copied discovery recipe changed its original source or selection')


def validate_completion(completion,registry):
    effect=completion.recipe
    if type(effect)is not CopyOpponentDeckOffer:return
    validate_recipe(completion.result,effect)
    if completion.result.choice.options!=tuple(o.item for o in options_for(registry,effect.request,effect.offered)):
        raise ValueError('Opponent copy completion changed its complete original material menu')
    fact=completion.recipient;offer=effect.offered[effect.index]
    deck=offer.gift_id is not None and gift_by_id(offer.gift_id).destination=='deck_top'
    if fact is None:
        if deck:return  # The original delivery window must prove full-deck denial.
        raise ValueError('Opponent copy completion lost its actual new minion recipient')
    if (fact.owner,fact.controller,fact.card_id,fact.kind)!=(effect.player_id,effect.player_id,effect.card_id,CardType.MINION)or fact.zone not in ((Zone.DECK,)if deck else(Zone.HAND,Zone.GRAVEYARD)):
        raise ValueError('Opponent copy completion lost its actual new minion recipient')


def materialize(r,effect):
    from .zones import copy_physical_card
    validate_materials(r.state,r.registry,effect)
    offer=effect.offered[effect.index];gift=gift_by_id(offer.gift_id)if offer.gift_id is not None else None
    recipe=CopyCard(offer.material,effect.player_id,destination=Zone.DECK if gift is not None and gift.destination=='deck_top'else Zone.HAND,
        position='top'if gift is not None and gift.destination=='deck_top'else'random',source_id=effect.source_id,
        cost=CostSpec(delta=gift.cost_delta)if gift is not None and gift.cost_delta else None)
    return copy_physical_card(r,recipe,minion_grant=replace(gift.grant,identity=gift.id)if gift is not None else None)


def direct(r,effect):materialize(r,effect)


def validate_boundary(game):
    frame=game._frame
    if frame is None:return
    matches=[e for o in frame.options for e in o.effects if type(e)is CopyOpponentDeckOffer]
    if not matches:return
    first=matches[0];validate_materials(game._state,game.registry,first);q=game._state.pending_choice
    if (frame.on_select is not None or frame.options!=options_for(game.registry,first.request,first.offered)or
            (q.purpose,q.player_id,q.source_id,q.prompt,q.min_count,q.max_count,q.repeat_key)!=
            (ChoicePurpose.CARD_DISCOVERY,first.player_id,first.source_id,PROMPT,1,1,None)):
        raise ValueError('Opponent copy discovery lost its complete original menu')


def register(mechanics):
    mechanics.register_payload_type(DeckCopyOffer)
    mechanics.register(DiscoverOpponentDeckCopy,discover)
    mechanics.register(CopyOpponentDeckOffer,direct)
