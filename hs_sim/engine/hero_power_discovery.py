"""Finite basic-skill offers connected to original Discover and power installation."""
from dataclasses import dataclass
from random import Random

from .allocation_facts import SourceAllocationFact, validate_allocation
from .construction import ids, name
from .effects import ChoiceOption, Effect, ReplaceHeroPower, RequestChoice, _player, _source
from .model import CardClass, CardType, ChoicePurpose, Zone, validate_end_turn_rng
from .pools import PoolMember, sample_candidates

PROMPT = '发现一个新的基础英雄技能'


@dataclass(frozen=True)
class HeroPowerDiscoveryProfile:
    card_id: str
    power_card_ids: tuple[str, ...]

    def __post_init__(self):
        name(self.card_id, 'skill discovery profile source')
        ids(self.power_card_ids, 'complete basic skill family', unique=True)
        if not self.power_card_ids:
            raise ValueError('A basic skill family must be explicitly nonempty')


def power_class(registry, card_id):
    from .registry import UnsupportedDefinitionError
    card = registry.card(card_id)
    if card.kind != CardType.HERO_POWER:
        raise ValueError('Basic skill discovery requires Hero Power definitions')
    if card.metadata is None or card.metadata.classes is None:
        raise UnsupportedDefinitionError('Basic skill discovery requires the printed power class')
    classes = tuple(c for c in card.metadata.classes if c != CardClass.NEUTRAL)
    if len(classes) > 1:
        raise UnsupportedDefinitionError('Basic skill discovery does not guess a multiclass power exclusion')
    return classes[0] if classes else None


def validate_profile(registry, profile):
    if type(profile) is not HeroPowerDiscoveryProfile:
        raise ValueError('Expected a typed complete basic skill family')
    profile.__post_init__()
    source = registry.card(profile.card_id)
    if source.kind != CardType.MINION or source.battlecry is None:
        raise ValueError('Basic skill discovery requires its actual battlecry source')
    classes = []
    for card_id in profile.power_card_ids:
        card = registry.card(card_id)
        current = power_class(registry, card_id)
        if current is None or card.passive_hero_power or card.choice_only:
            raise ValueError('Basic skill offers require active single-class physical skills')
        classes.append(current)
    if len(classes) != len(set(classes)):
        raise ValueError('Basic skill family has more than one edition of a class')


@dataclass(frozen=True)
class DiscoverHeroPower(Effect):
    player_id: int
    source_id: int
    profile_card_id: str

    def __post_init__(self):
        _player(self.player_id); _source(self.source_id)
        if self.source_id is None:
            raise ValueError('Basic skill discovery requires its actual source')
        name(self.profile_card_id, 'basic skill discovery profile')


@dataclass(frozen=True)
class HeroPowerDiscoveryOffer:
    request: DiscoverHeroPower
    source: SourceAllocationFact
    previous_power: SourceAllocationFact | None
    eligible: tuple[str, ...]
    offered: tuple[str, ...]
    rng_before: tuple
    rng_after: tuple

    def __post_init__(self):
        if type(self.request) is not DiscoverHeroPower or type(self.source) is not SourceAllocationFact:
            raise ValueError('Skill offer requires its complete original request and source')
        self.request.__post_init__(); self.source.__post_init__()
        if self.source.entity_id != self.request.source_id:
            raise ValueError('Skill offer borrowed another physical source')
        if self.previous_power is not None:
            if type(self.previous_power) is not SourceAllocationFact:
                raise ValueError('Skill offer requires its captured original primary skill')
            self.previous_power.__post_init__()
            if (self.previous_power.kind, self.previous_power.zone, self.previous_power.controller) != (
                    CardType.HERO_POWER, Zone.HERO_POWER, self.request.player_id):
                raise ValueError('Skill offer captured another slot owner or kind')
        ids(self.eligible, 'complete eligible skill family', unique=True)
        ids(self.offered, 'original sampled skill offers', unique=True)
        if self.eligible != tuple(sorted(self.eligible)):
            raise ValueError('Skill candidates require stable complete ordering')
        validate_end_turn_rng(self.rng_before); validate_end_turn_rng(self.rng_after)
        local = Random(); local.setstate(self.rng_before)
        expected = tuple(sample_candidates(local, tuple(PoolMember(cid) for cid in self.eligible),
            3, replacement=False))
        if expected != self.offered or local.getstate() != self.rng_after:
            raise ValueError('Skill menu lost its complete original uniform draw')


@dataclass(frozen=True)
class InstallDiscoveredHeroPower(Effect):
    offer: HeroPowerDiscoveryOffer
    card_id: str

    def __post_init__(self):
        if type(self.offer) is not HeroPowerDiscoveryOffer:
            raise ValueError('Discovered skill installation requires its original offer')
        self.offer.__post_init__()
        if self.card_id not in self.offer.offered:
            raise ValueError('Installed skill was not in the original sampled menu')

    @property
    def player_id(self): return self.offer.request.player_id

    @property
    def source_id(self): return self.offer.request.source_id


def profile_for(registry, request):
    request.__post_init__()
    profile = registry.hero_power_discovery_profiles.get(request.profile_card_id)
    if profile is None:
        raise ValueError('No complete registered basic skill family for this source')
    validate_profile(registry, profile)
    return profile


def candidates(registry, profile, previous_power):
    excluded = None if previous_power is None else power_class(registry, previous_power.card_id)
    return tuple(cid for cid in sorted(profile.power_card_ids) if power_class(registry, cid) != excluded)


def validate_offer_data(state, registry, offer, *, closed=False):
    offer.__post_init__()
    profile = profile_for(registry, offer.request)
    validate_allocation(state, registry, offer.source, closed=closed)
    if offer.previous_power is not None:
        validate_allocation(state, registry, offer.previous_power, closed=closed)
    if offer.eligible != candidates(registry, profile, offer.previous_power):
        raise ValueError('Skill offer lost its complete original class exclusion')


def options_for(registry, offer):
    from .pool_offers import preview
    return tuple(ChoiceOption(cid, registry.card(cid).name, (InstallDiscoveredHeroPower(offer, cid),),
        card_id=cid, preview=preview(registry.card(cid), registry.card(cid).cost)) for cid in offer.offered)


def discover(r, request):
    profile = profile_for(r.registry, request)
    source = r.state.entities.get(request.source_id)
    if source is None:
        raise ValueError('Basic skill discovery lost its physical source')
    old_id = r.player(request.player_id).hero_power_id
    previous = None if old_id is None else SourceAllocationFact.capture(r.state, r.state.entities[old_id])
    eligible = candidates(r.registry, profile, previous)
    before = r.game._rng.getstate()
    offered = tuple(sample_candidates(r.game._rng, tuple(PoolMember(cid) for cid in eligible), 3, replacement=False))
    offer = HeroPowerDiscoveryOffer(request, SourceAllocationFact.capture(r.state, source), previous,
        eligible, offered, before, r.game._rng.getstate())
    if not offered:
        return ()
    return (RequestChoice(request.player_id, options_for(r.registry, offer), request.source_id,
        prompt=PROMPT, purpose=ChoicePurpose.CARD_DISCOVERY),)


def validate_menu(registry, original):
    work = tuple(o.effects[0] for o in original.options
        if len(o.effects) == 1 and type(o.effects[0]) is InstallDiscoveredHeroPower)
    if not work:
        return False
    offer = work[0].offer
    offer.__post_init__()
    profile = profile_for(registry, offer.request)
    if offer.eligible != candidates(registry, profile, offer.previous_power):
        raise ValueError('Skill offer lost its complete original class exclusion')
    choice = original.choice
    if (original.on_select is not None or original.options != options_for(registry, offer) or
            (choice.player_id, choice.source_id, choice.prompt, choice.min_count, choice.max_count,
             choice.purpose, choice.repeat_key) !=
            (offer.request.player_id, offer.request.source_id, PROMPT, 1, 1, ChoicePurpose.CARD_DISCOVERY, None)):
        raise ValueError('Basic skill discovery changed its complete original menu or actor')
    return True


def validate_original_offer(game, original):
    if validate_menu(game.registry, original):
        validate_offer_data(game._state, game.registry, original.options[0].effects[0].offer, closed=True)


def validate_recipe(result, request):
    if type(request) is not InstallDiscoveredHeroPower:
        return
    request.__post_init__()
    choice = result.choice
    if (choice.purpose != ChoicePurpose.CARD_DISCOVERY or
            tuple(x.card_id for x in choice.options) != request.offer.offered or
            tuple(x.id for x in choice.options) != request.offer.offered or
            (choice.player_id, choice.source_id, choice.prompt, choice.min_count, choice.max_count) !=
            (request.player_id, request.source_id, PROMPT, 1, 1)):
        raise ValueError('Discovered skill borrowed another original card selection')


def materialize(r, result, request):
    from .card_discoveries import require_original_result
    from .hero_powers import install_hero_power
    validate_recipe(result, request)
    validate_offer_data(r.state, r.registry, request.offer)
    require_original_result(r.state, result)
    old, entity = install_hero_power(r, ReplaceHeroPower(request.player_id, request.card_id,
        source_id=request.source_id))
    r.emit('hero_power_replaced', source_id=old, target_id=entity.id, player_id=request.player_id)
    return entity


def validate_completion(state, registry, completion):
    if type(completion.recipe) is not InstallDiscoveredHeroPower:
        return
    request = completion.recipe
    validate_recipe(completion.result, request)
    validate_offer_data(state, registry, request.offer, closed=True)
    fact = completion.recipient
    if fact is None or (fact.kind, fact.zone, fact.controller, fact.card_id) != (
            CardType.HERO_POWER, Zone.HERO_POWER, request.player_id, request.card_id):
        raise ValueError('Discovered skill lost its actual installed physical recipient')
    if completion.result.choice.options != tuple(o.item for o in options_for(registry, request.offer)):
        raise ValueError('Discovered skill changed its original visible menu')


def direct_install(r, effect):
    raise ValueError('A discovered skill must be materialized by its original committed discovery')


def register(mechanics):
    mechanics.register(DiscoverHeroPower, discover)
    mechanics.register(InstallDiscoveredHeroPower, direct_install)
    mechanics.register_payload_type(HeroPowerDiscoveryOffer)
