"""Original-residence attacker, current enemy minions, ordinary forced combat."""
from dataclasses import dataclass
from .board_presence import resolve_board_presence
from .effects import Effect,ForceAttack,_player,_source
from .model import BoardPresenceReference,CardType,_bool


@dataclass(frozen=True)
class ForceEachMinionAttack(Effect):
    """Each surviving original residence attacks once; new summons may defend."""
    remaining: tuple[BoardPresenceReference, ...] | None = None

    def __post_init__(self):
        if self.remaining is not None:
            if (type(self.remaining) is not tuple or any(type(r) is not BoardPresenceReference for r in self.remaining)
                    or len({r.entity_id for r in self.remaining}) != len(self.remaining)):
                raise ValueError('Each-minion attacks require distinct original residences')
            for ref in self.remaining: ref.__post_init__()

    def validate_in_state(self, state):
        self.__post_init__()
        if self.remaining is not None and any(r.entity_id not in state.entities or r.presence_id >= state.next_order for r in self.remaining):
            raise ValueError('Each-minion attack borrowed an unknown or future residence')


def each_minion_attack(r, effect):
    effect.validate_in_state(r.state)
    def live():
        return tuple(BoardPresenceReference.capture(r.state, eid) for player in (1, 2) for eid in r.player(player).board
            for entity in (r.state.entities[eid],) if entity.kind == CardType.MINION and entity.active and
            entity.health > 0 and not entity.doomed and r.registry.card(entity.card_id).interactable is None)
    current = live()
    remaining = current if effect.remaining is None else tuple(ref for ref in effect.remaining if ref in current)
    if not remaining or len(current) < 2: return ()
    attacker = r.game._rng.choice(remaining)
    defender = r.game._rng.choice(tuple(ref for ref in current if ref != attacker))
    r.emit('random_choice', source_id=attacker.entity_id, target_id=defender.entity_id,
        producer='each_minion_forced_attack', attacker_presence_id=attacker.presence_id, defender_presence_id=defender.presence_id)
    return (ForceAttack(attacker, defender, combat_relation='any_minions'),
        ForceEachMinionAttack(tuple(ref for ref in remaining if ref != attacker)))

@dataclass(frozen=True)
class AttackRandomEnemyMinion(Effect):
    attacker:BoardPresenceReference
    player_id:int
    source_id:int|None=None
    excess_to_hero:bool=False

    def __post_init__(self):
        if type(self.attacker)is not BoardPresenceReference:raise ValueError('Random enemy attack requires its original board residence')
        self.attacker.__post_init__();_player(self.player_id);_source(self.source_id)
        _bool(self.excess_to_hero,'random attack excess policy')

    def validate_in_state(self,state):
        self.__post_init__()
        if self.attacker.entity_id not in state.entities or self.attacker.presence_id>=state.next_order:
            raise ValueError('Random enemy attack borrowed an unknown or future residence')
        if self.source_id is not None and self.source_id not in state.entities:
            raise ValueError('Random enemy attack has an unknown original source')

def execute(r,effect):
    effect.validate_in_state(r.state)
    attacker=resolve_board_presence(r.state,effect.attacker)
    if attacker is None or not attacker.active or attacker.health<=0 or attacker.doomed or attacker.controller!=effect.player_id:
        r.stale(effect,effect.attacker.entity_id);return ()
    candidates=tuple(sorted(eid for eid in r.player(3-effect.player_id).board for entity in(r.state.entities[eid],)
        if entity.kind==CardType.MINION and entity.active and entity.health>0 and not entity.doomed
        and r.registry.card(entity.card_id).interactable is None))
    if not candidates:return ()
    defender=r.game._rng.choice(candidates)
    original=BoardPresenceReference.capture(r.state,defender)
    r.emit('random_choice',source_id=effect.source_id,target_id=attacker.id,defender_id=defender)
    return(ForceAttack(effect.attacker,original,excess_to_hero=effect.excess_to_hero),)

@dataclass(frozen=True)
class AttackLowestHealthEnemy(AttackRandomEnemyMinion):
    """One original attacker; reselect current enemy characters for this attack."""


@dataclass(frozen=True)
class AttackRandomEnemyCharacter(AttackRandomEnemyMinion):
    """One original attacker; uniformly select a current enemy character."""


def _attack_character(r, effect, *, lowest):
    effect.validate_in_state(r.state)
    attacker = resolve_board_presence(r.state, effect.attacker)
    if (attacker is None or not attacker.active or attacker.health <= 0 or attacker.doomed or
            attacker.controller != effect.player_id):
        r.stale(effect, effect.attacker.entity_id); return ()
    enemy = r.player(3-effect.player_id)
    candidates = tuple(sorted(eid for eid in (enemy.hero_id, *enemy.board)
        for e in (r.live_character(eid),) if e is not None and e.health > 0 and not e.doomed
        and r.registry.card(e.card_id).interactable is None))
    if not candidates: return ()
    if lowest:
        minimum = min(r.state.entities[eid].health for eid in candidates)
        candidates = tuple(eid for eid in candidates if r.state.entities[eid].health == minimum)
    defender = r.game._rng.choice(candidates)
    target = (BoardPresenceReference.capture(r.state, defender)
        if r.state.entities[defender].kind == CardType.MINION else defender)
    r.emit('random_choice', source_id=effect.source_id, target_id=attacker.id,
        defender_id=defender, producer='attack_lowest_health_enemy' if lowest else 'attack_random_enemy_character')
    return (ForceAttack(effect.attacker, target, excess_to_hero=effect.excess_to_hero),)


def attack_lowest(r, effect):
    return _attack_character(r, effect, lowest=True)


def attack_random_character(r, effect):
    return _attack_character(r, effect, lowest=False)


@dataclass(frozen=True)
class AttackAllOtherMinions(Effect):
    attacker: BoardPresenceReference
    visited: tuple[BoardPresenceReference, ...] = ()

    def __post_init__(self):
        if type(self.attacker) is not BoardPresenceReference:
            raise ValueError('All-minion attack requires its original physical residence')
        self.attacker.__post_init__()
        if type(self.visited) is not tuple or len(set(self.visited)) != len(self.visited):
            raise ValueError('All-minion attack requires distinct attempted residences')
        for ref in self.visited:
            if type(ref) is not BoardPresenceReference or ref == self.attacker:
                raise ValueError('All-minion attack has an invalid attempted target')
            ref.__post_init__()

    def validate_in_state(self, state):
        self.__post_init__()
        for ref in (self.attacker, *self.visited):
            if ref.entity_id not in state.entities or ref.presence_id >= state.next_order:
                raise ValueError('All-minion attack has an unknown or future residence')


def attack_all(r, effect):
    effect.validate_in_state(r.state)
    attacker = resolve_board_presence(r.state, effect.attacker)
    if attacker is None or not attacker.active or attacker.health <= 0 or attacker.doomed:
        r.stale(effect, effect.attacker.entity_id)
        return ()
    candidates = tuple(BoardPresenceReference.capture(r.state, eid)
        for player in (1, 2) for eid in r.player(player).board
        for entity in (r.state.entities[eid],)
        if entity.kind == CardType.MINION and entity.active and entity.health > 0 and not entity.doomed
        and entity.id != attacker.id and r.registry.card(entity.card_id).interactable is None)
    candidates = tuple(sorted((ref for ref in candidates if ref not in effect.visited),
                              key=lambda ref: ref.entity_id))
    if not candidates:
        return ()
    defender = r.game._rng.choice(candidates)
    r.emit('random_choice', source_id=attacker.id, target_id=defender.entity_id,
           producer='attack_all_other_minions', defender_presence_id=defender.presence_id)
    return (ForceAttack(effect.attacker, defender, combat_relation='any_minions'),
            AttackAllOtherMinions(effect.attacker, (*effect.visited, defender)))


def register(mechanics):
    mechanics.register(AttackRandomEnemyMinion, execute)
    mechanics.register(AttackLowestHealthEnemy, attack_lowest)
    mechanics.register(AttackRandomEnemyCharacter, attack_random_character)
    mechanics.register(AttackAllOtherMinions, attack_all)
    mechanics.register(ForceEachMinionAttack, each_minion_attack)
