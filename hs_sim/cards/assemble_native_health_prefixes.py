"""Two complete native health-result prefixes and their independent rewards."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix,AssembleSuffix,AssembleTemplate
from hs_sim.engine.assemble_health_prefixes import AssembleHealthPrefixSource
from hs_sim.engine.effects import Buff,GainArmor,GrantKeyword
from hs_sim.engine.model import Keyword
from hs_sim.targets import TargetValidationError,canonical_digest

SOURCES=('BE_994','TLC_606')
DEPENDENCIES=('CORE_SW_072','CORE_REV_946','CORE_UNG_084','RLK_061','RLK_061t')
PREFIX='cards.assemble_native_health_prefixes.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/assemble-native-health-prefixes-v1.json'
BATCH_HASH='4facc86162bf772e6b4879f348c31803d2991ef627c9e861dc06283f14dd3464'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or
            tuple(x['record']['id']for x in data['existing_dependencies'])!=SOURCES+DEPENDENCIES or
            tuple(x['card_id']for x in data['health_prefix_sources'])!=SOURCES or
            tuple(x['card_id']for x in data['reviewed_templates'])!=SOURCES or
            any(data[k]for k in('cards','dependencies','evidence_only','choice_only','skipped'))or
            any(canonical_digest(x['record'])!=x['record_sha256']or
                canonical_digest(x['definition'])!=x['definition_sha256']for x in data['existing_dependencies'])):
        raise TargetValidationError('Native health prefixes changed complete original records or definitions')
    return data


def register_assemble_native_health_prefixes(registry):
    data=load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id'])))!=row['definition_sha256']:
            raise TargetValidationError('Native health prefix lost a complete original definition')
    registry.register_behavior(PREFIX+'survivor_reward',lambda c:(Buff(c.source_id,health=6,source_id=c.source_id),
        GrantKeyword(c.source_id,Keyword.TAUNT,c.source_id)))
    registry.register_behavior(PREFIX+'kill_reward',lambda c:(GainArmor(c.player_id,5),))
    for row in data['health_prefix_sources']:
        registry.register_assemble_health_prefix_source(AssembleHealthPrefixSource(**row))
    for row in data['reviewed_templates']:
        registry.register_assemble_template(AssembleTemplate(row['card_id'],
            AssemblePrefix('battlecry',before_behavior_id=row['before_behavior_id']),
            AssembleSuffix(row['body_id'],tuple(row['allowed_timings'])),original_battlecry_id=row['before_behavior_id']))
