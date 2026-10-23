"""Independent printed query fields for the fixed, non-formal candidate inventory."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.model import CardType,Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record,validate_race_pin

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/candidate-generation-catalog-v1.json'
BATCH_HASH='38cd8f1fb59d8e03b4e818d5d984d095530623739cb13f80ac83756928c514fc'
COST_PATH=ROOT/'data/cards/candidate-printed-cost-evidence-v1.json'
COST_HASH='81830c992ae467457070603209b2fe1b82c4510362e16514ec0323642a12d0e3'
ATTACK_PATH=ROOT/'data/cards/candidate-printed-attack-evidence-v1.json'
ATTACK_HASH='8e053c08699ab586306bb74c074db9559d48067fc88b803ded1393ee925ba125'
POLICY_PATH=ROOT/'data/cards/standard-candidate-policy-cn37-20261015.json'
NATIVE_GENERATION_EXCLUSIONS=('CATA_EVENT_110','JAIL_500','JAIL_831')
KEYWORD_TAGS=('CHARGE','COLOSSAL','COMBO','DIVINE_SHIELD','ELUSIVE','HERALD','LIFESTEAL',
 'OUTCAST','POISONOUS','QUEST','REBORN','REWIND','RUSH','SECRET','SHATTER','STEALTH','TAUNT','WINDFURY')


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:
        raise TargetValidationError('Unreviewed independent candidate generation catalog')
    ids=tuple(row['record']['id']for row in data['cards'])
    if(len(ids)!=1188 or len(set(ids))!=1188 or ids!=tuple(data['candidate_root_ids'])or
            not set(NATIVE_GENERATION_EXCLUSIONS)<=set(ids)or
            tuple(data['keyword_tags'])!=KEYWORD_TAGS or data['printed_keyword_overrides']!={'JAIL_890':['taunt'],'MEND_303':['taunt']}):
        raise TargetValidationError('Candidate catalog lost its complete fixed source scope')
    if data['policy']!=json.loads(POLICY_PATH.read_text(encoding='utf-8')):
        raise TargetValidationError('Candidate catalog differs from the fixed candidate policy')
    for row in data['cards']:
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('Candidate catalog requires complete original source rows')
    return data


def reviewed_zero_costs():
    data=json.loads(COST_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=COST_HASH or len(data['cards'])!=8:
        raise TargetValidationError('Unreviewed absent printed cost evidence')
    result={}
    for row in data['cards']:
        raw=row['record'];cid=raw['id']
        faces=[o['face']for o in data['official_observations']['observations']if o['card_id']==cid]
        if(cid in result or raw['cost']is not None or 'COST'in raw['tags']or row['reviewed_cost']!=0 or
                canonical_digest(raw)!=row['record_sha256']or len(faces)!=2 or any(f['manaCost']!=0 for f in faces)):
            raise TargetValidationError('Absent printed cost requires individual complete zero-cost evidence')
        result[cid]=row
    return result


def reviewed_zero_attacks():
    data=json.loads(ATTACK_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=ATTACK_HASH or len(data['cards'])!=17:
        raise TargetValidationError('Unreviewed absent printed minion attack evidence')
    result={}
    for item in data['cards']:
        raw=item['record'];cid=raw['id']
        faces=[o for o in data['official_observations']if o['card_id']==cid]
        if (cid in result or raw['type']!='MINION' or raw['attack']is not None or 'ATK'in raw['tags']or
                type(item['reviewed_attack'])is not int or item['reviewed_attack']!=0 or
                canonical_digest(raw)!=item['record_sha256']or len(faces)!=2 or
                {o['locale']for o in faces}!={'zh_CN','en_US'}or any(
                    o['face']['id']!=raw['dbf_id']or o['face']['cardTypeId']!=4 or
                    type(o['face'].get('attack'))is not int or o['face']['attack']!=0 or
                    o['face']['name']!=raw['name'if o['locale']=='zh_CN'else'name_en']for o in faces)):
            raise TargetValidationError('Absent attack requires individual complete zero-attack faces')
        result[cid]=item
    return result


def candidate_pool_rows(*, batch=None, zero_costs=None, zero_attacks=None, keyword_tags=KEYWORD_TAGS):
    """Compile metadata without consulting executable coverage or card text."""
    validate_race_pin()
    data=load_batch() if batch is None else batch
    zero=reviewed_zero_costs() if zero_costs is None else zero_costs
    zero_attack=reviewed_zero_attacks() if zero_attacks is None else zero_attacks
    result=[];used_zero=set();used_zero_attack=set()
    for row in data['cards']:
        raw=row['record'];cid=raw['id'];tags=raw['tags'];cost=raw['cost']
        if raw['collectible']is not True:raise TargetValidationError('Candidate root must be collectible')
        if cost is None:
            if cid not in zero or zero[cid]['record']!=raw:
                raise TargetValidationError('Missing candidate cost has no individual evidence')
            cost=zero[cid]['reviewed_cost'];used_zero.add(cid)
        if type(cost)is not int or cost<0:raise TargetValidationError('Candidate printed cost must be an integer')
        attack=None
        if raw['type']=='MINION':
            attack=raw['attack']
            if attack is None:
                if cid not in zero_attack or zero_attack[cid]['record']!=raw:
                    raise TargetValidationError('Missing candidate attack has no individual evidence')
                attack=zero_attack[cid]['reviewed_attack'];used_zero_attack.add(cid)
            if type(attack)is not int or attack<0:
                raise TargetValidationError('Candidate printed minion attack must be a nonnegative integer')
        school=tags.get('SPELL_SCHOOL')
        if school is not None and(type(school)is not int or school not in SCHOOLS):
            raise TargetValidationError('Unknown candidate spell school')
        keywords=[]
        for tag in keyword_tags:
            value=tags.get(tag,0)
            if type(value)is not int or value not in(0,1):raise TargetValidationError('Candidate keyword tag must be a reviewed boolean')
            if value:keywords.append(Keyword[tag])
        sidequest=tags.get('SIDE_QUEST',0)
        if type(sidequest)is not int or sidequest not in(0,1):raise TargetValidationError('Candidate Sidequest tag must be a reviewed boolean')
        if sidequest:keywords.append(Keyword.SIDEQUEST)
        for value in data['printed_keyword_overrides'].get(cid,()):
            keyword=Keyword(value)
            if keyword in keywords:raise TargetValidationError('Duplicate explicit candidate keyword')
            keywords.append(keyword)
        battlecry=tags.get('BATTLECRY',0)
        if type(battlecry)is not int or battlecry not in(0,1):raise TargetValidationError('Candidate Battlecry tag must be boolean')
        abilities={}
        for field,tag in (('deathrattle','DEATHRATTLE'),('choose_one','CHOOSE_ONE')):
            value=tags.get(tag,0)
            if type(value)is not int or value not in(0,1):raise TargetValidationError(f'Candidate {tag} tag must be boolean')
            abilities[field]=bool(value)
        result.append(PoolCard(cid,CardType(raw['type'].lower()),cost,metadata_from_record(raw),
            spell_school=SCHOOLS.get(school),keywords=tuple(keywords),battlecry=bool(battlecry),attack=attack,**abilities))
    if used_zero!=set(zero):raise TargetValidationError('Candidate cost evidence and catalog disagree')
    if used_zero_attack!=set(zero_attack):raise TargetValidationError('Candidate attack evidence and catalog disagree')
    return tuple(result)


def _same_printed_query_fields(expected,actual):
    left=asdict(expected.metadata);right=asdict(actual.metadata)
    # Copy-limit identity is not a generation filter. Preserve executable Core
    # aliases and legacy unspecified copy identities; generation identity is CID.
    left.pop('deck_identity');right.pop('deck_identity')
    return(left==right and expected.kind==actual.kind and expected.cost==actual.cost and
        expected.spell_school==actual.spell_school and set(expected.keywords)==set(actual.keywords)and
        expected.battlecry==actual.battlecry and expected.deathrattle==actual.deathrattle and
        expected.choose_one==actual.choose_one and expected.generation_identity==actual.generation_identity and
        expected.attack==actual.attack)


def register_candidate_pool_metadata(registry):
    """Prevalidate the entire inventory, then add only missing metadata rows."""
    pending=[]
    for expected in candidate_pool_rows():
        cid=expected.card_id;candidate=expected
        if cid in registry.cards:
            candidate=PoolCard.from_definition(registry.card(cid))
            if not _same_printed_query_fields(expected,candidate):
                raise TargetValidationError(f'Executable candidate disagrees with printed query fields: {cid}')
        if cid in registry.pool_cards:
            if registry.pool_card(cid)!=candidate:
                raise TargetValidationError(f'Existing candidate metadata conflicts with the complete catalog: {cid}')
        else:pending.append(candidate)
    for candidate in pending:registry.register_pool_card(candidate)
    # Native Fabled flags are independent of executable coverage.
    for row in load_batch()['cards']:
        raw=row['record'];tags=raw['tags']
        if tags.get('FABLED')==1 or tags.get('FABLED_PLUS')==1:
            if tags.get('DONT_PICK_FROM_SUBSETS')!=1:
                raise TargetValidationError('Fabled generation exclusion lost its complete original flag')
            registry.register_fabled_generation_exclusion(raw['id'])
        if raw['id']in NATIVE_GENERATION_EXCLUSIONS:
            if tags.get('DONT_PICK_FROM_SUBSETS')!=1:
                raise TargetValidationError('Native random exclusion lost its original subset flag')
            registry.register_generation_exclusion(raw['id'])
