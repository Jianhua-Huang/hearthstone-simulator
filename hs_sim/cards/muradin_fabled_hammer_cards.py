"""Muradin's real Fabled family over finite original-card consumption."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.deck_shuffles import ShuffleDeckCards
from hs_sim.engine.consumed_cards import ConsumptionProfile, ConsumeFabledWeapon, ResolveConsumedDeathrattle
from hs_sim.engine.fabled_decks import FabledSpec
from hs_sim.engine.growing_weapon_shuffles import ShuffleGrowingWeapon
from hs_sim.engine.model import CardDefinition,CardType,Keyword,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT='TIME_209';HAMMER='TIME_209t';AVATAR='TIME_209t2'
PREFIX='cards.muradin_fabled_hammer.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/muradin-fabled-hammer-v2.json'
BATCH_HASH='40f3f11efcdd4e81643bffad59f04dbf4987a7604626f31cd08b4db9245a3a45'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(r['record']['id']for r in d['cards'])!=(ROOT,)or tuple(r['record']['id']for r in d['dependencies'])!=(HAMMER,)
            or tuple(r['record']['id']for r in d['existing_dependencies'])!=(AVATAR,)
            or d['source_roots']
            or tuple(r['record']['id']for r in d['evidence_only'])!=('TIME_209e','TIME_209t2e')):
        raise TargetValidationError('Muradin family complete dependency source changed')
    for section in('cards','dependencies','existing_dependencies','evidence_only'):
        for row in d[section]:
            if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Muradin original complete row changed')
    return d


def register_muradin_fabled_hammer_cards(registry):
    def take(c):
        if c.source.zone != Zone.BOARD:
            return ()
        return (ConsumeFabledWeapon(MinionReference.capture(c.source), ROOT),)
    def payload(c):
        if c.deathrattle is None:
            raise ResolutionError('Muradin return requires its actual Deathrattle')
        if c.deathrattle.ability.consumed_card_id is None:
            return ()
        return (ResolveConsumedDeathrattle(c.deathrattle.id),)
    def shuffle(c):
        entity=c.state.entities.get(c.source_id)
        if entity is None or entity.kind!=CardType.WEAPON:raise ResolutionError('Hammer shuffle requires its actual physical weapon')
        death=c.death
        if death is None:raise ResolutionError('Hammer shuffle requires its actual original weapon death')
        if entity.zone!=Zone.GRAVEYARD or entity.zone_epoch!=death.cause.target_zone_epoch+1:return ()
        work=ShuffleGrowingWeapon(SourceAllocationFact.capture(c.state,entity),death,c.player_id,2,c.source_id)
        return (ShuffleDeckCards(c.player_id,c.player_id,(work,),c.source_id),)
    registry.register_behavior(PREFIX+'shuffle',shuffle)
    registry.register_behavior(PREFIX+'take',take)
    registry.register_behavior(PREFIX+'payload',payload)
    raw=load_batch()['dependencies'][0]['record']
    if(raw['type'],raw['cost'],raw['attack'],raw['health'])!=('WEAPON',6,3,4):raise TargetValidationError('Unexpected Hammer source face')
    card=CardDefinition(HAMMER,raw['name'],CardType.WEAPON,cost=6,attack=3,durability=4,keywords=(Keyword.WINDFURY,),
        deathrattle=PREFIX+'shuffle',metadata=replace(metadata_from_record(raw),deck_identity=HAMMER))
    registry.register_card(card)
    if HAMMER not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
    raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'])!=('MINION',5,3,2):
        raise TargetValidationError('Unexpected Muradin source face')
    card=CardDefinition(ROOT,raw['name'],CardType.MINION,cost=5,attack=3,health=2,
        keywords=(Keyword.RUSH,),battlecry=PREFIX+'take',deathrattle=PREFIX+'payload',
        metadata=replace(metadata_from_record(raw),deck_identity=ROOT))
    registry.register_card(card)
    if ROOT not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_fabled(FabledSpec(ROOT,(HAMMER,AVATAR)))
    registry.register_consumption_profile(ConsumptionProfile(ROOT,'fabled_weapon'))
