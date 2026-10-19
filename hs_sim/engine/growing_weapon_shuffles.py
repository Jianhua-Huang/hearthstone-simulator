"""One original dead weapon reshuffles with its own persistent growth."""
from dataclasses import dataclass,replace
from .allocation_facts import SourceAllocationFact,validate_allocation
from .effects import Buff,Effect,_integer,_player,_source
from .errors import ResolutionError
from .lifecycle import reset_to_definition
from .model import CardType,DeathRecord,Zone

GROWTH_LABEL='weapon_self_shuffle_growth'


@dataclass(frozen=True)
class ShuffleGrowingWeapon(Effect):
    weapon:SourceAllocationFact
    death:DeathRecord
    player_id:int
    attack_growth:int
    source_id:int|None=None

    def __post_init__(self):
        _player(self.player_id);_source(self.source_id);_integer(self.attack_growth,'weapon shuffle growth',0)
        if type(self.weapon)is not SourceAllocationFact:raise ValueError('Weapon shuffle requires its original allocation')
        self.weapon.__post_init__();fact=self.weapon
        if fact.kind!=CardType.WEAPON or fact.controller!=self.player_id or fact.zone!=Zone.GRAVEYARD:
            raise ValueError('Weapon shuffle requires its original controller graveyard residence')
        if type(self.death)is not DeathRecord:raise ValueError('Dead weapon shuffle requires its complete original death')
        self.death.__post_init__();d=self.death
        if(d.zone!=Zone.WEAPON or(fact.entity_id,fact.card_id,fact.owner,fact.controller,fact.zone_epoch,fact.entered_order)!=
                (d.entity_id,d.card_id,d.owner,d.controller,d.cause.target_zone_epoch+1,d.cause.target_entered_order)):
            raise ValueError('Weapon shuffle allocation differs from its original equipment death')


def validate_request(state,registry,request):
    request.__post_init__();validate_allocation(state,registry,request.weapon)
    if registry.card(request.weapon.card_id).kind!=CardType.WEAPON:raise ValueError('Weapon shuffle requires an actual weapon definition')
    if request.source_id is not None and request.source_id not in state.entities:raise ValueError('Weapon shuffle issuer is unknown')
    if next((d for d in state.death_history if d.id==request.death.id),None)!=request.death:
        raise ValueError('Weapon shuffle lost its complete original death record')


def permanent_attack(entity):
    return sum(e.attack for e in entity.enchantments if e.label==GROWTH_LABEL)


def shuffle(r,request):
    try:validate_request(r.state,r.registry,request)
    except ValueError as e:raise ResolutionError(str(e))from e
    fact=request.weapon;entity=r.state.entities[fact.entity_id]
    if ((entity.id,entity.card_id,entity.kind,entity.owner,entity.controller,entity.zone,entity.zone_epoch,entity.entered_order)!=
            (fact.entity_id,fact.card_id,fact.kind,fact.owner,fact.controller,fact.zone,fact.zone_epoch,fact.entered_order)):
        r.stale(request,entity.id);return
    growth=permanent_attack(entity)+request.attack_growth
    reset_to_definition(r.state,entity,r.registry.card(fact.card_id),r.registry)
    if growth:
        from .resolver import _buff_to
        enchantment=_buff_to(r,Buff(entity.id,growth,source_id=request.source_id),entity,notify=False)
        entity.enchantments[-1]=replace(enchantment,label=GROWTH_LABEL)
    player=r.player(request.player_id)
    position=r.game._rng.randrange(len(player.deck)+1)
    r.move(entity,Zone.DECK,position)
    r.refresh_auras()
    r.emit('card_shuffled',source_id=request.source_id,target_id=entity.id,player_id=player.id,
        position=position,_deck_insertion_mode='random')


def register(mechanics):mechanics.register(ShuffleGrowingWeapon,shuffle)
