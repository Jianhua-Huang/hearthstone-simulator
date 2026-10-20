"""The actual one-cost Potion required by Aya's Kabal counterfeit Coin."""
import json
from pathlib import Path

from hs_sim.engine.composed_spells import ComposedSpellComponent,ComposedSpellProfile,ResolveComposedSpell
from hs_sim.engine.effects import Damage,DamageBatch,Draw,GainArmor
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,TargetSpec,Zone
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion,MinionReference
from hs_sim.engine.spell_target_sequences import FreezeRandomEnemyMinions
from hs_sim.engine.summon_sources import Resurrect
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

TEMPLATE='JAIL_504t3p';DEMON='CFM_621_m4'
PARTS=('CFM_621t4','CFM_621t10','CFM_621t37','CFM_621t2','CFM_621t3','CFM_621t6','CFM_621t5','CFM_621t8','CFM_621t9')
PREFIX='cards.kazakus_potion.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/kazakus-potion-forms-v1.json'
BATCH_HASH='b311a2ded5c91031c6080575dfe503dafd6cd7717e43136d437afdb971c48e6d'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'));rows=(*data['dependencies'],*data['choice_only'],*data['evidence_only'])
    if (canonical_digest(data)!=BATCH_HASH or data['cards']or data['existing_dependencies']or data['skipped']or
            tuple(x['record']['id']for x in data['choice_only'])!=PARTS or
            tuple(x['record']['id']for x in data['dependencies'])!=(TEMPLATE,DEMON)or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in rows)):
        raise TargetValidationError('Potion requires the complete original one-cost template and nine actual ingredients')
    raw={x['record']['id']:x['record']for x in rows}
    if any(raw[c]['tags'].get('TAG_SCRIPT_DATA_NUM_1')!=i for i,c in enumerate(PARTS,1)):
        raise TargetValidationError('Potion original ingredient script identities changed')
    return data


def register_kazakus_potion_cards(registry):
    def uninitialized(c):raise ResolutionError('An uninitialized Potion has no selected recipe')
    def resolve(c):
        if c.cast is None:raise ResolutionError('A Potion requires its actual accepted spell CAST')
        return(ResolveComposedSpell(c.cast.id),)
    bodies={
        PARTS[0]:lambda c:(DamageBatch(tuple(Damage(i,2,c.source_id,DamageKind.SPELL)
            for p in(1,2)for i in minions(c,registry,p))),),
        PARTS[1]:lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(DEMON),),SummonCause.capture(c)),),
        PARTS[2]:lambda c:(Resurrect(c.player_id,source_id=c.source_id,cause=SummonCause.capture(c)),),
        PARTS[3]:lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL),),
        PARTS[4]:lambda c:(GainArmor(c.player_id,4),),
        PARTS[5]:lambda c:tuple(BuffCapturedMinion(MinionReference.capture(c.state.entities[i]),health=2,
            source_id=c.source_id)for i in minions(c,registry,c.player_id)),
        PARTS[6]:lambda c:(FreezeRandomEnemyMinions(c.player_id,c.cast.id,c.source_id,1),),
        PARTS[7]:lambda c:(Draw(c.player_id,1,c.source_id),),
        PARTS[8]:lambda c:(GenerateFromPool(c.player_id,'constructed.minions',PoolQuery(kinds=(CardType.MINION,),
            collectible=True,tribes_any=('demon',)),source_id=c.source_id),)}
    registry.register_behavior(PREFIX+'uninitialized',uninitialized)
    registry.register_behavior(PREFIX+'resolve',resolve)
    for cid,body in bodies.items():registry.register_behavior(PREFIX+cid,body)
    data=load_batch()
    for item in(*data['dependencies'],*data['choice_only']):
        raw=item['record'];cid=raw['id'];fields={};kind=CardType(raw['type'].lower())
        if cid==DEMON:fields.update(attack=raw['attack'],health=raw['health'])
        elif cid==TEMPLATE:fields.update(manual_playable=False,on_play=PREFIX+'uninitialized')
        else:fields.update(choice_only=True)
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost'],metadata=metadata_from_record(raw),**fields)
        registry.register_card(card)
        if cid==DEMON and cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_composed_spell_profile(ComposedSpellProfile(TEMPLATE,tuple(ComposedSpellComponent(cid,PREFIX+cid,
        TargetSpec(zones=(Zone.BOARD,Zone.HERO),kinds=(CardType.MINION,CardType.HERO))if cid==PARTS[3]else None)
        for cid in PARTS),PREFIX+'resolve'))
