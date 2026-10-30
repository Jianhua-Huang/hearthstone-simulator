"""Real past Legendary named bodies compose shared creation, death and health requests."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.effects import AddToHand,ChoiceOption,Damage,DamageBatch,Heal,HealBatch,RandomDamage
from hs_sim.engine.deathrattles import record as deathrattle_record
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,HealingKind,Keyword
from hs_sim.engine.ordered_group_batches import FillBoardWithCard
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.random_effect_choices import ChooseRandomEffects
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.summon_sources import DeathQuery,death_candidates
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position,minions

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-legendary-named-bodies-v1.json'
BATCH_HASH='0de5bbcf165ad45fa401a7def2abb3654bd8db7914dfd732dd8175de3f133f4d'
ROOTS=('AT_123','CFM_341','EX1_014','EX1_116','EX1_562','BOT_034','GVG_110','DAL_554','DAL_581','ETC_526','FP1_014','FP1_015')
DEPENDENCIES=('EX1_116t','ds1_whelptoken','GVG_110t','DAL_554t','ETC_526t','FP1_014t')
PREFIX='cards.past_legendary_named.'
BATTLECRIES=frozenset(ROOTS[2:9])
DEATHRATTLES=frozenset((*ROOTS[:2],*ROOTS[9:],'GVG_110t'))
LINKS={'EX1_014':'EX1_014t','EX1_116':'EX1_116t','EX1_562':'ds1_whelptoken','BOT_034':'BOT_031',
    'GVG_110':'GVG_110t','DAL_554':'DAL_554t','ETC_526':'ETC_526t'}
KEYWORDS={'AT_123':(Keyword.TAUNT,),'EX1_116':(Keyword.CHARGE,),'ETC_526t':(Keyword.CHARGE,Keyword.TAUNT)}


def make_definition(raw):
    cid=raw['id'];root=cid in ROOTS
    if (cid not in(*ROOTS,*DEPENDENCIES)or raw['type']!='MINION'or raw['collectible']is not root or
            root and raw['tags'].get('RARITY')!=5 or any(type(raw[k])is not int for k in('cost','attack','health'))):
        raise TargetValidationError('Named Legendary bodies require their complete original roots and actual dependency faces')
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        keywords=KEYWORDS.get(cid,()),battlecry=PREFIX+cid if cid in BATTLECRIES else None,
        deathrattle=PREFIX+cid if cid in DEATHRATTLES else None,metadata=metadata_from_record(raw))


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-past-Legendary-named-bodies-v1'or
            tuple(x['record']['id']for x in d['cards'])!=ROOTS or tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            [x['record']['id']for x in d['existing_dependencies']]!=['EX1_014t','BOT_031','TIME_013']or
            [x['record']['id']for x in d['evidence_only']]!=['MIS_701']or len(d['official_observations'])!=28 or
            any(d[k]for k in('complete_past_legendary_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Named bodies lost full original roles or declared a partial source complete')
    all_rows={row['record']['id']:row['record']for key in('cards','dependencies','existing_dependencies','evidence_only')for row in d[key]}
    for key in('cards','dependencies','existing_dependencies','evidence_only'):
        if any(canonical_digest(x['record'])!=x['record_sha256']for x in d[key]):raise TargetValidationError('Named body lost a complete original row')
    if any(all_rows[cid]['tags'].get('COLLECTION_RELATED_CARD_DATABASE_ID')!=all_rows[token]['dbf_id']for cid,token in LINKS.items()):
        raise TargetValidationError('Named body changed an actual client-linked generated identity')
    p=(ROOT/d['full_reference_document']).resolve()
    if not p.is_relative_to(ROOT)or hashlib.sha256(p.read_bytes()).hexdigest()!=d['full_reference_sha256']:
        raise TargetValidationError('Named bodies changed the complete original past reference')
    ref=json.loads(p.read_text(encoding='utf8'));records={x['record']['id']:x['record']for x in ref['candidate_records']}
    if len(ref['candidate_ids'])!=732 or d['original_candidate_ids']!=ref['candidate_ids']or any(x['record']!=records[x['record']['id']]for x in d['cards']):
        raise TargetValidationError('Named bodies cropped full original membership or root rows')
    return d


def register_past_legendary_named_bodies(registry):
    d=load_batch();prepared=[]
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']:
            raise TargetValidationError('Named bodies cannot replace or change existing native definitions')
        registry._validate_card(card)
        if card.id in registry.pool_cards and registry.pool_card(card.id)!=PoolCard.from_definition(card):
            raise TargetValidationError('Named bodies changed existing complete metadata')
        prepared.append(card)
    def named(c,card_id,count=1,player=None):
        position=deathrattle_position(c)if c.deathrattle is not None else None
        request=SummonByCard(c.player_id if player is None else player,(SummonEntryMaterial(card_id),),SummonCause.capture(c),position=position)
        return(request,)*count
    def chillmaw(c):
        if not any(c.state.entities[i].kind==CardType.MINION and has_any_tribe(registry,c.state.entities[i],('dragon',))for i in c.state.players[c.player_id].hand):return()
        return(DamageBatch(tuple(Damage(i,3,c.source_id,DamageKind.MINION_ABILITY)for p in(1,2)for i in minions(c,registry,p))),)
    def sally(c):
        row=None if c.deathrattle is None else deathrattle_record(c.state,c.deathrattle.id)
        if row is None or row.capture!=c.deathrattle:
            raise UnsupportedDefinitionError('Sergeant Sally requires her original Deathrattle callback')
        # First invocations retain the original captured callback window; repeated
        # activations get a fresh context from the common Deathrattle interpreter.
        attack=max(0,c.death.attack if c.death is not None else c.source.attack)
        return(DamageBatch(tuple(Damage(i,attack,c.source_id,DamageKind.MINION_ABILITY)for i in minions(c,registry,3-c.player_id))),)
    def boom(c):
        enemy=c.state.players[3-c.player_id];ids=(*((enemy.hero_id,)if c.state.entities[enemy.hero_id].health>0 else()),*minions(c,registry,3-c.player_id))
        if not ids:return()
        return(ChooseRandomEffects(c.player_id,c.source_id,tuple(ChoiceOption(str(n),str(n),
            (RandomDamage(ids,n,c.source_id,DamageKind.MINION_ABILITY),))for n in range(1,5))),)
    def counterpart(c,other):
        present=death_candidates(c.state,registry,c.player_id,DeathQuery(side='both',cards=PoolQuery(card_ids=(other,))),c.source_id)
        return named(c,'FP1_014t')if present else()
    bodies={
        'AT_123':chillmaw,'CFM_341':sally,
        'EX1_014':lambda c:tuple(AddToHand(3-c.player_id,'EX1_014t',c.source_id,revealed_to=(c.player_id,))for _ in range(2)),
        'EX1_116':lambda c:named(c,'EX1_116t',2,3-c.player_id),
        'EX1_562':lambda c:(FillBoardWithCard(c.player_id,'ds1_whelptoken',SummonCause.capture(c)),),
        'BOT_034':lambda c:named(c,'BOT_031',4),'GVG_110':lambda c:named(c,'GVG_110t',2),
        'DAL_554':lambda c:named(c,'DAL_554t',6)if not c.state.players[c.player_id].deck else(),
        'DAL_581':lambda c:(HealBatch(tuple(Heal(c.state.players[p].hero_id,c.state.entities[c.state.players[p].hero_id].max_health,
            c.source_id,HealingKind.EFFECT)for p in(1,2))),),
        'ETC_526':lambda c:named(c,'ETC_526t'),'FP1_014':lambda c:counterpart(c,'FP1_015'),
        'FP1_015':lambda c:counterpart(c,'FP1_014'),'GVG_110t':boom,
    }
    for cid,body in bodies.items():registry.register_behavior(PREFIX+cid,body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
