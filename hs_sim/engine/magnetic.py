"""Position-selected hand play fusion, expressed as removable attachments."""
from dataclasses import dataclass, replace

from .errors import ResolutionError
from .lifecycle import attachment_id, refresh_entity
from .model import AbilityInstance, CardType, Enchantment, Keyword, MagneticRecord, Zone
from .effects import Effect, _integer


# Play/zone-entry mechanics do not become ongoing abilities on the host.
ENTRY_ABILITIES = frozenset(('on_play','battlecry','combo','on_use','on_launch','on_awaken','dormant_trigger','hand_progress','printed_attack_permit'))
ENTRY_KEYWORDS = frozenset((Keyword.TWINSPELL,Keyword.MINIATURIZE,Keyword.GIGANTIFY,Keyword.MINI,Keyword.GIGANTIC,Keyword.ECHO,Keyword.SHATTER,Keyword.SHATTERED,Keyword.HERALD,Keyword.COLOSSAL,Keyword.MAGNETIC,Keyword.COMBO,Keyword.OUTCAST,Keyword.FINALE,
    Keyword.MANATHIRST,Keyword.QUICKDRAW,Keyword.CORRUPT,Keyword.CORRUPTED,Keyword.INFUSE,Keyword.INFUSED))


def host_eligible(state, registry, source, host):
    spec=registry.card(source.card_id)
    if (source.kind!=CardType.MINION or Keyword.MAGNETIC not in source.keywords or not spec.magnetic_tribes or
            host.kind!=CardType.MINION or host.zone!=Zone.BOARD or host.controller!=source.controller or
            host.id not in state.players[source.controller].board or not host.active or host.doomed or host.health<=0):
        return False
    from .tribes import has_any_tribe
    return has_any_tribe(registry, host, spec.magnetic_tribes)


def host_at_position(state, registry, source, position):
    board=state.players[source.controller].board
    if type(position) is not int or not 0<=position<len(board):
        return None
    host=state.entities[board[position]]
    return host if host_eligible(state,registry,source,host) else None


def play_definition(state, registry, source, position, *, branch_id=None):
    from .play_history import play_definition as ordinary_definition
    definition=ordinary_definition(state,registry,source,branch_id=branch_id)
    if host_at_position(state,registry,source,position) is not None:
        return replace(definition,requires_target=False,targeting=None,target_rule='any_entity')
    return definition


def transferable_ability(ability):
    # One semantic predicate for merge and persistent attachment validation.
    return ability.kind not in ENTRY_ABILITIES and not (
        ability.kind == 'keyword' and ability.keyword in ENTRY_KEYWORDS)


def transferable_abilities(source):
    return tuple(a for a in source.abilities if transferable_ability(a))


def merge(r, source, host, play):
    from .tribes import tribe_changes
    if not host_eligible(r.state,r.registry,source,host) or source.zone!=Zone.PLAY or source.health<=0:
        raise ResolutionError('Magnetic play no longer has its hand source or live host in its pending play')
    abilities=transferable_abilities(source)
    # Active abilities have per-host semantic keys; do not silently replace one.
    existing={a.activation.id for a in host.abilities if a.kind=='activated'}
    if any(a.kind=='activated' and a.activation.id in existing for a in abilities):
        raise ResolutionError('Magnetic active ability conflicts with its host')
    group=len(r.state.magnetic_history)+1
    enchantment=Enchantment(attachment_id(r.state),source_id=source.id,attack=source.attack,
                            health=source.health,label='magnetic',magnetic_id=group)
    grants=[replace(a,id=attachment_id(r.state),origin='granted',source_id=source.id,
                    remove_on_silence=True,magnetic_id=group,
                    deathrattle_grant_card_id=source.card_id if a.kind=='deathrattle' else None) for a in abilities]
    host_tribes=tribe_changes(host)
    # This is storage for a consumed hand card, not a death or resurrection fact.
    r.move(source,Zone.GRAVEYARD)
    from .copy_materials import CapturedCardCopyMaterial
    material=CapturedCardCopyMaterial.capture(r.state,source)
    record=MagneticRecord(group,play.id,source.id,host.id,source.controller,source.card_id,host.card_id,
                          enchantment.attack,enchantment.health,enchantment.id,tuple(a.id for a in grants),
                          host_tribes,material)
    r.state.magnetic_history.append(record)
    host.enchantments.append(enchantment);host.abilities.extend(grants)
    from .timed_keywords import arm
    arm(r.state, host)
    refresh_entity(host)
    r.refresh_auras()
    return record


def validate_magnetic_history(state, registry):
    from .play_history import play_record
    if type(state.magnetic_history) is not list:
        raise ValueError('Magnetic history must be a list')
    previous_play=0
    for index,record in enumerate(state.magnetic_history,1):
        if type(record) is not MagneticRecord:
            raise ValueError('Expected magnetic record')
        record.__post_init__()
        play=play_record(state,record.play_id)
        material=record.source_material
        from .copy_materials import validate_captured_card_copy
        if material is None:
            raise ValueError('Magnetic history lost its original consumed card material')
        validate_captured_card_copy(state,registry,material)
        if ((material.origin.entity_id,material.origin.card_id,material.origin.controller,
                material.origin.kind,material.origin.zone)!=(record.source_id,record.card_id,
                    record.player_id,CardType.MINION,Zone.GRAVEYARD) or
                material.turn!=play.turn or material.action<play.action or
                any(a.magnetic_id is not None and a.magnetic_id>=record.id
                    for a in (*material.local.enchantments,*material.local.abilities))):
            raise ValueError('Magnetic material borrowed another source, future group or acceptance')
        source=registry.card(record.card_id);host=registry.card(record.host_card_id)
        if (record.id!=index or record.play_id<=previous_play or
                (record.source_id,record.target_id,record.player_id,record.card_id)!=
                (play.source_id,play.magnetic_target_id,play.player_id,play.card_id) or
                record.source_id not in state.entities or record.target_id not in state.entities or
                not source.magnetic_tribes or host.kind!=CardType.MINION or
                max((record.enchantment_id,*record.ability_ids))>=state.next_attachment_id):
            raise ValueError('Invalid magnetic provenance')
        from .tribes import tribe_state_for
        original = tribe_state_for(registry, host.id, record.host_tribe_changes)
        if original is None or not original.matches_any(source.magnetic_tribes):
            raise ValueError('Original magnetic host tribes do not satisfy the merge')
        if any(c.source_id is not None and c.source_id not in state.entities for c in record.host_tribe_changes):
            raise ValueError('Unknown original magnetic tribe grant source')
        if any(c.expires_turn is not None and c.expires_turn < play.turn for c in record.host_tribe_changes):
            raise ValueError('Original magnetic host retained expired tribe changes')
        previous_play=record.play_id
    if {p.id for p in state.play_history if p.minion_result == "magnetized"}!={m.play_id for m in state.magnetic_history}:
        raise ValueError('Magnetic play history is incomplete')


def public_magnetic(entity, state):
    groups=sorted({a.magnetic_id for a in (*entity.enchantments,*entity.abilities) if a.magnetic_id is not None})
    return [state.magnetic_history[i-1].card_id for i in groups]


def _groups(carrier):
    return tuple(sorted({a.magnetic_id for a in (*carrier.enchantments,*carrier.abilities)
        if a.magnetic_id is not None}))


def groups_for_context(context):
    if context.deathrattle is None:
        raise ResolutionError('Magnetic return requires its actual Deathrattle invocation')
    carrier=context.death if context.death is not None else context.source
    return _groups(carrier)


@dataclass(frozen=True)
class ReturnMagnetizedMechs(Effect):
    deathrattle_id: int
    groups: tuple[int,...]
    carrier_material: object | None = None

    def __post_init__(self):
        _integer(self.deathrattle_id,'Magnetic return invocation',1)
        if type(self.groups) is not tuple or self.groups!=tuple(sorted(set(self.groups))):
            raise ValueError('Magnetic return requires the complete ordered original groups')
        for i in self.groups:_integer(i,'original Magnetic group',1)
        if self.carrier_material is not None:
            from .copy_materials import CapturedCardCopyMaterial
            if type(self.carrier_material) is not CapturedCardCopyMaterial:
                raise ValueError('Active Magnetic return requires the complete original carrier material')
            self.carrier_material.__post_init__()
            if self.groups!=_groups(self.carrier_material.entity()):
                raise ValueError('Active Magnetic return changed the complete accepted carrier groups')

    @classmethod
    def capture(cls,context):
        groups=groups_for_context(context)
        from .copy_materials import CapturedCardCopyMaterial
        material=(None if context.death is not None else
            CapturedCardCopyMaterial.capture(context.state,context.source))
        return cls(context.deathrattle.id,groups,material)

    def validate_in_state(self,state):
        self.__post_init__()
        from .deathrattles import record
        row=record(state,self.deathrattle_id)
        if row.execution_order is None or row.completed or row.interrupted or row.capture.kind!=CardType.MINION:
            raise ValueError('Magnetic return lost its actual running minion Deathrattle')
        if any(i>len(state.magnetic_history) for i in self.groups):
            raise ValueError('Magnetic return borrowed an unknown or future group')
        if row.capture.death_id is not None:
            death=next((d for d in state.death_history if d.id==row.capture.death_id),None)
            expected=()if death is None else tuple(sorted({a.magnetic_id for a in(*death.enchantments,*death.abilities)
                if a.magnetic_id is not None}))
            if death is None or self.groups!=expected:
                raise ValueError('Magnetic return changed its original complete death groups')
            if self.carrier_material is not None:
                raise ValueError('Natural Magnetic return must use its original DeathRecord')
        else:
            material=self.carrier_material;capture=row.capture
            if material is None or (material.origin.entity_id,material.origin.kind)!=(
                    capture.carrier_id,CardType.MINION):
                raise ValueError('Active Magnetic return borrowed another carrier or lost its acceptance')
            fresh=capture.repeat_index>1 or capture.trigger_index>1
            if not fresh and (material.origin.card_id,material.origin.controller)!=(capture.card_id,capture.player_id):
                raise ValueError('First Magnetic return changed its original accepted carrier')
            if not capture.action<=material.action<=state.action_number or not capture.turn<=material.turn<=state.turn:
                raise ValueError('Active Magnetic return changed its acceptance clock')


def return_magnetized(r,effect):
    from .deathrattles import record
    from .copy_materials import validate_captured_card_copy
    from .tribes import has_any_tribe
    from .zones import CopyCard
    effect.validate_in_state(r.state);capture=record(r.state,effect.deathrattle_id).capture
    if effect.carrier_material is not None:
        validate_captured_card_copy(r.state,r.registry,effect.carrier_material)
    materials=[]
    for i in effect.groups:
        row=r.state.magnetic_history[i-1];material=row.source_material
        if material is None:raise ResolutionError('Magnetic return lacks its original full material')
        validate_captured_card_copy(r.state,r.registry,material)
        if has_any_tribe(r.registry,material.entity(),('mech',)):materials.append(material)
    # Complete immutable recipes are accepted before the first delivery. Hand
    # reset, intrinsic composition, capacity and origin use the shared copier.
    return tuple(CopyCard(m,capture.player_id,mode='base',source_id=capture.carrier_id)for m in materials)


def register(mechanics):
    mechanics.register(ReturnMagnetizedMechs,return_magnetized)
