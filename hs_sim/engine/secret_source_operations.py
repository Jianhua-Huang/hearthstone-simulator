"""Original physical deck secrets and original live paid-hand copy sources."""
from dataclasses import dataclass

from .effects import Effect,_integer,_player
from .errors import ResolutionError
from .model import CardType,CostSpec,Zone
from .zones import CardReference,CopyCard,reference_entity


@dataclass(frozen=True)
class InstallDeckSecrets(Effect):
    cast_id: int
    cards: tuple[CardReference,...] | None = None
    used_keys: tuple[str,...] = ()

    def __post_init__(self):
        _integer(self.cast_id,'original deck-secret cast',1)
        if self.cards is not None:
            if type(self.cards) is not tuple or any(type(x) is not CardReference for x in self.cards):
                raise ValueError('Deck secrets require immutable original card references')
            for ref in self.cards:
                ref.__post_init__()
                if ref.zone!=Zone.DECK:raise ValueError('Original secret reference must be in the deck')
            if len({x.entity_id for x in self.cards})!=len(self.cards):
                raise ValueError('Original deck-secret references cannot repeat')
        if (type(self.used_keys) is not tuple or any(type(x) is not str or not x for x in self.used_keys) or
                len(set(self.used_keys))!=len(self.used_keys) or self.cards is None and self.used_keys):
            raise ValueError('Deck-secret plan requires unique original used keys')

    def validate_in_state(self,state,registry):
        self.__post_init__()
        from .spell_casts import active_cast,cast_record
        cast=cast_record(state,self.cast_id)
        if (registry.card(cast.card_id).kind!=CardType.SPELL or not cast.payload_started or cast.completed or
                cast.interrupted or cast.failure is not None or active_cast(state,cast.source_id,cast.player_id)!=cast):
            raise ValueError('Deck-secret installation requires its actual active spell cast')
        if self.cards is not None:
            for ref in self.cards:
                if ref.player_id!=cast.player_id or registry.card(ref.card_id).secret is None:
                    raise ValueError('Deck-secret plan borrowed another owner or non-secret card')
        return cast


def install(r,request):
    cast=request.validate_in_state(r.state,r.registry);player=r.player(cast.player_id)
    from .secrets import activate,area_count
    if area_count(player,r.registry)>=r.rules.max_secret_zone:return ()
    active={r.registry.card(r.state.entities[i].card_id).secret.key for i in player.secrets}
    cards=request.cards
    used=request.used_keys
    if cards is None:
        cards=tuple(CardReference.capture(r.state.entities[i]) for i in player.deck
            if r.registry.card(r.state.entities[i].card_id).secret is not None)
        used=tuple(sorted(active))
    candidates=[]
    for ref in cards:
        key=r.registry.card(ref.card_id).secret.key
        if key in used or key in active:continue
        entity=reference_entity(r,ref)
        if entity is not None:candidates.append(entity)
    if not candidates:return ()
    selected=candidates[0]
    if len(candidates)>1:
        selected=r.game._rng.choice(candidates)
        # Original deck identities remain private, including the physical card
        # selected before its ordinary hidden secret-set publication.
        r.emit('random_choice',source_id=cast.source_id,player_id=cast.player_id,
            producer='deck_unique_secrets',cast_id=cast.id,
            _deck_candidates=tuple(e.id for e in candidates),_deck_selected=selected.id)
    key=r.registry.card(selected.card_id).secret.key
    activate(r,selected)
    return (InstallDeckSecrets(cast.id,cards,(*used,key)),)


@dataclass(frozen=True)
class CopyCommittedHandCard(Effect):
    play_id: int
    player_id: int
    source_id: int

    def __post_init__(self):
        _integer(self.play_id,'original committed hand play',1)
        _player(self.player_id);_integer(self.source_id,'committed-copy effect source',1)


def original_hand_material(r,play_id):
    """Reuse the unique existing acceptance proof; never infer a later face."""
    _integer(play_id,'original copied hand play',1)
    from .play_history import play_record
    from .paid_hand_acceptance import FinishPaidHandAcceptance,bind_live
    from .spell_acceptance import FinishSpellAcceptance,_bind_live
    record=play_record(r.state,play_id)
    proofs=tuple(work for work in r._work_queue if type(work) in (FinishPaidHandAcceptance,FinishSpellAcceptance)
        and work.play_id==play_id)
    if len(proofs)!=1:
        raise ResolutionError('Original hand copy requires its one active payment acceptance proof')
    proof=proofs[0]
    if type(proof) is FinishPaidHandAcceptance:
        bind_live(r.state,proof,r.registry);original=proof.proof.payment_state
    else:
        _bind_live(r.state,proof,r.registry);original=proof.cost_proof.payment_state
    source=original.entities.get(record.source_id)
    if (source is None or source.zone!=Zone.HAND or source.controller!=record.player_id or
            source.card_id!=record.card_id or source.kind!=record.kind or source.hand_entry_id!=record.hand_entry_id):
        raise ResolutionError('Original hand copy lost its actual submitted physical source')
    from .copy_materials import CapturedCardCopyMaterial
    return CapturedCardCopyMaterial.capture(original,source)


def copy_committed(r,request):
    request.__post_init__()
    if request.source_id not in r.state.entities:raise ResolutionError('Committed copy lost its allocated effect source')
    r.player(request.player_id)
    material=original_hand_material(r,request.play_id)
    return (CopyCard(material,request.player_id,mode='current',source_id=request.source_id,cost=CostSpec(set_to=0)),)


def register(mechanics):
    mechanics.register(InstallDeckSecrets,install)
    mechanics.register(CopyCommittedHandCard,copy_committed)
