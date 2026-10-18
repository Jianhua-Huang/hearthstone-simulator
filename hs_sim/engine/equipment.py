"""Weapon slots, derived hero contribution and intrinsic attack wear."""
from dataclasses import dataclass
from .effects import Effect, _integer, _source
from .errors import ResolutionError
from .lifecycle import attachment_id, refresh_entity
from .model import CardType, Enchantment, EquippedWeaponReference, Event, Keyword, Zone, _int


WEAPON_KEYWORDS = {Keyword.WINDFURY, Keyword.MEGA_WINDFURY, Keyword.LIFESTEAL, Keyword.POISONOUS,
                   Keyword.IMMUNE_WHILE_ATTACKING}


@dataclass(frozen=True)
class SetWeaponAttackForTurn(Effect):
    weapon: EquippedWeaponReference
    attack: int
    expires_turn: int
    source_id: int | None = None

    def __post_init__(self):
        if type(self.weapon) is not EquippedWeaponReference:
            raise ValueError('Weapon Attack set requires an original equipped reference')
        self.weapon.__post_init__()
        _integer(self.attack,'weapon Attack set',0)
        _integer(self.expires_turn,'weapon Attack expiry',1)
        _source(self.source_id)


def set_weapon_attack_for_turn(r,effect):
    from .resolver import validate_attachment_source
    effect.__post_init__()
    validate_attachment_source(r,effect.source_id,effect.expires_turn)
    if effect.expires_turn != r.state.turn:
        raise ResolutionError('Weapon this-turn set must retain its actual current turn')
    ref=effect.weapon
    if r.registry.card(ref.card_id).kind != CardType.WEAPON:
        raise ResolutionError('Weapon Attack reference requires a weapon face')
    weapon=r.state.entities.get(ref.entity_id)
    if (weapon is None or not weapon.active or weapon.doomed or weapon.durability<=0 or
            (weapon.kind,weapon.zone,weapon.controller,weapon.card_id,weapon.zone_epoch,weapon.entered_order) !=
            (CardType.WEAPON,Zone.WEAPON,ref.player_id,ref.card_id,ref.zone_epoch,ref.entered_order) or
            r.player(ref.player_id).weapon_id != ref.entity_id):
        r.emit('effect_skipped',target_id=ref.entity_id,effect='SetWeaponAttackForTurn',reason='stale_equipped_weapon')
        return ()
    weapon.enchantments.append(Enchantment(attachment_id(r.state),source_id=effect.source_id,
        set_attack=effect.attack,expires_turn=effect.expires_turn,label='weapon_attack_set'))
    r.refresh_auras()
    r.emit('weapon_changed',source_id=effect.source_id,target_id=weapon.id,
           attack=weapon.attack,durability=weapon.durability)


def equipped_weapon(state, player):
    """The original live equipment predicate, independent of Attack or turn."""
    weapon = state.entities.get(player.weapon_id)
    return weapon if weapon is not None and weapon.durability > 0 and not weapon.doomed else None


def refresh_equipment(state):
    for entity in state.entities.values():
        entity.weapon_attack = 0
        entity.weapon_keywords = set()
        refresh_entity(entity)
    player = state.players[state.active_player]
    weapon = equipped_weapon(state, player)
    if weapon is not None:
        hero = state.entities[player.hero_id]
        hero.weapon_attack = weapon.attack
        hero.weapon_keywords = weapon.keywords & WEAPON_KEYWORDS
        refresh_entity(hero)


def equip_entity(r, entity, *, controller_id=None):
    player = r.player(entity.controller if controller_id is None else controller_id)
    if r.registry.card(entity.card_id).kind != CardType.WEAPON:
        raise ResolutionError('Equip requires a weapon definition')
    if player.weapon_id is not None:
        old = r.state.entities[player.weapon_id]
        from .death_causes import mark
        mark(r, old, 'replaced', 'EquipWeapon', entity.id)
        record = r.record_death(old, 0)
        r.move(old, Zone.GRAVEYARD)
        r.removed_weapons.append((record, 'replaced'))
    r.move(entity, Zone.WEAPON, controller_id=controller_id)
    r.refresh_auras()
    r.emit('weapon_equipped', source_id=entity.id, target_id=entity.id, player_id=player.id)


def create_equipped_weapon(r, player_id, card_id):
    """Ordinary equipment creation with its actual result available before reactions."""
    if r.registry.card(card_id).kind != CardType.WEAPON:
        raise ResolutionError('EquipWeapon requires a weapon definition')
    entity = r.create_entity(player_id, card_id, Zone.GRAVEYARD)
    equip_entity(r, entity)
    return entity


def equip_weapon(r, effect):
    create_equipped_weapon(r,effect.player_id,effect.card_id)


def transfer_weapon(r,effect):
    from .zones import source_exists
    effect.__post_init__(); source_exists(r,effect.source_id)
    ref=effect.weapon
    if r.registry.card(ref.card_id).kind!=CardType.WEAPON:
        raise ResolutionError('Weapon transfer reference requires a weapon definition')
    entity=r.state.entities.get(ref.entity_id)
    if (entity is None or not entity.active or entity.zone!=Zone.WEAPON or entity.kind!=CardType.WEAPON
            or entity.durability<=0 or entity.doomed
            or (entity.controller,entity.card_id,entity.zone_epoch,entity.entered_order)!=
                (ref.player_id,ref.card_id,ref.zone_epoch,ref.entered_order)
            or r.player(ref.player_id).weapon_id!=entity.id):
        r.emit('effect_skipped',target_id=ref.entity_id,effect='TransferWeapon',reason='stale_equipped_weapon'); return ()
    if entity.controller==effect.player_id: return ()
    owner=entity.owner
    equip_entity(r,entity,controller_id=effect.player_id)
    r.emit('weapon_transferred',source_id=effect.source_id,target_id=entity.id,player_id=effect.player_id,amount=1,
        weapon=ref.payload(),owner_id=owner,new_zone_epoch=entity.zone_epoch,new_entered_order=entity.entered_order)
    return ()


def weapon_transfer_reference(event):
    if event is None: return None
    if type(event) is not Event: raise ValueError('Weapon transfer requires an Event')
    if event.kind!='weapon_transferred': return None
    data=dict(event.data)
    if len(data)!=len(event.data) or set(data)!={'weapon','owner_id','new_zone_epoch','new_entered_order'}:
        raise ValueError('Weapon transfer lost its complete original envelope')
    raw=data['weapon']
    if type(raw) is not tuple or any(type(x) is not tuple or len(x)!=2 or type(x[0]) is not str for x in raw):
        raise ValueError('Weapon transfer requires immutable reference fields')
    values=dict(raw)
    if len(values)!=len(raw) or set(values)!={'entity_id','player_id','card_id','zone_epoch','entered_order'}:
        raise ValueError('Weapon transfer lost original reference fields')
    ref=EquippedWeaponReference(**values)
    if type(event.player_id) is not int or event.player_id not in (1,2) or event.player_id==ref.player_id:
        raise ValueError('Weapon transfer must change its original controller')
    if type(data['owner_id']) is not int or data['owner_id'] not in (1,2):
        raise ValueError('Weapon transfer requires its original owner')
    _int(event.target_id,'weapon transfer target',1); _int(event.amount,'weapon transfer amount',1)
    _int(data['new_zone_epoch'],'new weapon epoch',1); _int(data['new_entered_order'],'new weapon installation',1)
    if event.source_id is not None: _int(event.source_id,'weapon transfer source',1)
    if (event.target_id!=ref.entity_id or event.amount!=1 or data['new_zone_epoch']!=ref.zone_epoch+1
            or data['new_entered_order']<=ref.entered_order):
        raise ValueError('Weapon transfer changed original physical installation operands')
    return ref


def validate_weapon_transfer_events(state,registry,events):
    from .hero_health_history import effective_events
    effective=effective_events(events)
    for index,event in enumerate(effective):
        ref=weapon_transfer_reference(event)
        if ref is None: continue
        data=dict(event.data); entity=state.entities.get(ref.entity_id)
        if (registry.card(ref.card_id).kind!=CardType.WEAPON or entity is None or entity.owner!=data['owner_id']
                or entity.zone_epoch<data['new_zone_epoch'] or data['new_entered_order']>=state.next_order):
            raise ValueError('Weapon transfer borrowed unknown/future or different original material')
        if event.source_id is not None and event.source_id not in state.entities:
            raise ValueError('Weapon transfer borrowed an unknown physical source')
        prior=next((old for old in reversed(effective[:index]) if old.kind=='weapon_equipped' and old.action==event.action
            and (old.target_id,old.player_id)==(ref.entity_id,event.player_id)),None)
        if prior is None: raise ValueError('Weapon transfer lost its original physical equipment event')


def modify_weapon(r, effect, *, pending_events=None):
    reference = effect.target_id if type(effect.target_id) is EquippedWeaponReference else None
    if reference is not None:
        r.registry.card(reference.card_id)
        weapon = r.state.entities.get(reference.entity_id)
        if (weapon is None or not weapon.active or weapon.zone != Zone.WEAPON or weapon.kind != CardType.WEAPON
                or weapon.durability <= 0 or weapon.doomed or r.player(reference.player_id).weapon_id != weapon.id
                or (weapon.controller, weapon.card_id, weapon.zone_epoch, weapon.entered_order) !=
                (reference.player_id, reference.card_id, reference.zone_epoch, reference.entered_order)):
            r.emit('effect_skipped', target_id=reference.entity_id, effect='ModifyWeapon', reason='stale_equipped_weapon')
            return ()
    else:
        weapon = r.state.entities.get(effect.target_id)
    if weapon is None or weapon.zone != Zone.WEAPON:
        r.stale(effect, effect.target_id)
        return
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Weapon modifier source does not exist')
    if effect.attack:
        weapon.enchantments.append(Enchantment(attachment_id(r.state), source_id=effect.source_id,
                                               attack=effect.attack, label='weapon_buff'))
    weapon.durability += effect.durability
    from .death_causes import dying, mark
    if dying(weapon): mark(r, weapon, 'durability', 'ModifyWeapon', effect.source_id)
    r.refresh_auras()
    data = dict(source_id=effect.source_id, target_id=weapon.id,
                attack=weapon.attack, durability=weapon.durability)
    if pending_events is None:
        r.emit('weapon_changed', **data)
    else:
        pending_events.append(('weapon_changed', data))


def finish_exchange(r, combat):
    from .weapon_wear import commit
    commit(r,combat)
    from .hero_attack_history import complete
    complete(r,combat)
    from .character_attacks import complete as complete_character_attack
    complete_character_attack(r,combat)
    r.emit('attack_finished', source_id=combat.attacker_id, target_id=combat.defender_id)


def validate_exchange(r, combat):
    if combat is None:
        return
    from .hero_attack_history import require_link
    require_link(r.state,combat.attacker_id,combat.defender_id,False,combat.combat_relation,combat.hero_attack)
    from .character_attacks import require_link as require_character_link
    require_character_link(r.state, combat)
    attacker = r.live_character(combat.attacker_id)
    defender = r.live_character(combat.defender_id)
    from .combat import combat_relation_matches
    if attacker is None or defender is None or not combat_relation_matches(attacker, defender, combat.combat_relation):
        raise ResolutionError('Invalid combat exchange')
    if combat.weapon_id is not None:
        weapon = r.state.entities.get(combat.weapon_id)
        if (attacker.zone != Zone.HERO or r.player(attacker.controller).weapon_id != combat.weapon_id
                or weapon is None or weapon.zone != Zone.WEAPON or weapon.durability <= 0):
            raise ResolutionError('Invalid combat weapon')


def total_hero_attack(state, player):
    """Attack including an equipped weapon even while it is inactive off-turn."""
    hero = state.entities[player.hero_id]
    weapon = equipped_weapon(state, player)
    return hero.attack - hero.weapon_attack + (weapon.attack if weapon is not None else 0)
