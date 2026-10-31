"""Bind actual opposing hand gifts before publishing their ordinary acquisition."""
from dataclasses import dataclass
from .effects import AddToHand,Effect,_behavior,_integer,_player
from .hand_inspection import RememberHandForDeathrattle,remember
from .model import CardType,Zone
from .opening import announce_hand_card,create_hand_card
from .sacrifice import MinionReference,reference_value
from .zones import CardReference,source_exists


@dataclass(frozen=True)
class GiveRememberedHandMinions(Effect):
    player_id:int
    card_id:str
    source_id:int
    reference:MinionReference|None=None
    ability_ids:tuple[int,...]=()

    def __post_init__(self):
        _player(self.player_id);_behavior(self.card_id);_integer(self.source_id,'original hand-gift source',1)
        if type(self.ability_ids)is not tuple or len(set(self.ability_ids))!=len(self.ability_ids):
            raise ValueError('Hand gifts require their distinct original native memory abilities')
        for identity in self.ability_ids:_integer(identity,'original hand-gift ability',1)
        if self.reference is None:
            if self.ability_ids:raise ValueError('Hand gift memory requires an original board reference')
        else:
            reference_value(self.reference)
            if(self.reference.entity_id,self.reference.player_id)!=(self.source_id,self.player_id):
                raise ValueError('Hand gifts changed their original source or recipient side')

    def validate_in_state(self,state,registry):
        self.__post_init__()
        if self.source_id not in state.entities:raise ValueError('Hand gift source does not exist')
        if registry.card(self.card_id).kind!=CardType.MINION:raise ValueError('Remembered gifts require their complete actual minion face')
        if self.reference is not None:
            from .deathrattle_memory import validate_reference
            validate_reference(state,self.reference,self.ability_ids)


def give(r,request):
    request.validate_in_state(r.state,r.registry);source_exists(r,request.source_id)
    creation=AddToHand(3-request.player_id,request.card_id,request.source_id);created=[]
    # Both complete original gifts are bound before either notification runs.
    # Burned creations have no successful hand entry and are never remembered.
    for _ in range(2):
        r.charge();entity=create_hand_card(r,creation,defer_publication=True)
        if entity.zone==Zone.GRAVEYARD:
            # The original overflow witness is captured while this is still
            # the newest allocation. No successful hand entry is owed.
            announce_hand_card(r,creation,entity)
            continue
        created.append(entity)
        if entity.zone==Zone.HAND and request.reference is not None:
            remember(r,RememberHandForDeathrattle(CardReference.capture(entity),entity.hand_entry_id,request.reference,request.ability_ids))
    for entity in created:announce_hand_card(r,creation,entity)
    return()


def register(mechanics):mechanics.register(GiveRememberedHandMinions,give)
