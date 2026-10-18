"""Two other enemies from a real completed weapon attack, using normal Freeze."""
from dataclasses import dataclass
from .effects import Effect, Freeze, _integer
from .errors import ResolutionError
from .model import CardType, Zone


@dataclass(frozen=True)
class FreezeOtherEnemiesAfterWeaponAttack(Effect):
    attack_id: int
    source_id: int
    def __post_init__(self):
        _integer(self.attack_id,'original character attack',1)
        _integer(self.source_id,'original weapon source',1)


def freeze_others(r,effect):
    effect.__post_init__()
    row=next((x for x in r.state.character_attack_history if x.declaration.id==effect.attack_id),None)
    if row is None:raise ResolutionError('Unknown original completed attack')
    if (row.source_kind!=CardType.HERO or row.terminal is None or
            row.terminal.status!='completed' or row.combat is None or row.combat.weapon_id!=effect.source_id):
        raise ResolutionError('Freeze followup requires its original completed hero weapon attack')
    if effect.source_id not in r.state.entities or r.registry.card(r.state.entities[effect.source_id].card_id).kind!=CardType.WEAPON:
        raise ResolutionError('Freeze weapon source does not exist')
    player=r.player(3-row.declaration.player_id)
    candidates=tuple(i for i in (player.hero_id,*player.board) for e in (r.state.entities[i],)
        if i!=row.delivery.target_id and e.kind in (CardType.HERO,CardType.MINION) and e.zone in (Zone.HERO,Zone.BOARD)
        and e.active and not e.doomed and e.health>0 and r.registry.card(e.card_id).interactable is None)
    if not candidates:return ()
    selected=tuple(r.game._rng.sample(candidates,min(2,len(candidates))))
    r.emit('random_choice',source_id=effect.source_id,candidates=candidates,selected=selected)
    from .resolver import freeze_character
    pending=[]
    for target in selected:freeze_character(r,Freeze(target,effect.source_id),pending_events=pending)
    for kind,data in pending:r.emit(kind,**data)


def register(mechanics):mechanics.register(FreezeOtherEnemiesAfterWeaponAttack,freeze_others)
