"""Two past Mage spells reuse physical CASTs, Objective clocks and mana budgets."""
import hashlib,json
from pathlib import Path
from hs_sim.engine.deck_spell_casts import CastRandomDeckSpell
from hs_sim.engine.model import CardDefinition,CardType,EndTurnSpec,PlayerEffectSpec,TriggerSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.spell_mana_budget import CastManaWorth
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
RUNE,TOWER='AV_283','AV_290'
LEAVES=(RUNE,TOWER)
PREFIX='cards.archmage_tower.'
PROGRAM=PREFIX+'tower'
BATCH_PATH=ROOT/'data/cards/archmage-tower-v1.json'
BATCH_HASH='22a0e4e9f34757a227ed205dafc2799a96b54ed67667b39e202f2d34e28a4442'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data)!=BATCH_HASH or data['schema']!=1 or
            tuple(v['record']['id']for v in data['cards'])!=LEAVES or len(data['official_observations'])!=4 or
            any(canonical_digest(v['record'])!=v['record_sha256']for v in data['cards'])or
            any(data[k]for k in ('dependencies','evidence_only','new_standard_roots','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Archmage/Tower requires complete original records and four primary faces')
    ref=ROOT/data['reference_document']
    if hashlib.sha256(ref.read_bytes()).hexdigest()!=data['reference_sha256']or not set(LEAVES)<=set(json.loads(ref.read_text(encoding='utf8'))['candidate_ids']):
        raise TargetValidationError('Archmage/Tower lost the full original past-Mage reference')
    return data


def register_archmage_tower_cards(registry):
    data=load_batch()
    def rune(c):
        if c.cast is None:raise UnsupportedDefinitionError('Rune requires its original actual spell CAST')
        return (CastManaWorth(c.player_id,'constructed.cards',None,20,c.source_id,RUNE,mage_cast_id=c.cast.id),)
    def tower(c):
        instance=c.player_effect
        if instance is None or instance.spec_id!=PROGRAM or c.event is None or c.event.player_id!=c.player_id:
            raise UnsupportedDefinitionError('Tower requires its original owner-end Objective instance')
        return (CastRandomDeckSpell(c.player_id,None,c.source_id,player_effect=instance,owner_end=c.event),)
    registry.register_behavior(PREFIX+'rune',rune);registry.register_behavior(PROGRAM,tower)
    registry.register_player_effect(PlayerEffectSpec(PROGRAM,TOWER,kind='objective',duration=3,tick_event='turn_ended',
        triggers=(TriggerSpec('turn_ended',PROGRAM,EndTurnSpec()),)))
    for row in data['cards']:
        raw=row['record'];cid=raw['id']
        if raw['type']!='SPELL'or raw['cost']!=(9 if cid==RUNE else 10)or raw['tags'].get('SPELL_SCHOOL')is not None:
            raise TargetValidationError('Unreviewed original Archmage/Tower spell face')
        if cid==TOWER and (raw['tags'].get('OBJECTIVE'),raw['tags'].get('QUEST_PROGRESS_TOTAL'))!=(1,3):
            raise TargetValidationError('Tower lost its original three-turn Objective')
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],metadata=metadata_from_record(raw),
            on_play=PREFIX+'rune'if cid==RUNE else None,ongoing_effect_id=PROGRAM if cid==TOWER else None)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
