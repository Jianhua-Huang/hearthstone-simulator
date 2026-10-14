"""Independent classic C'Thun ritual growth, separate from physical card stats.

Numeric and Geomancer Taunt growth use the same original ritual history.
Shattered C'Thun assembly is a separate rule; generation eligibility uses its
own candidate query. This module does not claim the entire family is complete.
"""
from dataclasses import dataclass

from .effects import Effect, _integer, _player, _source
from .errors import ResolutionError
from .model import AbilityInstance, CardType, CthunGrowthRecord, CthunRitualStamp, Enchantment, Keyword, Zone


VERSION = 'cthun-ritual-v2'
LIVE_ZONES = (Zone.HAND, Zone.DECK, Zone.BOARD, Zone.PLAY)


@dataclass(frozen=True)
class CthunProfile:
    version: str
    card_ids: tuple[str, ...]
    base_attack: int = 6
    base_health: int = 6

    def __post_init__(self):
        if type(self.version) is not str or not self.version:
            raise ValueError('Cthun requires a named rule version')
        if (type(self.card_ids) is not tuple or not self.card_ids or
                any(type(cid) is not str or not cid for cid in self.card_ids) or
                len(set(self.card_ids)) != len(self.card_ids)):
            raise ValueError('Cthun requires distinct registered physical identities')
        for n in ('base_attack', 'base_health'):
            _integer(getattr(self, n), 'Cthun printed ' + n, 1)


def validate_profile(registry):
    profile = registry.cthun_profile
    if profile is None:
        return
    if type(profile) is not CthunProfile:
        raise ValueError('Expected typed Cthun profile')
    profile.__post_init__()
    for cid in profile.card_ids:
        if cid not in registry.cards:
            continue  # A named missing adapter remains an execution error.
        d = registry.card(cid)
        if (d.kind != CardType.MINION or (d.attack, d.health) != (
                profile.base_attack, profile.base_health) or
                d.herald_scaling or d.starship_for or d.colossal):
            raise ValueError('Cthun physical identity requires its ordinary printed base')


def is_cthun(registry, card_id):
    return registry.cthun_profile is not None and card_id in registry.cthun_profile.card_ids


def ritual_bonus(state, player_id, first=1, last=None):
    _player(player_id)
    last = len(state.cthun_history) if last is None else last
    rows = state.cthun_history[first - 1:last]
    return (sum(r.attack for r in rows if r.player_id == player_id),
            sum(r.health for r in rows if r.player_id == player_id))


def cthun_ritual_stats(state, registry, player_id):
    """The player's ideal ritual body exists even without a physical C'Thun."""
    _player(player_id)
    profile = registry.cthun_profile
    if profile is None:
        raise ValueError('Cthun statistics require a registered rule profile')
    attack, health = ritual_bonus(state, player_id)
    return profile.base_attack + attack, profile.base_health + health


def cthun_attack_at_least(state, registry, player_id, amount=10):
    """Ritual total OR an actual held/board body satisfies the real threshold."""
    _integer(amount, 'Cthun attack threshold', 0)
    if cthun_ritual_stats(state, registry, player_id)[0] >= amount:
        return True
    return any(e.controller == player_id and e.zone in (Zone.HAND, Zone.BOARD)
               and is_cthun(registry, e.card_id) and e.attack >= amount
               for e in state.entities.values())


def ritual_taunt(state, player_id, first=1, last=None):
    _player(player_id)
    last = len(state.cthun_history) if last is None else last
    return any(row.taunt for row in state.cthun_history[first - 1:last]
               if row.player_id == player_id)


def attach(state, registry, entity, player_id, first, last, *, stats=True, taunt=True):
    attack, health = ritual_bonus(state, player_id, first, last)
    has_taunt = taunt and ritual_taunt(state, player_id, first, last)
    if not (stats and (attack or health)) and not has_taunt:
        return
    from .lifecycle import attachment_id, refresh_entity
    stamp = CthunRitualStamp(player_id, first, last, registry.cthun_profile.version)
    if stats and (attack or health):
        entity.enchantments.append(Enchantment(attachment_id(state), attack=attack,
            health=health, remove_on_silence=False, label='cthun_ritual', cthun_ritual=stamp))
    if has_taunt:
        entity.abilities.append(AbilityInstance(attachment_id(state), 'keyword',
            keyword=Keyword.TAUNT, remove_on_silence=False, cthun_ritual=stamp))
    refresh_entity(entity)


def initialize_instance(state, registry, entity):
    """A new ordinary body receives its controller's past growth once.

    Transform uses reset_to_definition, which intentionally does not call this.
    Current copies subsequently replace attachments with their frozen material.
    """
    if is_cthun(registry, entity.card_id) and entity.zone in LIVE_ZONES:
        attach(state, registry, entity, entity.controller, 1, len(state.cthun_history))


def catch_up_on_reset(state, registry, entity):
    """A reset into an ordinary stored body adds previously unapplied owner rows.

    Existing permanent rows stay intact. A transformed body can therefore catch
    up when returned to hand; a normal bounce never applies the same row twice.
    """
    if not is_cthun(registry, entity.card_id) or entity.zone not in LIVE_ZONES:
        return
    stamps = [e.cthun_ritual for e in entity.enchantments if e.cthun_ritual is not None
              and e.cthun_ritual.player_id == entity.controller]
    taunts = [a.cthun_ritual for a in entity.abilities if a.cthun_ritual is not None
              and a.cthun_ritual.player_id == entity.controller]
    for row in state.cthun_history:
        if row.player_id != entity.controller:
            continue
        missing_stats = (row.attack or row.health) and not any(s.first_id <= row.id <= s.last_id for s in stamps)
        missing_taunt = row.taunt and not any(s.first_id <= row.id <= s.last_id for s in taunts)
        if missing_stats or missing_taunt:
            attach(state, registry, entity, entity.controller, row.id, row.id,
                   stats=bool(missing_stats), taunt=missing_taunt)


@dataclass(frozen=True)
class GrowCthun(Effect):
    player_id: int
    attack: int
    health: int
    source_id: int | None = None
    taunt: bool = False

    def __post_init__(self):
        _player(self.player_id); _source(self.source_id)
        _integer(self.attack, 'Cthun ritual attack', 0)
        _integer(self.health, 'Cthun ritual health', 0)
        if type(self.taunt) is not bool:
            raise ValueError('Cthun ritual Taunt requires an exact bool')


def grow(r, effect):
    effect.__post_init__()
    profile = r.registry.cthun_profile
    if profile is None:
        raise ResolutionError('Cthun growth requires a registered rule profile')
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Cthun growth source does not exist')
    if not effect.attack and not effect.health and not effect.taunt:
        return ()
    row = CthunGrowthRecord(len(r.state.cthun_history) + 1, effect.player_id,
        effect.source_id, effect.attack, effect.health, profile.version,
        r.state.turn, r.state.action_number, effect.taunt)
    r.state.cthun_history.append(row)
    for entity in r.state.entities.values():
        if (entity.controller == effect.player_id and entity.zone in LIVE_ZONES
                and is_cthun(r.registry, entity.card_id)):
            attach(r.state, r.registry, entity, effect.player_id, row.id, row.id)
    r.refresh_auras()
    # An internal receipt adds no invented public trigger or hidden-card leak.
    r.emit('cthun_ritual_grown', source_id=effect.source_id,
           player_id=effect.player_id, amount=effect.attack,
           growth_id=row.id, health=effect.health, taunt=effect.taunt, _capture=False)
    return ()


def validate_stamp(state, registry, attachment):
    stamp = attachment.cthun_ritual
    if stamp is None:
        return
    stamp.__post_init__()
    profile = registry.cthun_profile
    if (profile is None or stamp.version != profile.version or stamp.last_id > len(state.cthun_history)):
        raise ValueError('Cthun permanent attachment has another original ritual scope')
    if isinstance(attachment, AbilityInstance):
        if not ritual_taunt(state, stamp.player_id, stamp.first_id, stamp.last_id):
            raise ValueError('Cthun permanent Taunt has no original Taunt grant')
    elif (attachment.attack, attachment.health) != ritual_bonus(
            state, stamp.player_id, stamp.first_id, stamp.last_id):
        raise ValueError('Cthun permanent increment differs from its original ritual records')


def validate_state(state, registry):
    if type(state.cthun_history) is not list:
        raise ValueError('Cthun history requires ordered typed records')
    profile = registry.cthun_profile
    previous = (0, 0)
    for index, row in enumerate(state.cthun_history, 1):
        if type(row) is not CthunGrowthRecord:
            raise ValueError('Invalid Cthun growth history record')
        row.__post_init__()
        if (profile is None or row.version != profile.version or row.id != index or
                row.source_id is not None and row.source_id not in state.entities or
                row.turn > state.turn or row.action > state.action_number or
                row.turn < previous[0] or row.action < previous[1]):
            raise ValueError('Invalid Cthun original growth provenance')
        previous = (row.turn, row.action)
    for entity in state.entities.values():
        channels = (entity.enchantments, entity.abilities)
        if any(a.cthun_ritual is not None for channel in channels for a in channel) and not is_cthun(registry, entity.card_id):
            raise ValueError('Only a registered physical Cthun carries ritual increments')
        for channel in channels:
            seen = set()
            for attachment in channel:
                stamp = attachment.cthun_ritual
                if stamp is None:
                    continue
                ids = {r.id for r in state.cthun_history[stamp.first_id - 1:stamp.last_id]
                       if r.player_id == stamp.player_id and (
                           r.taunt if isinstance(attachment, AbilityInstance) else r.attack or r.health)}
                if ids & seen:
                    raise ValueError('A physical Cthun applied the same ritual contribution twice')
                seen |= ids


def validate_events(state, events):
    actual = [e for e in events if e.kind == 'cthun_ritual_grown']
    if len(actual) != len(state.cthun_history):
        raise ValueError('Cthun history and actual growth receipts disagree')
    for index, event in enumerate(actual, 1):
        validate_event(event)
        row = state.cthun_history[index - 1]
        if (dict(event.data) != {'growth_id': index, 'health': row.health, 'taunt': row.taunt} or
                (event.source_id, event.target_id, event.player_id, event.amount, event.action) !=
                (row.source_id, None, row.player_id, row.attack, row.action)):
            raise ValueError('Cthun receipt differs from its original growth')


def validate_event(event):
    if event.kind != 'cthun_ritual_grown':
        return
    data = dict(event.data)
    if (set(data) != {'growth_id', 'health', 'taunt'} or event.target_id is not None or
            type(data['growth_id']) is not int or data['growth_id'] < 1 or
            type(data['health']) is not int or data['health'] < 0 or
            type(event.amount) is not int or event.amount < 0 or
            type(data['taunt']) is not bool or not (data['health'] or event.amount or data['taunt'])):
        raise ValueError('Invalid private Cthun growth receipt')


def register(mechanics):
    mechanics.register(GrowCthun, grow)
    mechanics.register_payload_type(CthunRitualStamp)

