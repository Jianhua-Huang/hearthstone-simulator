"""Tiny Pal's four mutually exclusive native weapon faces and ordinary effects."""
from dataclasses import replace
import json,re
from pathlib import Path
from hs_sim.engine.effects import Damage,DamageBatch
from hs_sim.engine.model import CardAbilityCondition,CardDefinition,CardType,CostSpec,EquippedWeaponReference,Keyword,TriggerSpec,Zone
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery,SummonFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.weapon_attack_freeze import FreezeOtherEnemiesAfterWeaponAttack
from hs_sim.engine.weapon_forms import RequestWeaponForm
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import completed_attack
from .metadata import metadata_from_record
from .native_followup_cards import characters

CARD='JAIL_458'
FORMS=tuple(CARD+'t'+str(i)for i in range(1,5))
ROOTS=(CARD,*FORMS)
PREFIX='cards.tiny_pal.'
POOL='constructed.cards'
EARTH=PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=3,max_cost=3)
AIR=PoolQuery(kinds=(CardType.MINION,),collectible=True,ability=CardAbilityCondition(basis='printed'))
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/elemental-ammunition-v1.json'
BATCH_HASH='3d479412797696e0028ac14e89ccb770ce07aeccb439efa05a5ba44f927a87d4'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(CARD,) or
            tuple(x['record']['id']for x in data['dependencies'])!=FORMS):
        raise TargetValidationError('Tiny Pal requires all four complete native ammunition faces')
    for row in data['cards']+data['dependencies']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Tiny Pal complete native source changed')
    return data


def register_elemental_ammunition_card(registry):
    data=load_batch();raws={x['record']['id']:x['record']for x in data['cards']+data['dependencies']}
    options=tuple((cid,re.sub('<[^>]*>','',raws[cid]['text']).replace('\n',' ').replace('[x]',''))for cid in FORMS)
    def battlecry(c):
        if c.battlecry is None:raise ValueError('Tiny Pal requires its actual Battlecry context')
        return (RequestWeaponForm(c.player_id,options,c.source_id),)
    def after_attack(c):
        row=completed_attack(c)
        if (row is None or row.source_kind!=CardType.HERO or row.declaration.player_id!=c.player_id or
                row.combat is None or row.combat.weapon_id!=c.source_id):return ()
        face=c.source.card_id;effects=[]
        if face==FORMS[0]:effects.append(FreezeOtherEnemiesAfterWeaponAttack(row.declaration.id,c.source_id))
        elif face==FORMS[1]:
            effects.append(DamageBatch(tuple(Damage(i,1,c.source_id)for i in characters(c,registry,3-c.player_id))))
        elif face==FORMS[2]:
            effects.append(SummonFromPool(c.player_id,POOL,EARTH,source_id=c.source_id,
                cause=SummonCause.capture(c),entry_keywords=(Keyword.TAUNT,)))
        elif face==FORMS[3]:
            effects.append(GenerateFromPool(c.player_id,POOL,AIR,source_id=c.source_id,cost=CostSpec(delta=-2)))
        elif face!=CARD:raise ValueError('Unknown original Tiny Pal ammunition')
        e=c.source
        if e.kind==CardType.WEAPON and e.zone==Zone.WEAPON and e.active and not e.doomed and e.durability>0:
            effects.append(RequestWeaponForm(c.player_id,options,c.source_id,EquippedWeaponReference.capture(e)))
        return tuple(effects)
    registry.register_behavior(PREFIX+'battlecry',battlecry);registry.register_behavior(PREFIX+'after_attack',after_attack)
    for cid,raw in raws.items():
        if (raw['type'],raw['cost'],raw['attack'],raw['health'])!=('WEAPON',4,2,3):raise TargetValidationError('Unexpected Tiny Pal native weapon shape')
        card=CardDefinition(cid,raw['name'],CardType.WEAPON,cost=raw['cost'],attack=raw['attack'],durability=raw['health'],
            battlecry=PREFIX+'battlecry'if cid==CARD else None,triggers=(TriggerSpec('attack_finished',PREFIX+'after_attack'),),
            metadata=replace(metadata_from_record(raw),deck_identity=CARD))
        registry.register_card(card)
        if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
