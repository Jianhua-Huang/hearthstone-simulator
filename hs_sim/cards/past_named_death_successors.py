"""Four actual past deathrattles and their exact physical successors."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from hs_sim.engine.effects import EquipWeapon,RandomDamage,ReplaceHero,Transform
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,HandRepeatSpec,Keyword,TriggerSpec
from hs_sim.engine.ordered_group_batches import SummonOrderedGroup
from hs_sim.engine.ordered_summon_groups import OrderedGroupMember,OrderedSummonGroupSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import characters,deathrattle_position

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-named-death-successors-v1.json'
BATCH_HASH='8f08b321278433d9179b7f5e1f397d69e2a8fec5f942f1d408086f98ecd34d48'
SNIP,COOKIE,EXECUTUS,ALAR=ROOTS=('BOT_700','DED_522','BRM_027','BT_735')
MICRO,LADLE,RAGNAROS,POWER,ASHES=DEPENDENCIES=('BOT_312t','DED_522t','BRM_027h','BRM_027p','BT_735t')
EXISTING=()
EVIDENCE=('BOT_700e','BRM_027pH','MIS_701')
PREFIX='cards.past_named_death_successors.'
NORMALIZATIONS={'BRM_027h':{'cost':0},'BT_735t':{'attack':0}}
LINKS={SNIP:MICRO,COOKIE:LADLE,EXECUTUS:POWER,ALAR:ASHES}


def make_definition(raw):
    cid=raw['id'];kind=CardType(raw['type'].lower());fields={}
    if cid not in (*ROOTS,*DEPENDENCIES):raise TargetValidationError('Unassigned named death successor')
    if cid in ROOTS:fields['deathrattle']=PREFIX+cid
    if cid==SNIP:fields.update(keywords=(Keyword.MAGNETIC,Keyword.ECHO),magnetic_tribes=('mech',),hand_repeat=HandRepeatSpec())
    if cid in (COOKIE,LADLE):fields['keywords']=(Keyword.LIFESTEAL,)
    if cid==ASHES:fields['triggers']=(TriggerSpec('turn_started',PREFIX+'ashes'),)
    if cid==RAGNAROS:fields['initial_hero_power']=POWER
    if cid==POWER:fields['on_use']=PREFIX+'power'
    cost=NORMALIZATIONS.get(cid,{}).get('cost',raw['cost'])
    attack=NORMALIZATIONS.get(cid,{}).get('attack',raw['attack'])
    return CardDefinition(cid,raw['name'],kind,cost=cost,
        attack=attack if kind in (CardType.MINION,CardType.WEAPON) else 0,
        health=raw['health'] if kind in (CardType.MINION,CardType.HERO) else 0,
        durability=raw['health'] if kind==CardType.WEAPON else 0,metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or d['existing_dependencies'] or
            tuple(x['record']['id']for x in d['evidence_only'])!=EVIDENCE or d['numeric_normalizations']!=NORMALIZATIONS or
            len(d['official_observations'])!=20 or any(d[k]for k in ('complete_past_source_bound','new_standard_roots',
                'membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Named death successors changed their full source roles')
    rows={x['record']['id']:x['record']for key in ('cards','dependencies','evidence_only')for x in d[key]}
    if any(canonical_digest(x['record'])!=x['record_sha256']for key in ('cards','dependencies','evidence_only')for x in d[key]):
        raise TargetValidationError('Named death successors changed a complete original row')
    if any(rows[parent]['tags']['COLLECTION_RELATED_CARD_DATABASE_ID']!=rows[child]['dbf_id']for parent,child in LINKS.items()):
        raise TargetValidationError('Named death successors changed their actual client links')
    if rows[RAGNAROS]['tags']['HERO_POWER']!=rows[POWER]['dbf_id'] or rows[RAGNAROS]['health']!=8:
        raise TargetValidationError('Ragnaros lost the actual eight-health hero and normal power')
    if any(rows[cid]['collectible'] for cid in DEPENDENCIES):raise TargetValidationError('Named physical child gained constructed eligibility')
    path=ROOT/d['full_reference_document']
    if hashlib.sha256(path.read_bytes()).hexdigest()!=d['full_reference_sha256']:
        raise TargetValidationError('Named successors changed the complete past reference')
    ref=json.loads(path.read_text(encoding='utf8'));original={x['record']['id']:x['record']for x in ref['candidate_records']}
    if len(ref['candidate_ids'])!=732 or d['original_candidate_ids']!=ref['candidate_ids'] or any(rows[cid]!=original[cid]for cid in ROOTS):
        raise TargetValidationError('Named successors cropped their original full source')
    return d


def register_past_named_death_successors(registry):
    d=load_batch();prepared=[]
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if (card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256'] or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Named successor cannot replace an original full face')
        registry._validate_card(card);prepared.append(card)
    def microbots(c):
        position=deathrattle_position(c)
        members=tuple(OrderedGroupMember('micro-'+str(i),SummonEntryMaterial(MICRO),
            None if position is None else position+i)for i in range(2))
        return (SummonOrderedGroup(OrderedSummonGroupSpec(c.player_id,SummonCause.capture(c),members)),)
    registry.register_behavior(PREFIX+SNIP,microbots)
    registry.register_behavior(PREFIX+COOKIE,lambda c:(EquipWeapon(c.player_id,LADLE),))
    registry.register_behavior(PREFIX+EXECUTUS,lambda c:(ReplaceHero(c.player_id,RAGNAROS,hero_power_card_id=POWER,health=8),))
    registry.register_behavior(PREFIX+ALAR,lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(ASHES),),
        SummonCause.capture(c),position=deathrattle_position(c)),))
    registry.register_behavior(PREFIX+'ashes',lambda c:(Transform(c.source_id,ALAR),)
        if living_source(c) and c.event.player_id==c.player_id else ())
    registry.register_behavior(PREFIX+'power',lambda c:(RandomDamage(characters(c,registry,3-c.player_id),8,c.source_id,DamageKind.HERO_POWER),))
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
