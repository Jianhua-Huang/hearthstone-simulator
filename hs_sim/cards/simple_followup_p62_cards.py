"""Original physical choices and complete standard-reachable spell/token consumers."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.effects import (ChoiceOption, Damage, DestroyBatch, DrawToHandLimit,
    GainTemporaryMana, InvokeBehavior, RandomDamage, RequestChoice, ShuffleIntoDeck)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, Keyword, TargetSpec, Zone
from hs_sim.engine.pools import DiscoverFromPool, GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.sacrifice import MinionReference, live_minion
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import DeathQuery, Resurrect, death_candidates
from hs_sim.engine.zones import CardReference, ChooseFromZone, DiscardCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p62-v1.json'
BATCH_HASH = 'd21d17e033c8c7352ad62c99cda381e9d44f13c3b86fb8babd4262f2273dedac'
FRAME, TYPHOON, PRAYER, RITUAL, TICK, SANDS, COIN, STONE, TREANT, DRAGON, WHELP, RAPTOR = (
    'CAP_403', 'EDR_232', 'EDR_460t', 'EDR_461t', 'END_017t', 'TIME_EVENT_999t',
    'JAIL_504t2', 'TIME_852t3', 'END_009t', 'CATA_EVENT_110t6t', 'CATA_132t', 'TLC_101t')
ROOTS = (FRAME, TYPHOON, PRAYER, RITUAL, TICK, SANDS, COIN, STONE, TREANT, DRAGON, WHELP, RAPTOR)
PREFIX, POOL_ID = 'cards.simple_followup_p62.', 'constructed.cards'
DRAGONS = DeathQuery(cards=PoolQuery(kinds=(CardType.MINION,), tribes_any=('dragon',)))


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != ROOTS
            or any(d[k] for k in ('dependencies', 'existing_dependencies', 'skipped'))):
        raise TargetValidationError('P62 complete frozen scope changed')
    for x in d['cards'] + d['evidence_only']:
        if canonical_digest(x['record']) != x['record_sha256']:
            raise TargetValidationError('P62 complete original row changed')
    return d


def original_options(c, size=None):
    if c.choice is None or c.choice.selected_ids or size is not None and len(c.choice.choice.options) != size:
        raise ResolutionError('P62 automatic continuation lost its original finite material')
    return tuple(json.loads(o.id) for o in c.choice.choice.options)


def register_simple_followup_p62_cards(registry):
    d = load_batch()

    def frame(c):
        options = tuple(ChoiceOption(json.dumps(asdict(MinionReference.capture(c.state.entities[i])), sort_keys=True),
            'Original enemy minion') for i in minions(c, registry, 3-c.player_id))
        count = min(2, len(options))
        return (*((RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
            sample_size=count if len(options) > count else None, on_select=PREFIX + 'destroy_pair'),) if count else ()),
            InvokeBehavior(PREFIX + 'enemy_deck_top', c.source_id, c.player_id))

    def destroy_pair(c):
        refs = tuple(MinionReference(**row) for row in original_options(c))
        ids = tuple(ref.entity_id for ref in refs if ref.player_id == 3-c.player_id and live_minion(c.state, ref) is not None)
        return (DestroyBatch(ids, c.source_id),)

    def typhoon(c):
        refs = tuple(MinionReference.capture(c.state.entities[i]) for p in (1, 2) for i in minions(c, registry, p))
        return tuple(RequestChoice(c.player_id, (ChoiceOption(json.dumps(asdict(ref), sort_keys=True), 'Original minion'),),
            c.source_id, min_count=0, max_count=0, on_select=PREFIX + 'shuffle_ready') for ref in refs)

    def shuffle_ready(c):
        ref = MinionReference(**original_options(c, 1)[0])
        if live_minion(c.state, ref) is None: return ()
        options = tuple(ChoiceOption(json.dumps(dict(reference=asdict(ref), player=p), sort_keys=True), 'Deck recipient')
            for p in (1, 2))
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
            sample_size=1, on_select=PREFIX + 'shuffle_selected'),)

    def shuffle_selected(c):
        row = original_options(c, 1)[0]; ref = MinionReference(**row['reference']); player = row['player']
        if type(player) is not int or player not in (1, 2): raise ResolutionError('Invalid original shuffle recipient')
        if live_minion(c.state, ref) is None: return ()
        return shuffled(c, (ShuffleIntoDeck(ref.entity_id, player),), player_id=player)

    def empty_hand(c):
        refs = tuple(CardReference.capture(c.state.entities[i]) for i in c.state.players[3-c.player_id].hand)
        return tuple(DiscardCard(ref, c.source_id) for ref in refs)

    def coin(c):
        return (GainTemporaryMana(c.player_id, 1), InvokeBehavior(PREFIX + 'coin_damage', c.source_id, c.player_id))

    def stone(c):
        count = len(death_candidates(c.state, registry, c.player_id, DRAGONS, c.source_id))
        return (Resurrect(c.player_id, count, DRAGONS, selection='first', source_id=c.source_id,
            cause=SummonCause.capture(c)),) if count else ()

    bodies = {FRAME: frame, 'destroy_pair': destroy_pair,
        'enemy_deck_top': lambda c: (ChooseFromZone(c.player_id, 3-c.player_id, Zone.DECK,
            PoolQuery(kinds=(CardType.MINION,)), operation='top', distinct='entity', source_id=c.source_id,discovery=True),),
        TYPHOON: typhoon, 'shuffle_ready': shuffle_ready, 'shuffle_selected': shuffle_selected,
        PRAYER: lambda c: (Damage(c.target_id, 6, c.source_id, DamageKind.SPELL),),
        RITUAL: lambda c: (GenerateFromPool(c.player_id, POOL_ID, PoolQuery(kinds=(CardType.MINION,),
            collectible=True, min_cost=6, max_cost=6), count=2, source_id=c.source_id, destination='board',
            cause=SummonCause.capture(c)),), TICK: lambda c: (DrawToHandLimit(c.player_id),), 'empty_hand': empty_hand,
        SANDS: lambda c: (DiscoverFromPool(c.player_id, POOL_ID, PoolQuery(kinds=(CardType.SPELL,),
            collectible=True, class_mode='current', include_neutral=False), source_id=c.source_id),),
        COIN: coin, 'coin_damage': lambda c: (RandomDamage(minions(c, registry, 3-c.player_id), 2,
            c.source_id, DamageKind.SPELL),), STONE: stone}
    for name, body in bodies.items(): registry.register_behavior(PREFIX + name, body)
    for row in d['cards']:
        raw = row['record']; cid = raw['id']; kind = CardType(raw['type'].lower()); kw = {}
        if kind == CardType.SPELL: kw['on_play'] = PREFIX + cid
        if cid == PRAYER: kw.update(keywords=(Keyword.LIFESTEAL,), targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)))
        if cid == TICK: kw.update(battlecry=PREFIX + cid, deathrattle=PREFIX + 'empty_hand')
        if cid == WHELP: kw['keywords'] = (Keyword.TAUNT,)
        if cid == RAPTOR: kw['keywords'] = (Keyword.RUSH,)
        cost = raw['cost'] if raw['cost'] is not None else d['numeric_normalizations'][cid]['cost']
        card = CardDefinition(cid, raw['name'], kind, cost=cost,
            attack=raw['attack'] if kind == CardType.MINION else 0,
            health=raw['health'] if kind == CardType.MINION else 0,
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')), metadata=metadata_from_record(raw), **kw)
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
