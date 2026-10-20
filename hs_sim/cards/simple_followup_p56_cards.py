"""Native physical choices, actual deaths/resources, removal and opening copies."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.copy_materials import CapturedCardCopyMaterial
from hs_sim.engine.dark_gift_generation import DiscoverDarkGift
from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.effects import ChoiceOption, RequestChoice, SpendResource
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardClass, CardDefinition, CardType, ChoicePurpose, HandActionSpec, Keyword,
    OpeningHook, Rarity, Resource, SpellSchool, TargetMode, TargetSpec, Zone)
from hs_sim.engine.nondeath_removal import RemoveFromGame
from hs_sim.engine.pools import DiscoverFromPool, GenerateFromPool, PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.resource_operations import SpendUpToResource
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_history import CastFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import DeathQuery, ResurrectMinion, death_candidates
from hs_sim.engine.targeting import target_choices
from hs_sim.engine.zones import ChooseFromZone, CopyCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p56-v1.json'
BATCH_HASH = '3a8c085bf08d8165d42e7ba8baa4f17bd89b67f33207310b993fa7dc5ee230c7'
DEJA = 'TIME_039'
FATE = 'TIME_432'
YSONDRE = 'EDR_465'
MADNESS = 'EDR_455'
RITE = 'EDR_811'
FARM = 'CORE_WW_374'
TWO = 'TLC_452t21'
ALL = 'TLC_452t29'
IMPROVISER = 'JAIL_321'
HOGGER = 'JAIL_384'
ROOTS = (DEJA, FATE, YSONDRE, MADNESS, RITE, FARM, TWO, ALL, IMPROVISER, HOGGER)
PARENT = 'TLC_452'
PREFIX = 'cards.simple_followup_p56.'
POOL_ID = 'constructed.cards'
DRAGONS = PoolQuery(kinds=(CardType.MINION,), collectible=True, tribes_any=('dragon',))
UNDEAD = PoolQuery(kinds=(CardType.MINION,), collectible=True, tribes_any=('undead',))
SECRETS = PoolQuery(kinds=(CardType.SPELL,), collectible=True, class_mode='specified',
    classes=(CardClass.MAGE,), include_neutral=False, keywords_all=(Keyword.SECRET,))


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != ROOTS
            or tuple(x['record']['id'] for x in data['evidence_only']) != (PARENT,)
            or any(data[k] for k in ('dependencies', 'existing_dependencies', 'skipped'))):
        raise TargetValidationError('P56 complete physical/death/resource/opening scope changed')
    for row in data['cards'] + data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('P56 complete original source row changed')
    return data


def register_simple_followup_p56_cards(registry):
    def copy_zone(c, owner, zone):
        return ChooseFromZone(c.player_id, owner, zone, operation='copy_current', distinct='card', source_id=c.source_id,discovery=True)

    def ysondre(c):
        count = sum(d.card_id == YSONDRE for d in death_candidates(c.state, registry, c.player_id, source_id=c.source_id))
        return (GenerateFromPool(c.player_id, POOL_ID, DRAGONS, count=count, source_id=c.source_id,
            destination='board', cause=SummonCause.capture(c)),) if count else ()

    def madness(c):
        records = death_candidates(c.state, registry, c.player_id,
            DeathQuery(cards=PoolQuery(tribes_any=('dragon',))), c.source_id)
        unique = {}
        for record in records:
            unique.setdefault(record.card_id, record)
        options = tuple(ChoiceOption(str(d.id), registry.card(d.card_id).name,
            (ResurrectMinion(c.player_id, d.id, source_id=c.source_id, cause=SummonCause.capture(c)),), card_id=d.card_id)
            for d in unique.values())
        return (RequestChoice(c.player_id, options, c.source_id, sample_size=min(3, len(options)),
            purpose=ChoicePurpose.CARD_DISCOVERY),) if options else ()

    def rite(c):
        return (SpendResource(c.player_id, Resource.CORPSES, 2,
            on_success=(DiscoverDarkGift(c.player_id, POOL_ID, UNDEAD, c.source_id),),
            on_failure=(DiscoverFromPool(c.player_id, POOL_ID, UNDEAD, source_id=c.source_id),)),)

    def farm(c):
        return (SpendUpToResource(c.player_id, Resource.CORPSES, 8, c.source_id, PREFIX + 'farm_result'),)

    def farm_result(c):
        result = c.resource_result
        if result is None or (result.player_id, result.resource, result.cap, result.source_id) != (
                c.player_id, Resource.CORPSES, 8, c.source_id):
            raise ResolutionError('Farm lost its complete original capped corpse result')
        cost = result.actual_amount
        return (SummonFromPool(c.player_id, POOL_ID, PoolQuery(kinds=(CardType.MINION,), collectible=True,
            min_cost=cost, max_cost=cost), source_id=c.source_id, cause=SummonCause.capture(c)),)

    def two(c):
        domain = replace(registry.card(TWO), targeting=TargetSpec(TargetMode.IF_AVAILABLE,
            zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='enemy'))
        ids = tuple(i for i in target_choices(c.state, registry, c.source, domain) if i is not None)
        options = tuple(ChoiceOption(json.dumps(asdict(MinionReference.capture(c.state.entities[i])), sort_keys=True),
            registry.card(c.state.entities[i].card_id).name, entity_id=i) for i in ids)
        amount = min(2, len(options))
        return (RequestChoice(c.player_id, options, c.source_id, min_count=amount, max_count=amount,
            on_select=PREFIX + 'remove_selected',targeting=domain.targeting),) if amount else ()

    def remove_selected(c):
        if c.choice is None:
            raise ResolutionError('Remove-two requires its original complete selection')
        refs = tuple(MinionReference(**json.loads(key)) for key in c.choice.selected_ids)
        return (RemoveFromGame(refs, c.source_id),)

    def all_others(c):
        refs = tuple(MinionReference.capture(c.state.entities[i]) for player in (1, 2)
            for i in c.state.players[player].board if i != c.source_id and c.state.entities[i].kind == CardType.MINION)
        return (RemoveFromGame(refs, c.source_id),)

    def improviser(c):
        matched = any(d.player_id == c.player_id and d.turn == c.state.turn and d.completed and
            d.payload_started and not d.interrupted and d.failure is None for d in c.state.cast_history)
        return (CastFromPool(c.player_id, POOL_ID, SECRETS, count=2, source_id=c.source_id),) if matched else ()

    def hogger(c):
        entries = []
        for i in tuple(c.state.players[c.player_id].deck):
            entity = c.state.entities[i]
            if i == c.source_id:
                continue
            card = registry.card(entity.card_id)
            if card.metadata is None or card.metadata.rarity is None:
                raise ResolutionError('Hogger requires known Legendary qualification for every physical deck card')
            if card.metadata.rarity == Rarity.LEGENDARY:
                entries.append(CopyCard(CapturedCardCopyMaterial.capture(c.state, entity), c.player_id,
                    destination=Zone.DECK, mode='current', source_id=c.source_id))
        return shuffled(c, entries)

    bodies = {DEJA: lambda c: (copy_zone(c, 3-c.player_id, Zone.HAND),),
        FATE: lambda c: (copy_zone(c, c.player_id, Zone.DECK), copy_zone(c, 3-c.player_id, Zone.DECK)),
        YSONDRE: ysondre, MADNESS: madness, RITE: rite, FARM: farm, 'farm_result': farm_result,
        TWO: two, 'remove_selected': remove_selected, ALL: all_others, IMPROVISER: improviser, HOGGER: hogger}
    for name, body in bodies.items():
        registry.register_behavior(PREFIX + name, body)
    for row in load_batch()['cards']:
        raw = row['record'];cid = raw['id'];kind = CardType(raw['type'].lower());kwargs = {}
        if kind == CardType.SPELL:
            kwargs['on_play'] = PREFIX + cid
        if cid in (TWO, ALL, IMPROVISER):
            kwargs['battlecry'] = PREFIX + cid
        if cid in (YSONDRE, HOGGER):
            kwargs['keywords'] = (Keyword.TAUNT,)
        if cid == YSONDRE:
            kwargs['deathrattle'] = PREFIX + cid
        if cid == HOGGER:
            kwargs['opening_hooks'] = (OpeningHook('before_deal', PREFIX + cid),)
        if cid == IMPROVISER:
            kwargs['hand_actions'] = (HandActionSpec('prepare', 'prepare', 1),)
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'],
            attack=raw['attack'] if kind == CardType.MINION else 0, health=raw['health'] if kind == CardType.MINION else 0,
            spell_school=SpellSchool.SHADOW if cid == RITE else None, metadata=metadata_from_record(raw), **kwargs)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
