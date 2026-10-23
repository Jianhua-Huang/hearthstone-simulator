"""Three real historical leaves over original Reborn, dormancy and summons."""
import json
from pathlib import Path

from hs_sim.engine.dormancy import AwakenCapturedMinion, deaths_since_installation
from hs_sim.engine.effects import CopyMinion
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (BoardPresenceReference, CardDefinition, CardType,
    StatReference, StatRelationLayer, StatRelationOperand, StatRelationSpec, TriggerSpec)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.successful_summons import successful_reborns
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

SPEAKER, SLEEPER, AUTOMATON = 'GDB_469', 'TOY_866', 'TTN_401'
DEPENDENCIES = (SPEAKER, SLEEPER, AUTOMATON)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_summon_death_history.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-summon-death-history-cards-v1.json'
BATCH_HASH = '9f92fedb28b6de8414c777b1b792489dcb6c424b5eb3280f2c074c1dfba4574f'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != DEPENDENCIES or
            tuple(x['record']['id'] for x in data['dependencies']) != DEPENDENCIES or
            any(data[k] for k in ('cards','existing_dependencies','evidence_only','choice_only',
                'skipped','numeric_normalizations','display_normalizations')) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in data['dependencies'])):
        raise TargetValidationError('Historical summon/death consumers lost complete original sources')
    return data


def register_past_summon_death_history_cards(registry):
    def speaker(c):
        event = c.event
        if event is None or event.kind != 'minion_reborn':
            raise ResolutionError('Death-Speaker requires the original successful Reborn event')
        if event.player_id != c.player_id or event.target_id == c.source_id:return ()
        death_id = dict(event.data)['death_id']
        row = next((x for x in successful_reborns(c.state,c.player_id)
            if x.entity_id == event.target_id and x.reborn_death_id == death_id),None)
        if row is None:raise ResolutionError('Death-Speaker lost its actual original Reborn recipient')
        reference = BoardPresenceReference(row.entity_id,row.minion.entered_order)
        return (CopyMinion(reference,c.player_id,cause=SummonCause.capture(c)),)

    def sleeper(c):
        if c.event is None or c.event.kind != 'minion_died':
            raise ResolutionError('Corridor Sleeper requires an actual minion death window')
        if c.source.dormancy is None:return ()
        if deaths_since_installation(c.state,registry,c.source) < 7:return ()
        return (AwakenCapturedMinion(MinionReference.capture(c.source),c.source.dormancy.id,c.source_id),)

    registry.register_behavior(PREFIX+'speaker',speaker)
    registry.register_behavior(PREFIX+'sleeper',sleeper)
    for item in load_batch()['dependencies']:
        raw=item['record'];cid=raw['id']
        if raw['type']!='MINION' or raw['collectible'] is not True or raw['cost']!=1:
            raise TargetValidationError('Historical summon/death original body changed')
        if cid==SPEAKER:
            fields=dict(triggers=(TriggerSpec('minion_reborn',PREFIX+'speaker'),))
        elif cid==SLEEPER:
            fields=dict(dormant_turns=None,dormant_triggers=(TriggerSpec('minion_died',PREFIX+'sleeper'),))
        else:
            fields=dict(stat_relations=tuple(StatRelationSpec(target,
                StatRelationOperand.CONTROLLER_OTHER_SELF_SUMMON_COUNT,layer,1)
                for target,layer in ((StatReference.ATTACK,StatRelationLayer.CONDITIONAL_ATTACK),
                    (StatReference.HEALTH,StatRelationLayer.CONDITIONAL_HEALTH))))
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=1,attack=raw['attack'],health=raw['health'],
            metadata=metadata_from_record(raw),**fields)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
