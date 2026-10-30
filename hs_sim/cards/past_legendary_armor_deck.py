"""Real legendary consumers of committed armor, school damage and deck facts."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.costs import local_cost
from hs_sim.engine.deck_conditions import CheckDeckCondition,DeckCondition,DeckMinionCostCondition
from hs_sim.engine.effects import Heal,InvokeBehavior
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,HealingKind,Keyword,SpellSchool
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion,GrantCapturedKeyword,MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.engine.zones import CardReference,ModifyStoredCost
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-legendary-armor-deck-v1.json'
BATCH_HASH='c43f8ff9aeeb597fcaf8a86118db7ff4930495a8fa3438e4c50702c9518dc656'
GALVANGAR,BRUKAN,RENO,DREKTHAR,VANNDAR=ROOTS=('AV_145','BAR_048','LOE_011','AV_100','AV_223')
DEPENDENCIES=()
PREFIX='cards.past_legendary_armor_deck.'


def make_definition(raw):
    cid=raw['id']
    if(cid not in ROOTS or raw['type']!='MINION'or not raw['collectible']or
            raw['tags'].get('RARITY')!=5 or any(type(raw[k])is not int for k in('cost','attack','health'))):
        raise TargetValidationError('Armor/deck consumer requires its complete original Legendary minion')
    if cid==BRUKAN:
        if raw['tags'].get('SPELLPOWER_NATURE')!=1:
            raise TargetValidationError('Brukan lost his actual Nature-school declaration')
        fields=dict(spell_damage=3,spell_damage_schools=(SpellSchool.NATURE,))
    else:
        if raw['tags'].get('BATTLECRY')!=1:raise TargetValidationError('Legendary consumer lost its real Battlecry')
        fields=dict(battlecry=PREFIX+cid)
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],
        health=raw['health'],metadata=metadata_from_record(raw),**fields)


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(data)!=BATCH_HASH or data['schema']!=1 or
            data['policy_id']!='cn37-local-past-legendary-armor-deck-v1'or
            tuple(x['record']['id']for x in data['cards'])!=ROOTS or data['dependencies']or
            [x['record']['id']for x in data['existing_dependencies']]!=['TIME_013']or
            [x['record']['id']for x in data['evidence_only']]!=['MIS_701']or
            len(data['official_observations'])!=14 or
            data['display_normalizations']!={GALVANGAR:{'@':'','{0}':''}}or
            any(data[k]for k in('complete_past_legendary_source_bound','new_standard_roots',
                'membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Armor/deck consumers lost complete source identities or boundaries')
    for group in('cards','existing_dependencies','evidence_only'):
        if any(canonical_digest(x['record'])!=x['record_sha256']for x in data[group]):
            raise TargetValidationError('Armor/deck consumer changed a complete pinned raw row')
    for item in data['retained_documents'].values():
        path=(ROOT/item['path']).resolve()
        if not path.is_relative_to(ROOT)or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise TargetValidationError('Armor/deck consumer changed a retained complete reference')
    full=json.loads((ROOT/data['full_reference_document']).read_text(encoding='utf8'))
    records={x['record']['id']:x['record']for x in full['candidate_records']}
    if(len(full['candidate_ids'])!=732 or data['original_candidate_ids']!=full['candidate_ids']or
            any(x['record']!=records[x['record']['id']]for x in data['cards'])):
        raise TargetValidationError('Armor/deck consumers cropped the complete original past domain')
    return data


def register_past_legendary_armor_deck(registry):
    data=load_batch();prepared=[]
    for row in data['existing_dependencies']:
        cid=row['record']['id']
        if(canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or
                canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']):
            raise TargetValidationError('Armor/deck consumer changed a complete existing dependency')
    for row in data['cards']:
        card=make_definition(row['record'])
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Armor/deck consumer cannot replace or alter an existing face')
        registry._validate_card(card);prepared.append(card)
    def galvangar(c):
        gained=sum(row.amount for row in c.state.armor_gain_history if row.player_id==c.player_id)
        if gained<15 or not living_source(c):return()
        ref=MinionReference.capture(c.source)
        return(BuffCapturedMinion(ref,3,3,c.source_id),GrantCapturedKeyword(ref,Keyword.CHARGE,c.source_id))
    def reno(c):
        hero=c.state.entities[c.state.players[c.player_id].hero_id]
        return(CheckDeckCondition(c.player_id,DeckCondition('current','no_duplicates'),
            (Heal(hero.id,hero.max_health,c.source_id,HealingKind.EFFECT),)),)
    def drekthar(c):
        cost=local_cost(c.source)[0]
        return(CheckDeckCondition(c.player_id,DeckMinionCostCondition(cost,'less','local'),
            (SummonFromZone(c.player_id,count=1,source_id=c.source_id,cause=SummonCause.capture(c)),)),)
    def vanndar(c):
        cost=local_cost(c.source)[0]
        return(CheckDeckCondition(c.player_id,DeckMinionCostCondition(cost,'greater','local'),
            (InvokeBehavior(PREFIX+'discount',c.source_id,c.player_id),)),)
    def discount(c):
        refs=[]
        for eid in c.state.players[c.player_id].deck:
            entity=c.state.entities[eid]
            if registry.card(entity.card_id).kind==CardType.MINION:refs.append(CardReference.capture(entity))
        return tuple(ModifyStoredCost(ref,CostSpec(delta=-3),c.source_id)for ref in refs)
    for name,body in((GALVANGAR,galvangar),(RENO,reno),(DREKTHAR,drekthar),(VANNDAR,vanndar),('discount',discount)):
        registry.register_behavior(PREFIX+name,body)
    for card in prepared:
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
