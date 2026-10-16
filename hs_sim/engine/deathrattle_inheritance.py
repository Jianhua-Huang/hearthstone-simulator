"""Gain complete physical Deathrattles from this turn's friendly minion deaths."""
from dataclasses import dataclass, replace

from .effects import Effect,_player
from .lifecycle import attachment_id
from .model import CardType, Zone
from .sacrifice import MinionReference, live_minion, reference_value
from .summon_sources import DeathQuery, death_candidates


def inherited(original, *, identity, source_id, grant_card_id, death_id):
    """Copy payload, not the old attachment's residence, deadline or fusion group."""
    return replace(original, id=identity, origin='granted', source_id=source_id,
        deathrattle_grant_card_id=grant_card_id, expires_turn=None,
        remove_on_silence=True, consumed=False, magnetic_id=None,
        deathrattle_inherited_from=(death_id, original.id))


def validate_ability(state, registry, ability):
    link=ability.deathrattle_inherited_from
    if link is None:return
    ability.__post_init__()
    death_id,original_id=link
    if death_id>len(state.death_history):raise ValueError('Inherited Deathrattle has no original death')
    death=state.death_history[death_id-1]
    original=next((a for a in death.abilities if a.id==original_id),None)
    if (death.id!=death_id or death.zone!=Zone.BOARD or registry.card(death.card_id).kind!=CardType.MINION
            or original is None or original.kind!='deathrattle' or original.consumed
            or original.id>=ability.id):
        raise ValueError('Inherited Deathrattle lost its original physical declaration')
    expected=inherited(original,identity=ability.id,source_id=ability.source_id,
        grant_card_id=ability.deathrattle_grant_card_id,death_id=death_id)
    if ability!=expected:raise ValueError('Inherited Deathrattle changed its frozen payload')


@dataclass(frozen=True)
class GainDeathrattlesFromDeathsThisTurn(Effect):
    player_id: int
    beneficiary: MinionReference

    def __post_init__(self):_player(self.player_id);reference_value(self.beneficiary)

    def validate_in_state(self,state):
        self.__post_init__();ref=self.beneficiary;entity=state.entities.get(ref.entity_id)
        if entity is None or ref.zone_epoch>entity.zone_epoch or ref.entered_order>=state.next_order:
            raise ValueError('Deathrattle inheritance borrowed an unknown or future residence')


def gain(r,effect):
    effect.validate_in_state(r.state)
    entity=live_minion(r.state,effect.beneficiary)
    if entity is None:r.stale(effect,effect.beneficiary.entity_id);return ()
    deaths=death_candidates(r.state,r.registry,effect.player_id,
        DeathQuery(min_turn=r.state.turn,max_turn=r.state.turn),entity.id)
    # Structural declarations survive a global trigger prohibition. Conditions
    # belong to later actual invocations, never to the inheritance query.
    materials=tuple((d,a)for d in deaths for a in d.abilities
        if a.kind=='deathrattle'and not a.consumed)
    from .deathrattles import validate_ability as validate_deathrattle
    for _,ability in materials:validate_deathrattle(r.state,r.registry,ability)
    grants=[]
    for death,ability in materials:
        grant=inherited(ability,identity=attachment_id(r.state),source_id=entity.id,
            grant_card_id=entity.card_id,death_id=death.id)
        validate_ability(r.state,r.registry,grant);grants.append(grant)
    entity.abilities.extend(grants)
    r.refresh_auras()
    for ability in grants:
        r.emit('ability_granted',target_id=entity.id,source_id=entity.id,
            ability_id=ability.id,ability_kind='deathrattle')
    return ()


def register(mechanics):mechanics.register(GainDeathrattlesFromDeathsThisTurn,gain)
