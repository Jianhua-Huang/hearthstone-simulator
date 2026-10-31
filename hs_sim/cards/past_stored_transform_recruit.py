"""Original inventory transformations, ordered recruits and real native followups."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from hs_sim.engine.automatic_targets import PreferredMinionTarget
from hs_sim.engine.board_presence import capture_board_presence
from hs_sim.engine.costs import local_cost
from hs_sim.engine.deck_cost_order import OrderDeckByCost
from hs_sim.engine.deck_spell_casts import CastRandomDeckSpell
from hs_sim.engine.forced_attack_sequences import AttackRandomEnemyCharacter
from hs_sim.engine.model import (CardClass,CardDefinition,CardType,CostSpec,Keyword,LimitedTriggerSpec,
    Rarity,SummonStats,Zone)
from hs_sim.engine.named_summon_followups import original_named_reference
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.stored_pool_transforms import TransformStoredFromPool
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.summon_sources import DeathQuery,Resurrect,SummonFromZone,death_candidates
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.engine.zones import CardReference,ShuffleDeck
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-stored-transform-recruit-v1.json'
BATCH_HASH='aa5f5be651cd4c4610c38dd4bc73e022a8de021ddc90e1d332a976d4b844c381'
RAFAAM,LIAM,VOSS,POLKELT,PRESTOR,AVIANA,PIPSI,BASALEPH,ALURA,LILIAN=ROOTS=(
    'DAL_422','GIL_694','ICC_811','SCH_428','SW_078','TOY_806','TOY_812','RLK_832','SCH_141','SCH_426')
TOKEN='SCH_426t';DEPENDENCIES=(TOKEN,)
EVIDENCE=('MIS_701','SW_078e','SW_078e2','TOY_806e')
PREFIX='cards.past_stored_transform_recruit.'
POOL='constructed.cards'
LEGENDARY=PoolQuery(kinds=(CardType.MINION,),collectible=True,rarities=(Rarity.LEGENDARY,))
DRAGONS=PoolQuery(kinds=(CardType.MINION,),collectible=True,tribes_any=('dragon',))


def make_definition(raw):
    cid=raw['id']
    if cid not in ROOTS+DEPENDENCIES or raw['type']!='MINION':
        raise TargetValidationError('Stored consumers require complete original physical minion faces')
    extra={}
    if cid in(ROOTS[:6]+(BASALEPH,)):extra['battlecry']=PREFIX+cid
    if cid in(PIPSI,LILIAN):extra['deathrattle']=PREFIX+cid
    if cid==ALURA:extra['limited_triggers']=(LimitedTriggerSpec.spellburst(PREFIX+cid),)
    keywords=tuple(k for tag,k in(('TAUNT',Keyword.TAUNT),('STEALTH',Keyword.STEALTH),('SPELLBURST',Keyword.SPELLBURST))
        if raw['tags'].get(tag)==1)
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        keywords=keywords,metadata=metadata_from_record(raw),**extra)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or d['existing_dependencies']or
            tuple(x['record']['id']for x in d['evidence_only'])!=EVIDENCE or len(d['official_observations'])!=24 or
            any(d[k]for k in('complete_past_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Stored consumers lost complete original roles or explicit open boundaries')
    for row in d['cards']+d['dependencies']+d['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Changed full original stored-consumer row')
    for entry in d['retained_documents'].values():
        p=(ROOT/entry['path']).resolve()
        if not p.is_relative_to(ROOT)or hashlib.sha256(p.read_bytes()).hexdigest()!=entry['sha256']:
            raise TargetValidationError('Stored consumer lost its original complete reference')
    past=json.loads((ROOT/d['retained_documents']['past']['path']).read_text(encoding='utf8'))
    rows={x['record']['id']:x['record']for x in past['candidate_records']}
    if past['candidate_ids']!=d['original_candidate_ids']or len(d['original_candidate_ids'])!=732 or any(
            x['record']!=rows[x['record']['id']]for x in d['cards']):
        raise TargetValidationError('Stored consumers cropped or changed original past inventory')
    return d


def register_past_stored_transform_recruit(registry):
    d=load_batch();prepared=[]
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Stored consumer cannot change or replace an original physical face')
        registry._validate_card(card);prepared.append(card)
    def references(c,zone):
        return tuple(CardReference.capture(c.state.entities[i])for i in getattr(c.state.players[c.player_id],zone.value))
    def rafaam(c):return tuple(TransformStoredFromPool(ref,POOL,LEGENDARY,c.source_id)
        for zone in(Zone.HAND,Zone.DECK)for ref in references(c,zone))
    def liam(c):return tuple(TransformStoredFromPool(ref,POOL,LEGENDARY,c.source_id)
        for ref in references(c,Zone.DECK)if max(0,local_cost(c.state.entities[ref.entity_id])[0])==1)
    def voss(c):
        opponent=c.state.players[3-c.player_id].hero_class
        if opponent in(None,CardClass.NEUTRAL):raise UnsupportedDefinitionError('Voss requires the actual opponent playable class')
        query=PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='specified',classes=(opponent,),include_neutral=False)
        return tuple(TransformStoredFromPool(ref,POOL,query,c.source_id)for ref in references(c,Zone.HAND)
            if c.state.entities[ref.entity_id].kind==CardType.SPELL)
    def prestor(c):
        work=[]
        for ref in references(c,Zone.DECK):
            entity=c.state.entities[ref.entity_id]
            if entity.kind!=CardType.MINION:continue
            work.append(TransformStoredFromPool(ref,POOL,DRAGONS,c.source_id,
                retained_stats=SummonStats(attack=entity.attack,health=entity.max_health),
                retained_cost=max(0,local_cost(entity)[0])))
        return tuple(work)
    def aviana(c):
        return(GenerateFromPool(c.player_id,POOL,LEGENDARY,count=10,source_id=c.source_id,
            destination='deck',cost=CostSpec(set_to=1),shuffle_actor_id=c.player_id),ShuffleDeck(c.player_id))
    def basaleph(c):
        previous=next((row for row in reversed(c.state.owner_turn_history)if row.player_id==c.player_id and row.closed),None)
        query=DeathQuery(min_turn=1 if previous is None else previous.turn+1)
        ids=tuple(row.id for row in death_candidates(c.state,registry,c.player_id,query,c.source_id)
            if has_any_tribe(registry,row,('undead',),basis='current'))
        return()if not ids else(Resurrect(c.player_id,count=len(ids),query=query,selection='first',source_id=c.source_id,
            cause=SummonCause.capture(c),death_ids=ids),)
    def alura(c):return(CastRandomDeckSpell(c.player_id,None,c.source_id,
        PreferredMinionTarget(capture_board_presence(c.state,c.source_id))),)
    def lilian(c):return(SummonByCard(c.player_id,(SummonEntryMaterial(TOKEN,on_summon=PREFIX+'attack'),),SummonCause.capture(c)),)
    bodies={RAFAAM:rafaam,LIAM:liam,VOSS:voss,POLKELT:lambda c:(OrderDeckByCost(c.player_id,c.source_id),),
        PRESTOR:prestor,AVIANA:aviana,
        PIPSI:lambda c:tuple(SummonFromZone(c.player_id,query=PoolQuery(kinds=(CardType.MINION,),keywords_all=(keyword,)),
            source_id=c.source_id,cause=SummonCause.capture(c))for keyword in(Keyword.DIVINE_SHIELD,Keyword.RUSH,Keyword.TAUNT)),
        BASALEPH:basaleph,ALURA:alura,LILIAN:lilian,
        'attack':lambda c:(AttackRandomEnemyCharacter(original_named_reference(c),c.player_id,c.source_id),)}
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
