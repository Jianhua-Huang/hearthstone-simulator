"""Original live secret-copy program and one physical deck-reveal prefix."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix,AssembleSuffix,AssembleTemplate
from hs_sim.engine.assemble_reveals import AssembleRevealSource
from hs_sim.engine.model import CardType,DamageKind
from hs_sim.engine.random_split_damage import NON_SPELL_PROFILE,RandomSplitDamage,SplitDamageScope
from hs_sim.targets import TargetValidationError,canonical_digest

SOURCES=('EDR_780','JAIL_379')
DEPENDENCIES=('CORE_SW_072','CORE_UNG_084','CORE_CS2_032','CORE_CS2_029','RLK_061','RLK_061t','BE_994','CORE_UNG_848')
PREFIX='cards.assemble_native_copy_reveal_programs.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/assemble-native-copy-reveal-programs-v1.json'
BATCH_HASH='59c48d1af5a9218b8451098b7e8bb1de9ad121ff772de7da11dc596ec389514e'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or
            tuple(x['record']['id']for x in data['existing_dependencies'])!=SOURCES+DEPENDENCIES or
            tuple(x['card_id']for x in data['reviewed_templates'])!=SOURCES or
            tuple(x['card_id']for x in data['reveal_sources'])!=(SOURCES[1],)or
            any(data[k]for k in('cards','dependencies','evidence_only','choice_only','skipped'))or
            any(canonical_digest(x['record'])!=x['record_sha256']or
                canonical_digest(x['definition'])!=x['definition_sha256']for x in data['existing_dependencies'])):
        raise TargetValidationError('Copy/reveal assembly changed complete original records or definitions')
    return data


def register_assemble_native_copy_reveal_programs(registry):
    data=load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id'])))!=row['definition_sha256']:
            raise TargetValidationError('Copy/reveal assembly lost a full original definition')
    registry.register_behavior(PREFIX+'damage_reward',lambda c:(RandomSplitDamage(c.player_id,None,c.source_id,5,
        scope=SplitDamageScope(kinds=(CardType.MINION,)),profile=NON_SPELL_PROFILE,kind=DamageKind.MINION_ABILITY),))
    profile=AssembleRevealSource(**data['reveal_sources'][0]);registry.register_assemble_reveal_source(profile)
    for row in data['reviewed_templates']:
        prefix=AssemblePrefix('battlecry',before_behavior_id=profile.original_battlecry_id)if row['card_id']==profile.card_id else AssemblePrefix('battlecry')
        registry.register_assemble_template(AssembleTemplate(row['card_id'],prefix,
            AssembleSuffix(row['body_id'],tuple(row['allowed_timings']),pending_timings=tuple(row['pending_timings'])),
            original_battlecry_id=profile.original_battlecry_id if row['card_id']==profile.card_id else None))
