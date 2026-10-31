"""Native weapon Deathrattles remember actual frozen minion killing blows."""
from dataclasses import dataclass,replace
from .model import CardType,EquippedWeaponReference,NativeDeathrattleSpec,Zone,_int

PROFILE=NativeDeathrattleSpec('weapon_kills')


@dataclass(frozen=True)
class RememberedWeaponKill:
    death_id:int
    weapon:EquippedWeaponReference

    def __post_init__(self):
        _int(self.death_id,'original weapon minion death',1)
        if type(self.weapon)is not EquippedWeaponReference:raise ValueError('Weapon kill requires its actual equipped residence')
        self.weapon.__post_init__()


def validate_link(state,registry,link):
    if type(link)is not RememberedWeaponKill:raise ValueError('Expected original typed weapon kill')
    link.__post_init__()
    from .summon_sources import death_record
    from .death_causes import validate_in_state
    death=death_record(state,link.death_id);validate_in_state(state,registry,death.cause)
    result=death.cause.health_result;ref=link.weapon
    if(registry.card(death.card_id).kind!=CardType.MINION or death.zone!=Zone.BOARD or
            death.cause.kind not in('damage','poison')or result is None or
            registry.card(ref.card_id).native_deathrattle!=PROFILE or
            (result.weapon_id,result.weapon_zone_epoch,result.weapon_entered_order)!=(ref.entity_id,ref.zone_epoch,ref.entered_order)or
            result.source_controller!=ref.player_id):
        raise ValueError('Native weapon memory differs from the original actual killing blow')
    return death


def remember_batch(r,records):
    """After allocating all deaths, before moving/capturing any dying carrier."""
    from .model import DeathrattleMemory
    additions={}
    for death in records.values():
        if r.registry.card(death.card_id).kind!=CardType.MINION:continue
        result=death.cause.health_result
        if death.cause.kind not in('damage','poison')or result is None or result.weapon_id is None:continue
        weapon=r.state.entities[result.weapon_id]
        if r.registry.card(weapon.card_id).native_deathrattle!=PROFILE:continue
        if(weapon.card_id,weapon.zone_epoch,weapon.entered_order,weapon.controller,weapon.zone)!=(
                r.registry.card(weapon.card_id).id,result.weapon_zone_epoch,result.weapon_entered_order,result.source_controller,Zone.WEAPON):
            from .registry import UnsupportedDefinitionError
            raise UnsupportedDefinitionError('Weapon left its killing-blow residence before the actual death commit')
        ref=EquippedWeaponReference(weapon.id,weapon.controller,weapon.card_id,weapon.zone_epoch,weapon.entered_order)
        link=RememberedWeaponKill(death.id,ref);validate_link(r.state,r.registry,link)
        for ability in weapon.abilities:
            memory=ability.deathrattle_memory
            if ability.kind=='deathrattle'and not ability.consumed and memory is not None and memory.spec==PROFILE:
                additions.setdefault(weapon.id,{}).setdefault(ability.id,[]).append(link)
    for eid,by_ability in additions.items():
        weapon=r.state.entities[eid];updated=[]
        for ability in weapon.abilities:
            links=by_ability.get(ability.id)
            if links:
                memory=replace(ability.deathrattle_memory,weapon_kills=(*ability.deathrattle_memory.weapon_kills,*links))
                ability=replace(ability,deathrattle_memory=memory)
            updated.append(ability)
        weapon.abilities=updated
        if eid in records:
            # Includes the final swing when weapon and victim die in one batch.
            old=records[eid];new=replace(old,abilities=tuple(updated));records[eid]=new
            pos=next(i for i,d in enumerate(r.state.death_history)if d.id==old.id)
            r.state.death_history[pos]=new
    return records


def from_dict(value):
    from .serialization import _row
    row=_row(value,RememberedWeaponKill)
    row['weapon']=EquippedWeaponReference(**_row(row['weapon'],EquippedWeaponReference))
    return RememberedWeaponKill(**row)


def register(mechanics):mechanics.register_payload_type(RememberedWeaponKill)
