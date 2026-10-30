"""Complete original Spare Part rewards, fixed transforms and named mine/gnome."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.effects import ChoiceOption,Damage
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,CastWhenDrawnSpec,DamageKind,Keyword,TriggerSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.random_effect_choices import ChooseRandomEffects
from hs_sim.engine.sacrifice import MinionReference,TransformCapturedMinion
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import AddToDeck
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import minions
from .simple_followup_p93_cards import GNOME,SPARES,PREFIX as SPARE_PREFIX

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-fixed-parts-mines-v1.json'
BATCH_HASH='dbded756b4038d46aa02490aae5a43e55f0240e5379a754e8db08bd0401487a2'
TOSHLEY,TINKMASTER,JUGGERNAUT,THERMAPLUGG,WON_JUGGERNAUT=ROOTS=(
    'GVG_115','EX1_083','GVG_056','GVG_116','WON_114')
DEVILSAUR,SQUIRREL,MINE=DEPENDENCIES=('EX1_tk29','EX1_tk28','GVG_056t')
FORMS=(DEVILSAUR,SQUIRREL)
LEPER='EX1_029'
PREFIX='cards.past_fixed_parts.'
PART_BODY=SPARE_PREFIX+GNOME


def make_definition(raw):
    cid=raw['id'];fields={}
    if cid not in(*ROOTS,*DEPENDENCIES)or type(raw['cost'])is not int:
        raise TargetValidationError('Fixed original rewards require their complete original identities and costs')
    if cid in ROOTS:
        if raw['type']!='MINION'or not raw['collectible']or raw['tags'].get('RARITY')!=5:
            raise TargetValidationError('Fixed reward parent requires its complete original Legendary body')
        if cid==TOSHLEY:fields.update(battlecry=PART_BODY,deathrattle=PART_BODY)
        elif cid==TINKMASTER:fields['battlecry']=PREFIX+'tinkmaster'
        elif cid in(JUGGERNAUT,WON_JUGGERNAUT):fields.update(battlecry=PREFIX+'shuffle',deathrattle=PREFIX+'shuffle')
        else:fields['triggers']=(TriggerSpec('minion_died',PREFIX+'thermaplugg'),)
    elif cid in FORMS:
        if raw['type']!='MINION'or raw['collectible']or raw['text']or raw['text_en']:
            raise TargetValidationError('Fixed transform requires its actual complete vanilla Beast face')
    else:
        if raw['type']!='SPELL'or raw['collectible']or raw['tags'].get('CASTS_WHEN_DRAWN')!=1:
            raise TargetValidationError('Mine requires its complete original drawn-spell declaration')
        return CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],on_play=PREFIX+'mine',
            keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec(),metadata=metadata_from_record(raw))
    if any(type(raw[k])is not int for k in('attack','health')):
        raise TargetValidationError('Fixed reward minion requires original integer printed stats')
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-past-fixed-parts-mines-v1'or
            tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            tuple(x['record']['id']for x in d['existing_dependencies'])!=SPARES+(LEPER,GNOME,'TIME_013')or
            [x['record']['id']for x in d['evidence_only']]!=['MIS_701']or len(d['official_observations'])!=24 or
            d['member_ids']!=list(SPARES)or d['member_weights']!=[1]*7 or
            any(d[k]for k in('complete_past_legendary_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Fixed rewards lost complete original identities, roles or seven-part recipe')
    all_rows={x['record']['id']:x['record']for key in('cards','dependencies','existing_dependencies','evidence_only')for x in d[key]}
    for key in('cards','dependencies','existing_dependencies','evidence_only'):
        if any(canonical_digest(x['record'])!=x['record_sha256']for x in d[key]):
            raise TargetValidationError('Fixed rewards changed a complete original row')
    for parent,child in((JUGGERNAUT,MINE),(WON_JUGGERNAUT,MINE),(THERMAPLUGG,LEPER)):
        if all_rows[parent]['tags'].get('COLLECTION_RELATED_CARD_DATABASE_ID')!=all_rows[child]['dbf_id']:
            raise TargetValidationError('Fixed rewards lost an actual original client child identity')
    for cid,members in((TOSHLEY,SPARES),(TINKMASTER,FORMS),(JUGGERNAUT,(MINE,))):
        faces=[x['face']for x in d['official_observations']if x['card_id']==cid]
        if len(faces)!=2 or any(f['childIds']!=d['official_child_ids'][cid]or
                set(f['childIds'])!={all_rows[c]['dbf_id']for c in members}for f in faces):
            raise TargetValidationError('Fixed rewards lost the complete original parent child declarations')
    for entry in d['retained_documents'].values():
        p=(ROOT/entry['path']).resolve()
        if not p.is_relative_to(ROOT)or hashlib.sha256(p.read_bytes()).hexdigest()!=entry['sha256']:
            raise TargetValidationError('Fixed rewards changed an original complete retained source')
    if d['retained_documents']['full_reference']!={'path':d['full_reference_document'],'sha256':d['full_reference_sha256']}:
        raise TargetValidationError('Fixed rewards lost the exact retained full-reference binding')
    ref=json.loads((ROOT/d['full_reference_document']).read_text(encoding='utf8'));records={x['record']['id']:x['record']for x in ref['candidate_records']}
    if(len(ref['candidate_ids'])!=732 or d['original_candidate_ids']!=ref['candidate_ids']or
            any(x['record']!=records[x['record']['id']]for x in d['cards'])):
        raise TargetValidationError('Fixed rewards cropped the complete original past domain')
    return d


def register_past_fixed_parts_mines(registry):
    d=load_batch();prepared=[]
    for row in d['existing_dependencies']:
        cid=row['record']['id']
        if cid=='TIME_013':continue
        if(canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or
                canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']):
            raise TargetValidationError('Fixed rewards require complete unchanged original Parts and Leper Gnome effects')
    if registry.card(GNOME).deathrattle!=PART_BODY:
        raise TargetValidationError('Toshley lost the actual original seven-Part producer')
    registry.behavior(PART_BODY)
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']:
            raise TargetValidationError('Fixed rewards cannot replace or alter an existing complete face')
        registry._validate_card(card)
        if card.id in registry.pool_cards and registry.pool_card(card.id)!=PoolCard.from_definition(card):
            raise TargetValidationError('Fixed rewards changed complete existing metadata')
        prepared.append(card)
    def tinkmaster(c):
        for cid in FORMS:registry.card(cid)
        refs=tuple(MinionReference.capture(c.state.entities[i])for p in(1,2)for i in minions(c,registry,p)if i!=c.source_id)
        options=tuple(ChoiceOption(str(ref.entity_id),'Original other minion',(
            ChooseRandomEffects(c.player_id,c.source_id,tuple(ChoiceOption(cid,registry.card(cid).name,
                (TransformCapturedMinion(ref,cid,c.source_id),))for cid in FORMS)),))for ref in refs)
        return(ChooseRandomEffects(c.player_id,c.source_id,options),)if options else()
    def mine(c):return(Damage(c.state.players[c.player_id].hero_id,10,c.source_id,DamageKind.SPELL),)
    def shuffle(c):return shuffled(c,(AddToDeck(3-c.player_id,MINE,source_id=c.source_id),),player_id=3-c.player_id)
    def thermaplugg(c):
        identity=dict(c.event.data)['death_id'];row=next((x for x in c.state.death_history if x.id==identity),None)
        if(row is None or(row.entity_id,row.entity_id,row.controller)!=(c.event.source_id,c.event.target_id,c.event.player_id)or
                row.zone!=Zone.BOARD or registry.card(row.card_id).kind!=CardType.MINION):
            raise ResolutionError('Thermaplugg lost its actual original physical minion death')
        return(SummonByCard(c.player_id,(SummonEntryMaterial(LEPER),),SummonCause.capture(c)),)if(
            row.controller!=c.player_id and living_source(c))else()
    for name,body in(('tinkmaster',tinkmaster),('mine',mine),('shuffle',shuffle),('thermaplugg',thermaplugg)):
        registry.register_behavior(PREFIX+name,body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
