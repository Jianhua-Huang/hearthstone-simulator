"""The actual Soothsayer healing belongs before the replaceable summon half."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix,AssembleSuffix,AssembleTemplate
from hs_sim.engine.effects import Heal
from hs_sim.engine.model import HandActionSpec,Keyword
from hs_sim.engine.pools import SummonFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .native_followup_cards import deathrattle_position
from .simple_followup_p47_cards import minion_query,POOL_ID

CARD='JAIL_912'
BEFORE='cards.assemble_prefix_healing.heal'
BODY='cards.assemble_prefix_healing.summon'
DEATH_BODY='cards.assemble_prefix_healing.death_summon'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/assemble-prefix-healing-fragments-v1.json'
BATCH_HASH='95a1aec2d6c6e64760b90e884765a62eb1daa0b5b67d9995af5d2f565644e33f'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'));rows=data['existing_dependencies']
    if(canonical_digest(data)!=BATCH_HASH or tuple(r['record']['id']for r in rows)!=(CARD,) or
            any(data[k]for k in ('cards','dependencies','evidence_only','choice_only','skipped')) or
            canonical_digest(rows[0]['record'])!=rows[0]['record_sha256']):
        raise TargetValidationError('Prefix healing requires the complete original Soothsayer')
    return data


def register_assemble_prefix_healing_fragments(registry):
    data=load_batch();row=data['existing_dependencies'][0];decl=data['reviewed_template'];query=minion_query(6)
    if(canonical_digest(asdict(registry.card(CARD)))!=row['definition_sha256'] or
            canonical_digest(asdict(query))!=canonical_digest(decl['query']) or decl['pool_id']!=POOL_ID):
        raise TargetValidationError('Prefix healing changed its complete original Soothsayer or summon query')
    registry.register_behavior(BEFORE,lambda c:(Heal(c.state.players[c.player_id].hero_id,6,c.source_id),))
    registry.register_behavior(BODY,lambda c:(SummonFromPool(c.player_id,POOL_ID,query,
        source_id=c.source_id,cause=SummonCause.capture(c)),))
    registry.register_behavior(DEATH_BODY,lambda c:(SummonFromPool(c.player_id,POOL_ID,query,
        source_id=c.source_id,cause=SummonCause.capture(c),position=deathrattle_position(c)),))
    registry.register_assemble_template(AssembleTemplate(CARD,
        AssemblePrefix('deathrattle',tuple(Keyword(k)for k in decl['keywords']),
            hand_actions=tuple(HandActionSpec(**s)for s in decl['hand_actions']),before_behavior_id=BEFORE),
        AssembleSuffix(BODY,tuple(decl['allowed_timings']),deathrattle_behavior_id=DEATH_BODY),
        original_deathrattle_id=decl['original_deathrattle_id']))
