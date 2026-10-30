"""Five actual grant/transform consumers and their exact choice/token roles."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from hs_sim.engine.choose_one import normalize
from hs_sim.engine.cross_zone import TransformMinionIntoCopy
from hs_sim.engine.effects import ChoiceOption,DestroyBatch,GrantDeathrattle
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import (CardDefinition,CardType,ChooseBranch,ChooseOneSpec,Keyword,TargetMode,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.random_effect_choices import ChooseRandomEffects
from hs_sim.engine.sacrifice import BuffCapturedMinion,GrantCapturedDeathrattle,GrantCapturedKeyword,MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.target_predicates import TargetPredicateSpec
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .mimiron_reported_tech_cards import PREFIX as TECH_PREFIX
from .native_followup_cards import minions

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-native-grants-transforms-v1.json'
BATCH_HASH='8eb85be03688d8a3b60fbcd3e3e5544713320756d7ad1287ff4903ddb49ca039'
SHANDO,HEAD,TALRITHA,ROTGILL,INVINCIBLE=ROOTS=('SCH_607','GVG_111','DRG_235','RLK_550','RLK_592')
TOKEN,COPY_OPTION,BUFF_OPTION=DEPENDENCIES=('GVG_111t','SCH_607a','SCH_607b')
CHOICES=(COPY_OPTION,BUFF_OPTION)
EXISTING=()
EVIDENCE=('SCH_607e','DRG_235d','DRG_235e','RLK_550e','RLK_550e2','RLK_592e','MIS_701')
PREFIX='cards.past_native_grants.'
BEAST_RULE=TECH_PREFIX+'beast'  # Reuse only the exact generic current-Beast predicate.


def make_definition(raw):
    cid=raw['id'];kind=CardType(raw['type'].lower())
    if cid in CHOICES:
        if kind!=CardType.SPELL or raw['collectible']or type(raw['cost'])is not int:
            raise TargetValidationError('Native choice requires its complete original nonphysical display face')
        return CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],choice_only=True,metadata=metadata_from_record(raw))
    if cid not in(*ROOTS,TOKEN)or kind!=CardType.MINION or any(type(raw[k])is not int for k in('cost','attack','health')):
        raise TargetValidationError('Native grants lost an original complete physical minion face')
    fields={}
    if cid==SHANDO:
        targeting=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly')
        fields['choose_one']=ChooseOneSpec((ChooseBranch(BUFF_OPTION,'唤起兽群',PREFIX+'deck'),
            ChooseBranch(COPY_OPTION,'拟态变形',PREFIX+'copy',targeting=targeting,target_rule=BEAST_RULE)),
            ChooseBranch('both','两者兼得',PREFIX+'both',targeting=targeting,target_rule=BEAST_RULE))
    if cid==HEAD:fields['triggers']=(TriggerSpec('turn_started',PREFIX+cid),)
    if cid in(TALRITHA,INVINCIBLE):fields['deathrattle']=PREFIX+cid
    if cid in(ROTGILL,INVINCIBLE):fields['battlecry']=PREFIX+cid
    keys=(Keyword.CHARGE,Keyword.MEGA_WINDFURY)if cid==TOKEN else(Keyword.REBORN,)if cid==INVINCIBLE else()
    if cid==TOKEN and('超级风怒'not in raw['text']or raw['tags'].get('CHARGE')!=1):
        raise TargetValidationError('V-07-TR-0N lost its actual Charge/Mega-Windfury text')
    return normalize(CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        keywords=keys,metadata=metadata_from_record(raw),**fields))


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or d['existing_dependencies']or
            tuple(x['record']['id']for x in d['evidence_only'])!=EVIDENCE or
            len(d['official_observations'])!=14 or d['actual_choice_only_ids']!=list(CHOICES)or
            d['actual_physical_dependency_ids']!=[TOKEN]or
            any(d[k]for k in('complete_past_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Native grants lost full source roles or made a partial completeness claim')
    if any(canonical_digest(x['record'])!=x['record_sha256']for key in('cards','dependencies','evidence_only')for x in d[key]):
        raise TargetValidationError('Native grants changed an original complete raw row')
    path=ROOT/d['full_reference_document']
    if hashlib.sha256(path.read_bytes()).hexdigest()!=d['full_reference_sha256']:
        raise TargetValidationError('Native grants changed the complete original past reference')
    reference=json.loads(path.read_text(encoding='utf8'));rows={x['record']['id']:x['record']for x in reference['candidate_records']}
    if(len(reference['candidate_ids'])!=732 or d['original_candidate_ids']!=reference['candidate_ids']or
            any(x['record']!=rows[x['record']['id']]for x in d['cards'])):
        raise TargetValidationError('Native grants cropped the original complete past source')
    return d


def register_past_native_grants_transforms(registry):
    d=load_batch();predicate=registry.target_predicate(BEAST_RULE)
    if(predicate!=TargetPredicateSpec(BEAST_RULE,current_tribes_any=('beast',))or
            canonical_digest(asdict(predicate))!=d['reused_beast_predicate_sha256']):
        raise TargetValidationError('Native Choose One lost its original generic current-Beast predicate')
    prepared=[]
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                (not card.choice_only and canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256'])):
            raise TargetValidationError('Native grants cannot replace an existing original face')
        registry._validate_card(card);prepared.append(card)
    def deck(c):
        return tuple(BuffStoredCard(CardReference.capture(c.state.entities[i]),1,1,c.source_id)
            for i in tuple(c.state.players[c.player_id].deck)if c.state.entities[i].kind==CardType.MINION and
            has_any_tribe(registry,c.state.entities[i],('beast',),basis='current'))
    def copied(c):
        return()if c.target_id is None or not living_source(c)else(TransformMinionIntoCopy(
            MinionReference.capture(c.source),MinionReference.capture(c.state.entities[c.target_id]),c.source_id),)
    def head(c):
        if c.event.player_id!=c.player_id or not living_source(c):return()
        mechs=tuple(i for i in minions(c,registry,c.player_id)if has_any_tribe(registry,c.state.entities[i],('mech',),basis='current'))
        if len(mechs)<3:return()
        cause=SummonCause.capture(c);position=c.state.players[c.player_id].board.index(c.source_id)
        return(DestroyBatch(mechs,c.source_id),SummonByCard(c.player_id,(SummonEntryMaterial(TOKEN),),cause,position=position))
    def talritha(c):
        options=[]
        for i in tuple(c.state.players[c.player_id].hand):
            entity=c.state.entities[i]
            if entity.kind!=CardType.MINION or not has_any_tribe(registry,entity,('dragon',),basis='current'):continue
            ref=CardReference.capture(entity)
            options.append(ChoiceOption(str(i),registry.card(entity.card_id).name,(BuffStoredCard(ref,3,3,c.source_id),
                GrantDeathrattle(ref.entity_id,PREFIX+TALRITHA,c.source_id,stored_card=ref))))
        return(ChooseRandomEffects(c.player_id,c.source_id,tuple(options)),)if options else()
    def rotgill(c):
        return tuple(GrantCapturedDeathrattle(MinionReference.capture(c.state.entities[i]),PREFIX+'rotgill_death',c.source_id)
            for i in minions(c,registry,c.player_id)if i!=c.source_id)
    def rotgill_death(c):
        return tuple(BuffCapturedMinion(MinionReference.capture(c.state.entities[i]),1,1,c.source_id)
            for i in minions(c,registry,c.player_id))
    def invincible(c):
        refs=tuple(MinionReference.capture(c.state.entities[i])for i in minions(c,registry,c.player_id)
            if i!=c.source_id and has_any_tribe(registry,c.state.entities[i],('undead',),basis='current'))
        options=tuple(ChoiceOption(str(ref.entity_id),registry.card(ref.card_id).name,(
            BuffCapturedMinion(ref,5,5,c.source_id),GrantCapturedKeyword(ref,Keyword.TAUNT,c.source_id)))for ref in refs)
        return(ChooseRandomEffects(c.player_id,c.source_id,options),)if options else()
    bodies={'deck':deck,'copy':copied,'both':lambda c:(*deck(c),*copied(c)),HEAD:head,
        TALRITHA:talritha,ROTGILL:rotgill,'rotgill_death':rotgill_death,INVINCIBLE:invincible}
    for key,body in bodies.items():registry.register_behavior(PREFIX+key,body)
    for card in prepared:
        registry.register_card(card)
        if not card.choice_only:registry.register_pool_card(PoolCard.from_definition(card))
