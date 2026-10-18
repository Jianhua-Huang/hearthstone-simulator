"""Current equipment choices and in-place weapon faces with retained material."""
from dataclasses import dataclass
from .effects import ChoiceOption, Effect, RequestChoice, _behavior, _integer, _player, _source
from .errors import ResolutionError
from .model import CardType, EquippedWeaponReference, Zone


def current_weapon(state,ref):
    e=state.entities.get(ref.entity_id)
    return e if (e is not None and e.active and not e.doomed and e.durability>0 and
        (e.kind,e.zone,e.controller,e.card_id,e.zone_epoch,e.entered_order)==
        (CardType.WEAPON,Zone.WEAPON,ref.player_id,ref.card_id,ref.zone_epoch,ref.entered_order) and
        state.players[ref.player_id].weapon_id==e.id) else None


@dataclass(frozen=True)
class RefaceEquippedWeapon(Effect):
    weapon: EquippedWeaponReference
    card_id: str
    source_id: int | None = None
    def __post_init__(self):
        if type(self.weapon)is not EquippedWeaponReference:raise ValueError('Weapon face requires an original equipped reference')
        self.weapon.__post_init__();_behavior(self.card_id);_source(self.source_id)


@dataclass(frozen=True)
class RequestWeaponForm(Effect):
    player_id: int
    options: tuple[tuple[str,str],...]
    source_id: int
    weapon: EquippedWeaponReference | None = None
    def __post_init__(self):
        _player(self.player_id);_integer(self.source_id,'weapon form source',1)
        if type(self.options)is not tuple or not 2<=len(self.options)<=4:raise ValueError('Finite weapon forms required')
        for row in self.options:
            if type(row)is not tuple or len(row)!=2:raise ValueError('Weapon form must have card and label')
            for value in row:_behavior(value)
        if len({x[0]for x in self.options})!=len(self.options):raise ValueError('Weapon form IDs must be unique')
        if self.weapon is not None:
            if type(self.weapon)is not EquippedWeaponReference:raise ValueError('Expected original equipped reference')
            self.weapon.__post_init__()
            if self.weapon.player_id!=self.player_id:raise ValueError('Weapon form choice changed its original player')


def reface(r,effect):
    from .lifecycle import reset_to_definition
    effect.__post_init__()
    if effect.source_id is not None and effect.source_id not in r.state.entities:raise ResolutionError('Weapon form source does not exist')
    definition=r.registry.card(effect.card_id)
    if definition.kind!=CardType.WEAPON or definition.choice_only:raise ResolutionError('Weapon face must be an actual physical weapon')
    if r.registry.card(effect.weapon.card_id).kind!=CardType.WEAPON:raise ResolutionError('Original face must be a weapon')
    e=current_weapon(r.state,effect.weapon)
    if e is None:
        r.emit('effect_skipped',target_id=effect.weapon.entity_id,effect='RefaceEquippedWeapon',reason='stale_equipped_weapon');return ()
    if e.card_id==definition.id:return ()
    old=e.card_id;durability=e.durability;enchantments=list(e.enchantments)
    granted=[a for a in e.abilities if a.origin!='printed']
    e.face_replaced=True;e.zone_epoch+=1
    reset_to_definition(r.state,e,definition,r.registry)
    e.durability=durability;e.enchantments=enchantments;e.abilities.extend(granted)
    r.refresh_auras()
    r.emit('transformed',source_id=effect.source_id,target_id=e.id,old_card_id=old,card_id=e.card_id)


def request(r,effect):
    effect.__post_init__()
    if effect.source_id not in r.state.entities:raise ResolutionError('Weapon form source does not exist')
    for cid,_ in effect.options:
        c=r.registry.card(cid)
        if c.kind!=CardType.WEAPON or c.choice_only:raise ResolutionError('All weapon form candidates must be real weapon faces')
    if effect.weapon is not None:e=current_weapon(r.state,effect.weapon)
    else:
        from .equipment import equipped_weapon
        e=equipped_weapon(r.state,r.player(effect.player_id))
    if e is None:return ()
    ref=EquippedWeaponReference.capture(e)
    options=tuple(ChoiceOption(cid,label,(RefaceEquippedWeapon(ref,cid,effect.source_id),),card_id=cid)
        for cid,label in effect.options if cid!=e.card_id)
    return (RequestChoice(effect.player_id,options,effect.source_id,prompt='选择弹药'),) if options else ()


def register(mechanics):
    mechanics.register(RefaceEquippedWeapon,reface)
    mechanics.register(RequestWeaponForm,request)
