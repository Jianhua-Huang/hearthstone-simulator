"""Actual previous-play rune weapon and fixed Necronurse summon/attack spell."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import ModifyWeapon
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BoardPresenceReference,CardDefinition,CardType,Keyword,TargetSpec,Zone
from hs_sim.engine.play_history import played_cards
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.summon_attack_groups import AttackSummonedGroup,SummonAttackProfile
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/blood-rune-native-v1.json'
BATCH_HASH='8dc491ad5e21f3e3fd4a7bdf6788a72b5b48ef2d53eac6d219f15b914727e029'
BLADE='EDR_812';SURGERY='JAIL_454';NURSE='JAIL_454t';PREFIX='cards.blood_rune_native.'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Blood rune native complete source pin changed')
    return data


def register_blood_rune_native_cards(registry):
    def blade(c):
        if c.battlecry is None or c.battlecry.card_id!=BLADE or c.battlecry.source_id!=c.source_id:
            raise ResolutionError('Runeblade requires its actual accepted Battlecry')
        before=c.battlecry.play_id if c.battlecry.origin=='hand'else None
        previous=played_cards(c.state,c.player_id,before_id=before)
        if not previous:return()
        meta=previous[-1].played_face.metadata
        if meta is None:raise UnsupportedDefinitionError('Runeblade previous played rune metadata is unknown')
        runes=meta.runes
        attack=int(runes is not None and runes.unholy>0);durability=int(runes is not None and runes.blood>0)
        return(ModifyWeapon(c.source_id,attack,durability,c.source_id),)if attack or durability else()
    def surgery(c):
        if c.cast is None or c.cast.card_id!=SURGERY or c.cast.source_id!=c.source_id:
            raise ResolutionError('Surgery requires its actual native spell body')
        target=c.state.entities.get(c.target_id)
        if target is None or target.zone!=Zone.BOARD or not target.active or target.health<=0 or target.doomed:return()
        reference=BoardPresenceReference.capture(c.state,target.id)
        request=SummonByCard(c.player_id,(SummonEntryMaterial(NURSE),),SummonCause.capture(c))
        return(request,request,request,request,AttackSummonedGroup(c,reference))
    registry.register_behavior(PREFIX+'blade',blade);registry.register_behavior(PREFIX+'surgery',surgery)
    data=load_batch()
    if tuple(x['record']['id']for x in data['cards'])!=(BLADE,SURGERY)or tuple(x['record']['id']for x in data['dependencies'])!=(NURSE,):
        raise TargetValidationError('Unreviewed blood rune root/fixed dependency set')
    for row in data['cards']+data['dependencies']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete blood rune native raw row')
    for row in data['cards']+data['dependencies']:
        raw=row['record'];cid=raw['id'];metadata=replace(metadata_from_record(raw),deck_identity=cid)
        if cid==BLADE:
            card=CardDefinition(cid,raw['name'],CardType.WEAPON,cost=raw['cost'],attack=raw['attack'],durability=raw['health'],metadata=metadata,battlecry=PREFIX+'blade')
        elif cid==NURSE:
            card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=metadata,keywords=(Keyword.LIFESTEAL,))
        else:
            card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],metadata=metadata,on_play=PREFIX+'surgery',
                targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy'))
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_summon_attack_profile(SummonAttackProfile(SURGERY,NURSE,4))
