"""An explicit complete Standard-pack domain and five native automatic plays."""
from dataclasses import asdict, dataclass
import json
from random import Random

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .effects import Effect, _integer, _player
from .errors import ResolutionError
from .model import CardType, Zone, _name
from .pools import GenerationContext, PoolQuery, matches_metadata, sample_candidates

OPENED = 'standard_pack_opened'
STEP = 'standard_pack_card_started'
FINISHED = 'standard_pack_finished'
VERSION = 'standard-pack-host-weights-v1'
KINDS = (CardType.MINION, CardType.SPELL, CardType.WEAPON, CardType.LOCATION, CardType.HERO)
QUERY = PoolQuery(kinds=KINDS, collectible=True)


@dataclass(frozen=True)
class StandardPackProfile:
    source_card_id: str
    pool_id: str = 'constructed.standard_pack'
    version: str = VERSION

    def __post_init__(self):
        _name(self.source_card_id, 'pack source')
        if self.pool_id != 'constructed.standard_pack' or self.version != VERSION:
            raise ValueError('Standard-pack playback requires its explicit versioned pack domain')


def validate_profile(registry, profile):
    if type(profile) is not StandardPackProfile: raise ValueError('Typed Standard-pack source required')
    profile.__post_init__(); card = registry.card(profile.source_card_id)
    if card.kind != CardType.MINION or card.battlecry is None:
        raise ValueError('Standard-pack source requires its actual Battlecry minion')


def pack_candidates(registry, context, profile):
    """Pack eligibility is independent of ordinary Discover/generation bans.

    The host must supply the actual complete pack-printing domain and weights.
    No rarity guarantees, ownership protection or shop pity timers are inferred.
    """
    if type(context) is not GenerationContext: raise ResolutionError('A Standard pack requires its explicit pool context')
    context.__post_init__(); profile.__post_init__(); pool = registry.pool(profile.pool_id, context)
    if not pool.complete: raise ResolutionError('A Standard pack requires its complete independently reviewed pool')
    excluded = set(pool.excluded_card_ids); identities = set(); eligible = []
    for member in sorted(pool.members, key=lambda m: m.card_id):
        row = registry.pool_card(member.card_id)
        if row.card_id in excluded: continue
        if not matches_metadata(QUERY, card_id=row.card_id, kind=row.kind, cost=row.cost, meta=row.metadata,
                spell_school=row.spell_school, keywords=row.keywords): continue
        definition = registry.card(row.card_id)  # Unknown eligible content is never filtered out.
        if not definition.hand_playable or definition.choice_only:
            raise ResolutionError('An eligible pack card has no native playable definition')
        if row.generation_identity in identities:
            raise ResolutionError('Pack printings require one explicit original identity, not duplicate editions')
        identities.add(row.generation_identity); eligible.append(member)
    if not eligible: raise ResolutionError('A complete Standard pack cannot have an empty eligible domain')
    return pool, tuple(eligible)


@dataclass(frozen=True)
class OpenStandardPack(Effect):
    player_id: int
    source: SourceAllocationFact
    profile_card_id: str

    def __post_init__(self):
        _player(self.player_id); _name(self.profile_card_id, 'pack profile')
        if type(self.source) is not SourceAllocationFact: raise ValueError('Pack requires its original physical issuer')
        self.source.__post_init__()


@dataclass(frozen=True)
class PlayStandardPackSlot(Effect):
    opening_id: int
    index: int = 0

    def __post_init__(self):
        _integer(self.opening_id, 'original pack opening', 1); _integer(self.index, 'pack cursor', 0)
        if self.index > 5: raise ValueError('A Standard pack has five original card occurrences')


def pack(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def request_from_dict(value):
    data = json.loads(value); data['source'] = allocation_from_dict(data['source'])
    return OpenStandardPack(**data)


def events(game, kind):
    from .hero_health_history import effective_events
    return tuple(e for e in effective_events(game._events) if e.kind == kind)


def opening(game, ident):
    rows = [e for e in events(game, OPENED) if e.sequence == ident]
    if len(rows) != 1: raise ValueError('Pack playback lost its original effective opening')
    event = rows[0]; data = dict(event.data); request = request_from_dict(data['request'])
    return event, data, request


def open_pack(r, effect):
    effect.__post_init__(); validate_allocation(r.state, r.registry, effect.source)
    profile = r.registry._standard_pack_profiles[effect.profile_card_id]
    pool, candidates = pack_candidates(r.registry, r.game._generation_context, profile)
    before = r.game._rng.getstate(); drawn = sample_candidates(r.game._rng, candidates, 5, replacement=True)
    event = r.emit(OPENED, source_id=effect.source.entity_id, player_id=effect.player_id,
        request=pack(asdict(effect)), pool_version=pool.version, candidates=tuple((m.card_id, m.weight) for m in candidates),
        drawn=drawn, rng_before=before, rng_after=r.game._rng.getstate(), _capture=False)
    return (PlayStandardPackSlot(event.sequence),)


def play_slot(r, effect):
    event, data, request = opening(r.game, effect.opening_id)
    steps = [e for e in events(r.game, STEP) if dict(e.data)['opening_id'] == event.sequence]
    if effect.index != len(steps) or any(dict(e.data)['opening_id'] == event.sequence for e in events(r.game, FINISHED)):
        raise ValueError('Pack playback changed or duplicated its original slot cursor')
    source = r.state.entities[request.source.entity_id]
    # Each actual next card follows the original physical issuer's current
    # controller, including a move to the opponent's deck; it is not a new play.
    player_id = source.controller
    if effect.index == 5:
        r.emit(FINISHED, source_id=source.id, player_id=player_id, opening_id=event.sequence, _capture=False)
        return ()
    card_id = data['drawn'][effect.index]; card = r.registry.card(card_id)
    r.emit(STEP, source_id=source.id, player_id=player_id, opening_id=event.sequence, index=effect.index,
        card_id=card_id, source=pack(asdict(SourceAllocationFact.capture(r.state, source))), _capture=False)
    tail = (PlayStandardPackSlot(event.sequence, effect.index + 1),)
    if card.kind == CardType.MINION:
        from .summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
        cause = SummonCause(SourceAllocationFact.capture(r.state, source), player_id, r.state.turn, r.state.action_number)
        return (SummonByCard(player_id, (SummonEntryMaterial(card_id),), cause), *tail)
    if card.kind == CardType.SPELL:
        from .spell_casts import CastSpell, automatic
        entity = r.create_entity(player_id, card_id, Zone.GRAVEYARD)
        return (*automatic(r, CastSpell(player_id, card_id, source.id), entity, None), *tail)
    if card.kind in (CardType.WEAPON, CardType.LOCATION):
        from .generated_placement import InstallGeneratedPlacement, install_generated_placement
        install_generated_placement(r, InstallGeneratedPlacement(player_id, card_id, source.id))
        return tail
    if card.kind == CardType.HERO:
        from .generated_heroes import InstallGeneratedHeroCard, install_generated_hero_card
        install_generated_hero_card(r, InstallGeneratedHeroCard(player_id, card_id, source.id))
        return tail
    raise ResolutionError('Unsupported actual pack card kind')


def validate_game(game):
    from .hero_health_history import effective_events
    relevant = [e for e in effective_events(game._events) if e.kind in (OPENED, STEP, FINISHED)]
    frame = game._frame; queue = () if frame is None else (*frame.prefix, *frame.continuation)
    if not relevant and not any(type(w) in (OpenStandardPack, PlayStandardPackSlot) for w in queue): return
    roots = {}
    for event in relevant:
        data = dict(event.data)
        if event.kind == OPENED:
            request = request_from_dict(data['request']); validate_allocation(game._state, game.registry, request.source)
            profile = game.registry._standard_pack_profiles[request.profile_card_id]
            pool, candidates = pack_candidates(game.registry, game._generation_context, profile)
            rng = Random(); rng.setstate(data['rng_before']); drawn = sample_candidates(rng, candidates, 5, replacement=True)
            if (event.source_id, event.player_id, data['pool_version'], tuple(data['candidates']), tuple(data['drawn']), data['rng_after']) != (
                    request.source.entity_id, request.player_id, pool.version, tuple((m.card_id, m.weight) for m in candidates), drawn, rng.getstate()):
                raise ValueError('Pack changed its complete original domain, weights or five-card draw')
            roots[event.sequence] = dict(request=request, drawn=drawn, steps=0, finished=False)
        else:
            root = roots.get(data['opening_id'])
            if root is None or root['finished'] or event.source_id != root['request'].source.entity_id:
                raise ValueError('Pack playback borrowed a missing or finished opening')
            if event.kind == STEP:
                material = allocation_from_dict(json.loads(data['source'])); validate_allocation(game._state, game.registry, material)
                if (root['steps'] >= 5 or data['index'] != root['steps'] or data['card_id'] != root['drawn'][root['steps']] or
                        (material.entity_id, material.controller) != (event.source_id, event.player_id)):
                    raise ValueError('Pack changed its ordered original occurrence or actual acting source')
                root['steps'] += 1
            else:
                if root['steps'] != 5 or set(data) != {'opening_id'}: raise ValueError('Pack finished before all five original occurrences')
                root['finished'] = True
    for work in queue:
        if type(work) is OpenStandardPack:
            validate_allocation(game._state, game.registry, work.source)
            pack_candidates(game.registry, game._generation_context, game.registry._standard_pack_profiles[work.profile_card_id])
        elif type(work) is PlayStandardPackSlot:
            root = roots.get(work.opening_id)
            if root is None or root['finished'] or work.index != root['steps']:
                raise ValueError('Pack continuation lost its unique original next slot')
    if game._state.status != 'playing': return
    for ident, root in roots.items():
        pending = [w for w in queue if type(w) is PlayStandardPackSlot and w.opening_id == ident]
        if pending != ([] if root['finished'] else [PlayStandardPackSlot(ident, root['steps'])]):
            raise ValueError('Pack playback lost or duplicated its original unexecuted cards')


def register(mechanics):
    mechanics.register(OpenStandardPack, open_pack)
    mechanics.register(PlayStandardPackSlot, play_slot)
