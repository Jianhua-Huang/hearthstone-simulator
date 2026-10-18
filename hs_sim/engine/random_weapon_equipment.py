"""Two ordinary random equipment deliveries with a bonus bound to the first result."""
from dataclasses import dataclass
from .effects import Effect,EquipWeapon,ModifyWeapon,_behavior,_integer,_player
from .equipment import create_equipped_weapon
from .model import CardType,EquippedWeaponReference
from .pools import GenerateFromPool,PoolQuery,generation_candidates,sample_candidates

QUERY=PoolQuery(kinds=(CardType.WEAPON,),collectible=True)


@dataclass(frozen=True)
class EquipRandomWeapons(Effect):
    player_id: int
    source_id: int
    pool_id: str = 'constructed.cards'
    own_attack: int = 1
    own_durability: int = 1
    def __post_init__(self):
        _player(self.player_id);_integer(self.source_id,'random equipment source',1)
        _behavior(self.pool_id);_integer(self.own_attack,'original weapon attack bonus',0)
        _integer(self.own_durability,'original weapon durability bonus',0)


def equip_random_weapons(r,effect):
    effect.__post_init__()
    players=(effect.player_id,3-effect.player_id)
    pools=tuple(generation_candidates(r,GenerateFromPool(pid,effect.pool_id,QUERY,
        source_id=effect.source_id))for pid in players)
    selected=tuple(sample_candidates(r.game._rng,rows,1,replacement=True)for rows in pools)
    original=None
    if selected[0]:
        entity=create_equipped_weapon(r,players[0],selected[0][0])
        original=EquippedWeaponReference.capture(entity)
    tail=[]
    if selected[1]:tail.append(EquipWeapon(players[1],selected[1][0]))
    if original is not None:
        tail.append(ModifyWeapon(original,attack=effect.own_attack,durability=effect.own_durability,
            source_id=effect.source_id))
    return tuple(tail)


def register(mechanics):mechanics.register(EquipRandomWeapons,equip_random_weapons)
