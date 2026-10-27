"""Aggramar grants real current weapons ordinary native attack followups."""
import hashlib,json
from pathlib import Path

from hs_sim.engine.character_attacks import completed_attack
from hs_sim.engine.effects import Draw,EquipWeapon,GrantKeyword,GrantTrigger,InvokeBehavior,ModifyWeapon,Summon
from hs_sim.engine.equipment import equipped_weapon
from hs_sim.engine.model import ActivatedAbilitySpec,CardDefinition,CardType,EquippedWeaponReference,Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/aggramar-weapon-skills-v1.json'
BATCH_HASH='b04c50a2dcf79d05d83ed444f5a741002b7d95c38e059d529472149ab43913bd'
AGGRAMAR='TTN_092';WEAPON='TTN_092t';ENFORCER='TTN_092e2t'
SKILLS=('TTN_092t1','TTN_092t2','TTN_092t3')
EVIDENCE=('TTN_092e','TTN_092e2','TTN_092e3')
ROOTS=(AGGRAMAR,);DEPENDENCIES=(WEAPON,ENFORCER,*SKILLS);COLLECTIBLE_ROOTS=()
PREFIX='cards.aggramar_weapon_skills.'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or
            tuple(r['record']['id']for r in d['cards'])!=ROOTS or
            tuple(r['record']['id']for r in d['dependencies'])!=DEPENDENCIES or
            tuple(r['record']['id']for r in d['evidence_only'])!=EVIDENCE or
            tuple(d['choice_only_ids'])!=SKILLS or tuple(d['new_token_ids'])!=(WEAPON,ENFORCER) or
            any(d[k]for k in('existing_dependencies','source_scope_bound','formal_pool_complete',
                            'cn_calibrated','real_excavate_profile_bound')) or
            len(d['official_observations'])!=12 or
            any(canonical_digest(r['record'])!=r['record_sha256']for key in('cards','dependencies','evidence_only')for r in d[key])):
        raise TargetValidationError('Aggramar requires complete original faces and explicit physical/descriptor roles')
    for ref in d['references']:
        if hashlib.sha256((ROOT/ref['path']).read_bytes()).hexdigest()!=ref['sha256']:
            raise TargetValidationError('Aggramar changed its complete original Titan reference')
    return d


def register_aggramar_weapon_skills(registry):
    d=load_batch();prepared=[]
    if any(r['record']['type']!='ENCHANTMENT'for r in d['evidence_only']):
        raise TargetValidationError('Aggramar enchantment evidence cannot become a physical face')
    for row in d['cards']+d['dependencies']:
        raw=row['record'];cid=raw['id'];kind=CardType[raw['type']];extra={}
        if cid in registry.cards:raise TargetValidationError('Aggramar cannot overwrite an existing card')
        if cid==AGGRAMAR:
            if kind!=CardType.MINION or (raw['cost'],raw['attack'],raw['health'])!=(6,3,7) or not raw['collectible'] or raw['tags'].get('TITAN')!=1:
                raise TargetValidationError('Aggramar lost its original Titan body')
            extra.update(keywords=(Keyword.TITAN,),battlecry=PREFIX+'equip',activated_abilities=tuple(
                ActivatedAbilitySpec(skill,PREFIX+skill,card_id=skill)for skill in SKILLS))
        elif cid in SKILLS:
            if kind!=CardType.SPELL or raw['cost']is not None or raw['collectible']:
                raise TargetValidationError('Aggramar skills require nonphysical original descriptors')
            extra['choice_only']=True
        else:
            if (kind,raw['cost'],raw['attack'],raw['health'],raw['collectible'])!=(
                    CardType.WEAPON if cid==WEAPON else CardType.MINION,3,3,3,False):
                raise TargetValidationError('Aggramar lost its real three-three weapon or Enforcer')
            if cid==ENFORCER:
                if raw['tags'].get('TAUNT')!=1:raise TargetValidationError('Vrykul Enforcer requires printed Taunt')
                extra['keywords']=(Keyword.TAUNT,)
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost']or 0,attack=raw['attack']or 0,
            health=(raw['health']or 0)if kind==CardType.MINION else 0,
            durability=raw['health']if kind==CardType.WEAPON else 0,metadata=metadata_from_record(raw),**extra)
        registry._validate_card(card)
        if cid not in SKILLS and cid in registry.pool_cards and registry.pool_card(cid)!=PoolCard.from_definition(card):
            raise TargetValidationError('Aggramar changed original printed pool metadata')
        prepared.append(card)

    def grant(c,skill):
        weapon=equipped_weapon(c.state,c.state.players[c.player_id])
        if weapon is None:return ()
        if skill==SKILLS[2]:
            return(ModifyWeapon(EquippedWeaponReference.capture(weapon),attack=2,source_id=c.source_id),
                GrantKeyword(weapon.id,Keyword.IMMUNE_WHILE_ATTACKING,c.source_id))
        return(GrantTrigger(weapon.id,'attack_finished',PREFIX+('draw'if skill==SKILLS[0]else'summon'),c.source_id),)

    def after_attack(c,draw):
        original=completed_attack(c)
        if (original is None or original.source_kind!=CardType.HERO or original.declaration.player_id!=c.player_id or
                original.combat is None or original.combat.weapon_id!=c.source_id):return ()
        return(Draw(c.player_id,source_id=c.source_id),)if draw else(Summon(c.player_id,ENFORCER),)

    registry.register_behavior(PREFIX+'equip',lambda c:(EquipWeapon(c.player_id,WEAPON),))
    registry.register_behavior(PREFIX+'draw',lambda c:after_attack(c,True))
    registry.register_behavior(PREFIX+'summon',lambda c:after_attack(c,False))
    for skill in SKILLS:
        registry.register_behavior(PREFIX+'grant.'+skill,lambda c,skill=skill:grant(c,skill))
        registry.register_behavior(PREFIX+skill,lambda c,skill=skill:(
            InvokeBehavior(PREFIX+'grant.'+skill,c.source_id,c.player_id),))
    for card in prepared:
        registry.register_card(card)
        if card.id not in SKILLS and card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
