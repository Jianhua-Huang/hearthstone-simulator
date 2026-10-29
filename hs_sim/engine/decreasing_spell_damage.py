"""Fresh random minion hits with a serializable, decreasing spell number.

Current Spell Damage is counted before ordinary health rules on each step.
Multiplier/bonus-change ordering is a local policy pending CN calibration.
"""
from dataclasses import dataclass,replace

from .effects import Damage,Effect,_integer,_player,_source
from .errors import ResolutionError
from .health_rules import spell_bonus
from .model import CardType,DamageKind
from .spell_casts import cast_record


@dataclass(frozen=True)
class DecreasingRandomSpellDamage(Effect):
    player_id:int
    cast_id:int
    source_id:int
    base_amount:int=3
    step:int=0

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.cast_id,'original decreasing CAST',1)
        _integer(self.source_id,'original decreasing source',1)
        _integer(self.base_amount,'initial decreasing spell number',1)
        _integer(self.step,'decreasing step',0)


def apply(r,effect):
    effect.__post_init__()
    cast=cast_record(r.state,effect.cast_id)
    card=r.registry.card(cast.card_id)
    if (card.kind!=CardType.SPELL or (cast.player_id,cast.source_id)!=(effect.player_id,effect.source_id) or
            not cast.payload_started or cast.failure is not None or effect.source_id not in r.state.entities):
        raise ResolutionError('Decreasing damage requires its actual started original spell CAST')
    amount=effect.base_amount+spell_bonus(r.state,effect.player_id,r.registry,
        card.spell_school,cast_id=cast.id)-effect.step
    if amount<=0:return()
    candidates=tuple(sorted(eid for eid in r.player(3-effect.player_id).board
        if (e:=r.live_character(eid))is not None and e.kind==CardType.MINION and e.health>0 and not e.doomed))
    if not candidates:
        r.emit('random_choice_skipped',source_id=effect.source_id,reason='no_candidates')
        return()
    target=r.game._rng.choice(candidates)
    r.emit('random_choice',source_id=effect.source_id,target_id=target,candidates=candidates)
    # The current bonus is already included. Ordinary SPELL routing, health
    # replacements, multipliers, reactions and death checkpoints still apply.
    return(Damage(target,amount,effect.source_id,DamageKind.SPELL,spell_bonus_multiplier=0),
        replace(effect,step=effect.step+1))


def register(mechanics):mechanics.register(DecreasingRandomSpellDamage,apply)
