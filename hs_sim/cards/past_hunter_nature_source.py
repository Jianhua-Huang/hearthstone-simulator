"""Complete original Hunter Nature source, death offers and named Wildseeds."""
from dataclasses import asdict,replace
import hashlib,json
from pathlib import Path

from hs_sim.engine.decreasing_spell_damage import DecreasingRandomSpellDamage
from hs_sim.engine.dormancy import AdvanceCapturedDormancy
from hs_sim.engine.effects import ChoiceOption,EquipWeapon,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.generation_scopes import GenerationScope,pool_digest
from hs_sim.engine.model import CardClass,CardDefinition,CardType,ChoicePurpose,Keyword,SpellSchool
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolDefinition,PoolMember,PoolQuery,resolve_candidates
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import DeathQuery,ResurrectMinion,death_candidates
from hs_sim.targets import TargetValidationError,canonical_digest
from . import past_priest_nature_source as reference
from .metadata import metadata_from_record
from .simple_followup_p89_cards import WO,QUERIES,HUNTER_NATURE_PAST_POOL

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-hunter-nature-source-v1.json'
BATCH_HASH='411e1e53b1fcf2d32c33e48ba436ba9b3ac82b9f3abdc4a5b77b863bc2902ff1'
POLICY='cn37-local-hunter-past-nature-v1'
ROOTS=('AV_333','REV_361','TID_075')
SEEDS=('REV_360t','REV_360t1','REV_360t2')
BOW='REV_360t4'
DEPENDENCIES=(*SEEDS,BOW)
MEMBERS=('AV_333','DRG_006','GVG_073','ICC_049','LOOT_080','OG_045','REV_361','TID_075','WON_306')
EXISTING=('DRG_006','GVG_073','ICC_049','LOOT_080','OG_045','WON_306','LOOT_080t2','LOOT_080t3','LOOT_077t',WO)
WILDSEED_POOL='constructed.local-wildseeds.hunter-reference-v1'
SEED_QUERY=PoolQuery(kinds=(CardType.MINION,),collectible=False)
BEAST_DEATHS=DeathQuery(cards=PoolQuery(kinds=(CardType.MINION,),tribes_any=('beast',)))
PREFIX='cards.past_hunter_nature_source.'


def make_definition(raw):
    cid=raw['id'];fields={};kind=CardType(raw['type'].lower())
    if cid not in ROOTS+DEPENDENCIES or raw['collectible']is not(cid in ROOTS):
        raise TargetValidationError('Hunter Nature requires its original complete native face roles')
    if cid in ROOTS:
        if kind!=CardType.SPELL or raw['cost']!=3 or raw['tags'].get('SPELL_SCHOOL')!=4:
            raise TargetValidationError('Hunter Nature requires its real three-cost Nature spells')
        fields.update(on_play=PREFIX+cid,spell_school=SpellSchool.NATURE)
    elif cid in SEEDS:
        stats=((1,3,1),(2,2,5),(3,5,4))[SEEDS.index(cid)]
        if kind!=CardType.MINION or (raw['cost'],raw['attack'],raw['health'])!=stats:
            raise TargetValidationError('Wildseed lost its original complete printed stats')
        fields.update(attack=raw['attack'],health=raw['health'],dormant_turns=SEEDS.index(cid)+1,
            keywords=(Keyword.RUSH,)if cid==SEEDS[0]else(Keyword.TAUNT,)if cid==SEEDS[1]else())
        if cid==SEEDS[2]:fields['on_awaken']=PREFIX+'bow'
    else:
        if kind!=CardType.WEAPON or (raw['cost'],raw['attack'],raw['health'])!=(3,4,2):
            raise TargetValidationError('Stag requires its actual 4/2 Wildbow')
        fields.update(attack=4,durability=2)
    return CardDefinition(cid,raw['name'],kind,cost=raw['cost'],metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'));prior=reference.load_batch()
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!=POLICY or
            tuple(v['record']['id']for v in d['cards'])!=ROOTS or
            tuple(v['record']['id']for v in d['dependencies'])!=DEPENDENCIES or
            tuple(v['record']['id']for v in d['existing_dependencies'])!=EXISTING or
            [v['record']['id']for v in d['evidence_only']]!=['REV_360te','REV_360t1e','REV_360t2e'] or
            len(d['official_observations'])!=34 or d['member_ids']!=list(MEMBERS) or d['seed_ids']!=list(SEEDS) or
            d['source_card_id']!=WO or d['pool_id']!=HUNTER_NATURE_PAST_POOL or d['wildseed_pool_id']!=WILDSEED_POOL or
            [v['card_id']for v in d['native_pins']]!=list(MEMBERS+DEPENDENCIES) or
            canonical_digest(d['query'])!=canonical_digest(asdict(QUERIES[WO])) or
            canonical_digest(d['seed_query'])!=canonical_digest(asdict(SEED_QUERY)) or
            any(d[k]for k in('new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Hunter Nature lost a complete source, seed role or original query')
    if (d['full_union_source_document']!=reference.BATCH_PATH.relative_to(ROOT).as_posix() or
            d['full_union_source_sha256']!=hashlib.sha256(reference.BATCH_PATH.read_bytes()).hexdigest()):
        raise TargetValidationError('Hunter Nature changed its original complete 174-row reference')
    for key in('cards','dependencies','existing_dependencies','evidence_only'):
        for row in d[key]:
            if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Hunter Nature lost a complete original row')
    derived=[v['record']['id']for v in prior['full_union_records']if
        CardClass.HUNTER in metadata_from_record(v['record']).classes or CardClass.NEUTRAL in metadata_from_record(v['record']).classes]
    if derived!=list(MEMBERS):raise TargetValidationError('Hunter Nature changed original class order or membership')
    return d


def register_past_hunter_nature_cards(registry):
    d=load_batch();prepared=[]
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']:
            raise TargetValidationError('Hunter Nature cannot replace or change an original face')
        registry._validate_card(card)
        if card.id in registry.pool_cards and registry.pool_card(card.id)!=PoolCard.from_definition(card):
            raise TargetValidationError('Hunter Nature changed an existing complete metadata row')
        prepared.append(card)

    def pet(c):
        deaths=death_candidates(c.state,registry,c.player_id,BEAST_DEATHS,c.source_id)
        distinct={}
        for death in deaths:distinct.setdefault(death.card_id,death)
        if not distinct:return()
        cause=SummonCause.capture(c)
        options=tuple(ChoiceOption('death-'+str(death.id),registry.card(death.card_id).name,
            (ResurrectMinion(c.player_id,death.id,source_id=c.source_id,cause=cause),),card_id=death.card_id)
            for death in distinct.values())
        return(RequestChoice(c.player_id,options,c.source_id,prompt='发现并复活一只野兽',
            sample_size=min(3,len(options)),purpose=ChoicePurpose.CARD_DISCOVERY),)

    def spirits(c):
        return(GenerateFromPool(c.player_id,WILDSEED_POOL,SEED_QUERY,2,source_id=c.source_id,
            replacement=False,destination='board',cause=SummonCause.capture(c)),
            InvokeBehavior(PREFIX+'advance',c.source_id,c.player_id))

    def advance(c):
        captured=tuple((MinionReference.capture(e),e.dormancy.id)
            for eid in c.state.players[c.player_id].board if(e:=c.state.entities[eid]).card_id in SEEDS
            and e.dormancy is not None and e.kind==CardType.MINION and e.health>0 and not e.doomed)
        return tuple(AdvanceCapturedDormancy(ref,dormancy_id,1,c.source_id)for ref,dormancy_id in captured)

    def shell(c):
        if c.cast is None or (c.cast.source_id,c.cast.player_id)!=(c.source_id,c.player_id):
            raise ResolutionError('Shellshot requires its actual original CAST')
        return(DecreasingRandomSpellDamage(c.player_id,c.cast.id,c.source_id),)

    for name,body in(('AV_333',pet),('REV_361',spirits),('TID_075',shell),('advance',advance),
            ('bow',lambda c:(EquipWeapon(c.player_id,BOW),))):registry.register_behavior(PREFIX+name,body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))


def checked_native(registry,d):
    for row in d['native_pins']:
        cid=row['card_id']
        if (canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256'] or
                canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']):
            raise TargetValidationError('Hunter Nature lost a complete executable member: '+cid)
    for row in d['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id'])))!=row['definition_sha256']:
            raise TargetValidationError('Hunter Nature changed an earlier native dependency')


def local_pools(registry,context):
    d=load_batch();checked_native(registry,d)
    return tuple(PoolDefinition(pid,version,context.target_id,context.mode,
        tuple(PoolMember(cid)for cid in members),complete=True)for pid,version,members in
        ((HUNTER_NATURE_PAST_POOL,POLICY,MEMBERS),(WILDSEED_POOL,POLICY+':wildseeds',SEEDS)))


def register_scopes(registry,context):
    expected=local_pools(registry,context);prepared=[]
    for pool,source,cls,query in((expected[0],WO,CardClass.HUNTER,QUERIES[WO]),
            (expected[1],'REV_361',None,SEED_QUERY)):
        actual=registry.pool(pool.id,context)
        if actual!=replace(pool,version=context.target_id+':'+pool.version):
            raise TargetValidationError('Hunter source cannot borrow, crop, reorder or reweight a complete pool')
        prepared.append(GenerationScope(POLICY+':'+source+':'+str(cls)+':'+context.target_id,
            pool.id,context.target_id,context.mode,source,cls,query,pool_digest(actual)))
        members=resolve_candidates(registry,context,pool.id,query,current_class=CardClass.HUNTER,
            source_card_id=source,exclude_source_by_rule=True)
        if [m.card_id for m in members]!=[m.card_id for m in pool.members]or any(m.weight!=1 for m in members):
            raise TargetValidationError('Hunter source changed its complete actual candidate order or weights')
    for scope in prepared:registry.register_generation_scope(scope)
