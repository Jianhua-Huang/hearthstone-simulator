"""Original no-neutral death gate and original held Nature progress material."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_death_programs import AssembleConditionalDeathSource
from hs_sim.engine.assemble_hand_progress import AssembleHandProgressSource
from hs_sim.engine.assemble_faces import AssemblePrefix,AssembleSuffix,AssembleTemplate
from hs_sim.engine.effects import Draw
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.model import CardClass,CardType,CostSpec,Zone
from hs_sim.engine.pools import GenerateFromPool,PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion,MinionReference
from hs_sim.targets import TargetValidationError,canonical_digest
from .simple_followup_p47_cards import NO_NEUTRAL

SOURCES=('JAIL_328','TIME_213')
DEPENDENCIES=('CORE_SW_072','CORE_UNG_084','RLK_061','RLK_061t','CORE_EX1_169','EDR_451','CATA_480','BE_994','CORE_UNG_848')
PREFIX='cards.assemble_native_conditional_prefixes.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/assemble-native-conditional-prefixes-v1.json'
BATCH_HASH='56718fce4ba861e2ffaeb75d2ce6ec897cf2a90d92f528d9a026e9601102aceb'
PALADIN=PoolQuery(collectible=True,class_mode='specified',classes=(CardClass.PALADIN,),include_neutral=False)


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or
            tuple(x['record']['id']for x in data['existing_dependencies'])!=SOURCES+DEPENDENCIES or
            tuple(x['card_id']for x in data['reviewed_templates'])!=SOURCES or
            tuple(x['card_id']for x in data['conditional_death_sources'])!=(SOURCES[0],)or
            tuple(x['card_id']for x in data['hand_progress_sources'])!=(SOURCES[1],)or
            any(data[k]for k in('cards','dependencies','evidence_only','choice_only','skipped'))or
            any(canonical_digest(x['record'])!=x['record_sha256']or
                canonical_digest(x['definition'])!=x['definition_sha256']for x in data['existing_dependencies'])or
            canonical_digest(data['conditional_death_sources'][0]['condition'])!=canonical_digest(asdict(NO_NEUTRAL))or
            canonical_digest(data['conditional_death_sources'][0]['query'])!=canonical_digest(asdict(PALADIN))or
            canonical_digest(data['conditional_death_sources'][0]['cost'])!=canonical_digest(asdict(CostSpec(delta=-2)))):
        raise TargetValidationError('Native conditional prefixes changed complete originals or exact deck branch')
    return data


def register_assemble_native_conditional_prefixes(registry):
    data=load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id'])))!=row['definition_sha256']:
            raise TargetValidationError('Native conditional prefix lost a complete original definition')
    def paladin_reward(c):
        return (GenerateFromPool(c.player_id,'constructed.cards',PALADIN,source_id=c.source_id,cost=CostSpec(delta=-2)),)
    def held_reward(c):
        buff=(BuffCapturedMinion(MinionReference.capture(c.source),1,1,c.source_id),)if c.source.zone==Zone.BOARD and c.source.kind==CardType.MINION else ()
        return (*buff,Draw(c.player_id,1,c.source_id))
    def held_ready(c):
        progress=progress_ability(c.source)
        if progress is None:raise ResolutionError('Held assembly prefix lost its original Nature facts')
        return bool(progress.progress_completions)
    registry.register_behavior(PREFIX+'paladin_reward',paladin_reward)
    registry.register_behavior(PREFIX+'held_reward',held_reward)
    registry.register_trigger_condition(PREFIX+'held_ready',held_ready)
    row=data['conditional_death_sources'][0]
    registry.register_assemble_conditional_death_source(AssembleConditionalDeathSource(row['card_id'],
        row['original_deathrattle_id'],row['original_suffix_id'],NO_NEUTRAL,row['pool_id'],PALADIN,CostSpec(delta=-2)))
    row=data['hand_progress_sources'][0];spec=registry.card(row['card_id']).hand_progress
    if canonical_digest(asdict(spec))!=canonical_digest(row['native_spec']):raise TargetValidationError('Held prefix changed full printed progress')
    registry.register_assemble_hand_progress_source(AssembleHandProgressSource(row['card_id'],spec,
        row['original_battlecry_id'],row['condition_id'],row['reward_behavior_id']))
    for row in data['reviewed_templates']:
        if row['card_id']==SOURCES[0]:
            before=data['conditional_death_sources'][0]['original_deathrattle_id']
            registry.register_assemble_template(AssembleTemplate(row['card_id'],AssemblePrefix('deathrattle',before_behavior_id=before),
                AssembleSuffix(row['body_id'],tuple(row['allowed_timings'])),original_deathrattle_id=before))
        else:
            source=data['hand_progress_sources'][0]
            registry.register_assemble_template(AssembleTemplate(row['card_id'],AssemblePrefix('battlecry',condition_id=source['condition_id']),
                AssembleSuffix(row['body_id'],tuple(row['allowed_timings'])),original_battlecry_id=source['original_battlecry_id']))
