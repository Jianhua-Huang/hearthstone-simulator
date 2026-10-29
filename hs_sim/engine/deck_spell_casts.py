"""A real physical deck cast, with stored cost filtering and shared target selection."""
from dataclasses import dataclass
from .automatic_targets import PreferredMinionTarget, validate_preferred_source
from .costs import local_cost
from .effects import Effect, _integer, _player
from .model import CardType, Event, PlayerEffect, Zone
from .spell_casts import CastStoredSpell
from .zones import CardReference, source_exists


@dataclass(frozen=True)
class CastRandomDeckSpell(Effect):
    player_id: int
    max_cost: int | None
    source_id: int
    target_preference: PreferredMinionTarget | None = None
    player_effect: PlayerEffect | None = None
    owner_end: Event | None = None

    def __post_init__(self):
        _player(self.player_id)
        if self.player_effect is None:
            _integer(self.max_cost, 'deck spell cost ceiling', 0)
            if self.owner_end is not None:raise ValueError('Ordinary deck cast cannot borrow an Objective end')
        elif (type(self.player_effect)is not PlayerEffect or self.max_cost is not None or
                self.target_preference is not None or self.player_effect.source_id!=self.source_id or
                type(self.owner_end)is not Event or self.owner_end.kind!='turn_ended'or self.owner_end.player_id!=self.player_id):
            raise ValueError('Objective deck cast requires its original instance and unrestricted random targets')
        else:self.player_effect.__post_init__()
        _integer(self.source_id, 'deck spell causing source', 1)
        if self.target_preference is not None and type(self.target_preference) is not PreferredMinionTarget:
            raise ValueError('Deck spell preference requires its original minion')
        validate_preferred_source(self.target_preference, self.source_id)

    def validate_in_state(self,state,registry,events=None):
        self.__post_init__()
        if self.player_effect is None:return
        from .player_effects import ConsumePlayerEffect,validate_consumption
        instance=self.player_effect;spec=registry.player_effect(instance.spec_id);source=registry.card(instance.source_card_id)
        validate_consumption(state,registry,ConsumePlayerEffect(self.player_id,instance))
        if sum(row.end_event==self.owner_end.sequence and row.player_id==self.player_id for row in state.owner_turn_history)!=1:
            raise ValueError('Objective deck cast lost its original natural owner end')
        if events is not None:
            from .hero_health_history import effective_events
            if sum(event==self.owner_end for event in effective_events(events))!=1:
                raise ValueError('Objective deck cast changed its actual original end event')
        if (source.kind!=CardType.SPELL or source.ongoing_effect_id!=spec.id or spec.card_id!=source.id or
                spec.kind!='objective' or spec.duration!=3 or spec.tick_event!='turn_ended' or
                spec.tick_player!='controller' or instance.remaining_turns not in (1,2,3)):
            raise ValueError('Deck cast lost its original three-owner-end Objective declaration')


def cast_matching(r, effect):
    effect.validate_in_state(r.state,r.registry,r.game.events); source_exists(r, effect.source_id)
    if effect.player_effect is not None and not r.ending_turn:
        raise ValueError('Objective deck cast cannot execute outside its accepted natural end')
    validate_preferred_source(effect.target_preference, effect.source_id, r.state)
    candidates = []
    for eid in r.player(effect.player_id).deck:
        entity = r.state.entities[eid]
        definition = r.registry.card(entity.card_id)
        if (entity.zone == Zone.DECK and entity.controller == effect.player_id and
                definition.kind == CardType.SPELL and
                (effect.max_cost is None or max(0, local_cost(entity)[0]) <= effect.max_cost)and
                (effect.player_effect is None or definition.id!=effect.player_effect.source_card_id)):
            candidates.append(CardReference.capture(entity))
    if not candidates:
        return ()
    selected = r.game._rng.choice(candidates)
    return (CastStoredSpell(selected, effect.player_id, effect.source_id,
        target_preference=effect.target_preference),)


def register(mechanics):
    mechanics.register(CastRandomDeckSpell, cast_matching)
