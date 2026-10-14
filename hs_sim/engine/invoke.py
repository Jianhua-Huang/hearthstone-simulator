"""Independent Invoke: one main physical Galakrond, upgrades and named gifts.

The profile declares all five families independently of adapter coverage. Invoke
does not activate the currently installed power, pay mana or spend its uses.
See docs/m3-invoke.md for the uncalibrated lifecycle boundaries.
"""
from dataclasses import dataclass, replace

from .construction import name
from .effects import Effect, _integer, _player, _source
from .errors import ResolutionError, ResolutionLimitExceeded
from .model import CardClass, CardType, GalakrondMain, InvokeRecord, Keyword, Zone


CLASSES = frozenset((CardClass.PRIEST, CardClass.ROGUE, CardClass.SHAMAN,
                     CardClass.WARLOCK, CardClass.WARRIOR))
COLLECTIBLE_IDS = frozenset(('DRG_600', 'DRG_610', 'DRG_620', 'DRG_650', 'DRG_660'))
VERSION = 'invoke-v1'


@dataclass(frozen=True)
class GalakrondFamily:
    hero_class: CardClass
    forms: tuple[str, str, str]
    gift_behavior: str

    def __post_init__(self):
        if type(self.hero_class) is not CardClass or self.hero_class not in CLASSES:
            raise ValueError('Galakrond requires one of the five Invoke classes')
        if type(self.forms) is not tuple or len(self.forms) != 3 or len(set(self.forms)) != 3:
            raise ValueError('Galakrond requires three distinct ordered forms')
        for cid in self.forms:
            name(cid, 'Galakrond form')
        name(self.gift_behavior, 'Galakrond gift')


@dataclass(frozen=True)
class InvokeProfile:
    version: str
    families: tuple[GalakrondFamily, ...]

    def __post_init__(self):
        name(self.version, 'Invoke profile version')
        if type(self.families) is not tuple or any(type(f) is not GalakrondFamily for f in self.families):
            raise ValueError('Invoke families must be immutable typed declarations')
        for family in self.families:
            family.__post_init__()
        if len(self.families) != 5 or {f.hero_class for f in self.families} != CLASSES:
            raise ValueError('Invoke requires all five explicit class families')
        if len({cid for f in self.families for cid in f.forms}) != 15:
            raise ValueError('Galakrond families cannot share a form')

    def family(self, card_id):
        return next((f for f in self.families if card_id in f.forms), None)


def validate_profile(registry):
    profile = registry.invoke_profile
    if profile is None:
        return
    profile.__post_init__()
    for family in profile.families:
        for cid in family.forms:
            if cid in registry.cards:
                definition = registry.card(cid)
                if (definition.kind != CardType.HERO or not definition.hero_card or definition.choice_only or
                        definition.metadata.classes != (family.hero_class,)):
                    raise ValueError('Galakrond forms require physical heroes of the declared class')
    # Missing named forms/gifts stay explicit execution gaps, never whiteboards.


def invoke_count(state, player_id):
    """Successful Invokes; no-Galakrond attempts do not satisfy two-use conditions."""
    _player(player_id)
    return sum(row.player_id == player_id and row.main_id is not None for row in state.invoke_history)


def validate_event(event):
    if event.kind != 'galakrond_invoked':
        return
    data = dict(event.data)
    if (set(data) != {'invoke_id'} or type(data['invoke_id']) is not int or data['invoke_id'] < 1 or
            type(event.amount) is not int or event.amount != 1 or event.target_id is not None or
            type(event.player_id) is not int or event.player_id not in (1, 2)):
        raise ValueError('Invalid Invoke event payload')


def record_for_event(state, event):
    validate_event(event)
    record_id = dict(event.data)['invoke_id']
    if record_id > len(state.invoke_history):
        raise ValueError('Invoke event has no accepted history record')
    record = state.invoke_history[record_id - 1]
    if (record.id, record.player_id, record.source_id, record.action) != (
            record_id, event.player_id, event.source_id, event.action):
        raise ValueError('Invoke event differs from its accepted player/source/action')
    return record


def validate_context(context, registry):
    if context.event is not None and context.event.kind == 'galakrond_invoked':
        record_for_event(context.state, context.event)


def validate_events(state, registry, events):
    captured = [event for event in events if event.kind == 'galakrond_invoked']
    if len(captured) != len(state.invoke_history):
        raise ValueError('Invoke history and actual events disagree')
    for index, event in enumerate(captured, 1):
        if record_for_event(state, event).id != index:
            raise ValueError('Invoke event order differs from actual history')


def eligible(state, entity, player_id, profile):
    if entity is None or entity.controller != player_id or profile.family(entity.card_id) is None:
        return False
    player = state.players[player_id]
    return (entity.zone == Zone.HAND and entity.id in player.hand or
            entity.zone == Zone.DECK and entity.id in player.deck or
            entity.zone == Zone.HERO and entity.id == player.hero_id)


def main_for(state, registry, player_id):
    profile = registry.invoke_profile
    if profile is None:
        return None
    binding = state.galakrond_mains[player_id]
    entity = state.entities.get(binding.entity_id) if binding is not None else None
    return entity if eligible(state, entity, player_id, profile) and (
        profile.family(entity.card_id).hero_class == binding.hero_class) else None


def synchronize(state, registry):
    """Install new physical progress and track actual presence before reactions.

    This runs only on game creation and genuine mutation events, never as a
    snapshot repair. No profile means no scan in unrelated games.
    """
    profile = registry.invoke_profile
    if profile is None:
        return
    for entity in state.entities.values():
        family = profile.family(entity.card_id)
        if family is None:
            entity.galakrond_invocations = None
        elif entity.galakrond_invocations is None:
            entity.galakrond_invocations = family.forms.index(entity.card_id) * 2
    for player in state.players.values():
        hero = state.entities.get(player.hero_id)
        main = main_for(state, registry, player.id)
        if eligible(state, hero, player.id, profile):
            main = hero
        elif main is None:
            candidates = [e for e in state.entities.values() if eligible(state, e, player.id, profile)]
            same_class = [e for e in candidates if profile.family(e.card_id).hero_class == player.hero_class]
            main = min(same_class or candidates, key=lambda e: e.id, default=None)
        state.galakrond_mains[player.id] = (None if main is None else
            GalakrondMain(main.id, profile.family(main.card_id).hero_class))


@dataclass(frozen=True)
class Invoke(Effect):
    player_id: int
    source_id: int | None = None
    count: int = 1

    def __post_init__(self):
        _player(self.player_id)
        _source(self.source_id)
        _integer(self.count, 'Invoke count', 0)


def invoke(r, effect):
    from .zones import source_exists
    from .hand_upgrades import upgrade_face
    effect.__post_init__()
    source_exists(r, effect.source_id)
    if effect.count > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Invoke count exceeds resolution budget')
    if effect.count == 0:
        return ()
    profile = r.registry.invoke_profile
    if profile is None:
        raise ResolutionError('Invoke requires a registered Galakrond profile')
    synchronize(r.state, r.registry)
    main = main_for(r.state, r.registry, effect.player_id)
    family = profile.family(main.card_id) if main is not None else None
    before = main.galakrond_invocations if main is not None else None
    after = min(4, before + 1) if main is not None and main.zone != Zone.HERO else before
    old_card = main.card_id if main is not None else None
    new_card = family.forms[after // 2] if main is not None and main.zone != Zone.HERO else old_card
    # Validate all selected content before mutating progress or upgrading a face.
    if family is not None:
        r.registry.behavior(family.gift_behavior)
        r.registry.card(new_card)
    record = InvokeRecord(len(r.state.invoke_history) + 1, effect.player_id,
        effect.source_id, profile.version, invoke_count(r.state, effect.player_id),
        main.id if main is not None else None, family.hero_class if family is not None else None,
        main.zone if main is not None else None, main.zone_epoch if main is not None else None,
        old_card, new_card, before, after, r.state.turn, r.state.action_number)
    if main is not None:
        if old_card != new_card:
            upgrade_face(r, main, new_card)
        main.galakrond_invocations = after
    r.state.invoke_history.append(record)
    # Public event carries no hidden main identity, class, location or progress.
    event = r.emit('galakrond_invoked', source_id=effect.source_id,
                   player_id=effect.player_id, amount=1, invoke_id=record.id)
    work = () if family is None else (r.call(family.gift_behavior,
        effect.source_id if effect.source_id is not None else main.id,
        effect.player_id, event=event),)
    return (*work, *((replace(effect, count=effect.count - 1),) if effect.count > 1 else ()))


def validate_state(state, registry):
    if (type(state.galakrond_mains) is not dict or
            set(state.galakrond_mains) != {1, 2} or
            any(type(k) is not int for k in state.galakrond_mains) or
            type(state.invoke_history) is not list):
        raise ValueError('Invalid Invoke state containers')
    profile = registry.invoke_profile
    for entity in state.entities.values():
        family = profile.family(entity.card_id) if profile is not None else None
        value = entity.galakrond_invocations
        if family is None:
            if value is not None:
                raise ValueError('Non-Galakrond has Invoke progress')
        else:
            stage = family.forms.index(entity.card_id)
            if type(value) is not int or not stage * 2 <= value <= min(4, stage * 2 + 1):
                raise ValueError('Galakrond face and physical Invoke progress disagree')
    for player_id, binding in state.galakrond_mains.items():
        if binding is not None:
            if type(binding) is not GalakrondMain:
                raise ValueError('Invalid main Galakrond binding')
            binding.__post_init__()
            if main_for(state, registry, player_id) is None:
                raise ValueError('Main Galakrond is absent or changed family')
        if profile is not None:
            hero = state.entities.get(state.players[player_id].hero_id)
            present = [e for e in state.entities.values() if eligible(state, e, player_id, profile)]
            if bool(present) != (binding is not None) or (
                    eligible(state, hero, player_id, profile) and binding.entity_id != hero.id):
                raise ValueError('Invoke main does not describe current presence/hero')
    counts = {1: 0, 2: 0}
    previous_time = (0, 0)
    for index, record in enumerate(state.invoke_history, 1):
        if type(record) is not InvokeRecord:
            raise ValueError('Invalid Invoke history record')
        record.__post_init__()
        if (profile is None or record.profile_version != profile.version or record.id != index or
                record.count_before != counts[record.player_id] or
                record.source_id is not None and record.source_id not in state.entities or
                not previous_time <= (record.turn, record.action) <= (state.turn, state.action_number)):
            raise ValueError('Invalid Invoke prefix, profile or provenance')
        if record.main_id is not None:
            entity = state.entities.get(record.main_id)
            family = profile.family(record.card_before)
            if (entity is None or record.main_epoch > entity.zone_epoch or family is None or
                    family.hero_class != record.hero_class or record.card_after not in family.forms or
                    not family.forms.index(record.card_before) * 2 <= record.progress_before <=
                        min(4, family.forms.index(record.card_before) * 2 + 1)):
                raise ValueError('Invalid captured Galakrond identity or form')
            after = (record.progress_before if record.main_zone == Zone.HERO else
                     min(4, record.progress_before + 1))
            card_after = record.card_before if record.main_zone == Zone.HERO else family.forms[after // 2]
            if record.progress_after != after or record.card_after != card_after:
                raise ValueError('Invalid captured Galakrond upgrade')
            registry.behavior(family.gift_behavior)
            registry.card(record.card_before)
            registry.card(record.card_after)
            counts[record.player_id] += 1
        previous_time = (record.turn, record.action)


def register(mechanics):
    mechanics.register(Invoke, invoke)
