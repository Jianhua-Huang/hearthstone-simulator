"""Finite original hand-spell counter returns and same-cost replacement casts."""
from dataclasses import dataclass
from .allocation_facts import SourceAllocationFact,validate_allocation
from .effects import Effect,_integer
from .interrupts import find_window,mark_counter,announce_counter
from .model import CardType,Zone
from .play_history import play_record


def pending_spell(state,event,player_id):
    if event is None or event.kind!='card_committed' or event.player_id==player_id:return None
    data=dict(event.data);window=find_window(state,data.get('window_id'))
    if window is None or window.kind!='spell' or window.countered:return None
    play=play_record(state,window.play_id);card=state.entities[window.source_id]
    if (event.source_id,event.player_id,data.get('play_id'))!=(play.source_id,play.player_id,play.id):
        raise ValueError('Spell Secret lost its original hand notification')
    if (play.kind!=CardType.SPELL or play.completed or play.interrupted or play.submitted_cost is None or
            (card.card_id,card.controller,card.zone,card.zone_epoch)!=(
                play.card_id,play.player_id,Zone.GRAVEYARD,play.submitted_cost.zone_epoch+1)):
        return None
    return window,play,card


def validate(state,registry,effect):
    effect.__post_init__()
    validate_allocation(state,registry,effect.card);validate_allocation(state,registry,effect.source)
    window=find_window(state,effect.window_id);play=play_record(state,effect.play_id)
    if (window is None or window.kind!='spell' or window.play_id!=play.id or
            (window.source_id,window.player_id)!=(effect.card.entity_id,effect.card.controller) or
            (play.source_id,play.card_id,play.player_id,play.kind)!=(
                effect.card.entity_id,effect.card.card_id,effect.card.controller,CardType.SPELL) or
            play.completed or play.interrupted or play.spell_acceptance_closed or play.submitted_cost is None or
            effect.card.zone_epoch!=play.submitted_cost.zone_epoch+1 or
            registry.card(effect.source.card_id).secret is None):
        raise ValueError('Counter replacement lost its original physical hand-spell scope')
    return window,play


@dataclass(frozen=True)
class CounterReturnSpell(Effect):
    window_id:int
    play_id:int
    card:SourceAllocationFact
    source:SourceAllocationFact

    def __post_init__(self):
        _integer(self.window_id,'original spell window',1);_integer(self.play_id,'original hand spell play',1)
        for value in (self.card,self.source):
            if type(value)is not SourceAllocationFact:raise ValueError('Complete original spell allocation required')
            value.__post_init__()
            if value.kind!=CardType.SPELL or value.zone!=Zone.GRAVEYARD:
                raise ValueError('Spell counter requires its original played/revealed graveyard residents')
        if self.card.controller==self.source.controller:raise ValueError('Spell Secret requires its opposing caster')

    def validate_in_state(self,state,registry):validate(state,registry,self)


@dataclass(frozen=True)
class CounterReplaceSpell(CounterReturnSpell):
    pass


def accept(r,effect):
    window,play=validate(r.state,r.registry,effect);card=r.state.entities[effect.card.entity_id];fact=effect.card
    if (card.owner,card.controller,card.card_id,card.kind,card.zone,card.zone_epoch,card.entered_order)!=(
            fact.owner,fact.controller,fact.card_id,fact.kind,fact.zone,fact.zone_epoch,fact.entered_order):
        r.emit('zone_target_skipped',target_id=card.id,reason='original_spell_departed');return None
    original=mark_counter(r,window.id,('spell',))
    if original is None:return None
    announce_counter(r,original)
    return play,card


def return_spell(r,effect):
    accepted=accept(r,effect)
    if accepted is None:return ()
    play,card=accepted
    from .hand_returns import deliver
    return deliver(r,card,effect.source.entity_id,cost_delta=1,recipient_id=card.owner,preserve_spell_material=True)


def replace_spell(r,effect):
    accepted=accept(r,effect)
    if accepted is None:return ()
    play,card=accepted
    from .pools import PoolQuery
    from .spell_history import CastFromPool
    return (CastFromPool(play.player_id,'constructed.cards',PoolQuery(kinds=(CardType.SPELL,),collectible=True,
        min_cost=play.cost,max_cost=play.cost),source_id=effect.source.entity_id,targeting='random',choices='random'),)


def register(mechanics):
    mechanics.register(CounterReturnSpell,return_spell)
    mechanics.register(CounterReplaceSpell,replace_spell)
