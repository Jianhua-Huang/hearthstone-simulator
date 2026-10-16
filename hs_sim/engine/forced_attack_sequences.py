"""Original-residence attacker, current enemy minions, ordinary forced combat."""
from dataclasses import dataclass
from .board_presence import resolve_board_presence
from .effects import Effect,ForceAttack,_player,_source
from .model import BoardPresenceReference,CardType

@dataclass(frozen=True)
class AttackRandomEnemyMinion(Effect):
    attacker:BoardPresenceReference
    player_id:int
    source_id:int|None=None

    def __post_init__(self):
        if type(self.attacker)is not BoardPresenceReference:raise ValueError('Random enemy attack requires its original board residence')
        self.attacker.__post_init__();_player(self.player_id);_source(self.source_id)

    def validate_in_state(self,state):
        self.__post_init__()
        if self.attacker.entity_id not in state.entities or self.attacker.presence_id>=state.next_order:
            raise ValueError('Random enemy attack borrowed an unknown or future residence')
        if self.source_id is not None and self.source_id not in state.entities:
            raise ValueError('Random enemy attack has an unknown original source')

def execute(r,effect):
    effect.validate_in_state(r.state)
    attacker=resolve_board_presence(r.state,effect.attacker)
    if attacker is None or not attacker.active or attacker.health<=0 or attacker.doomed or attacker.controller!=effect.player_id:
        r.stale(effect,effect.attacker.entity_id);return ()
    candidates=tuple(sorted(eid for eid in r.player(3-effect.player_id).board for entity in(r.state.entities[eid],)
        if entity.kind==CardType.MINION and entity.active and entity.health>0 and not entity.doomed
        and r.registry.card(entity.card_id).interactable is None))
    if not candidates:return ()
    defender=r.game._rng.choice(candidates)
    original=BoardPresenceReference.capture(r.state,defender)
    r.emit('random_choice',source_id=effect.source_id,target_id=attacker.id,defender_id=defender)
    return(ForceAttack(effect.attacker,original),)

def register(mechanics):mechanics.register(AttackRandomEnemyMinion,execute)
