"""Unleash the Colossus and bounded, independent Gorishi bonus damage."""
import json
from pathlib import Path

from hs_sim.engine.effects import AddToHand
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import (CardDefinition, CardType, DamageKind, HealthFlow, Keyword,
    PlayerEffectSpec, QuestSpec, QuestStageSpec, TriggerSpec)
from hs_sim.engine.player_effects import AddPlayerEffect, PlayerEffectDamage
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.quests import AdvanceQuest
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

QUEST, REWARD, ENCHANTMENT = 'TLC_631', 'TLC_631t', 'TLC_631e'
PREFIX = 'cards.gorishi_colossus.'
RULE = PREFIX+'permanent'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/damage-quest-reward-v1.json'
BATCH_HASH = '5146f6dd72755487f7d3ddf9cd4ed9df9debc6b07d7c00636e89ca4137a593c2'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != (QUEST,) or
            tuple(x['record']['id'] for x in d['dependencies']) != (REWARD,) or
            tuple(x['record']['id'] for x in d['evidence_only']) != (ENCHANTMENT,) or
            any(d[k] for k in ('existing_dependencies','skipped'))):
        raise TargetValidationError('Gorishi requires its complete original Quest, reward and enchantment evidence')
    for row in (*d['cards'], *d['dependencies'], *d['evidence_only']):
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Gorishi complete original source changed')
    q, r = d['cards'][0]['record'], d['dependencies'][0]['record']
    if ((q['type'],q['cost'],q['tags']['QUEST_PROGRESS_TOTAL'],q['tags']['QUEST_REWARD_DATABASE_ID']) !=
            ('SPELL',1,12,r['dbf_id']) or (r['type'],r['cost'],r['attack'],r['health'],r['collectible'],
            r['tags']['CLASS'],r['tags']['BATTLECRY']) != ('MINION',5,8,8,False,14,1)):
        raise TargetValidationError('Original twelve-damage Quest or five-cost 8/8 reward changed')
    return d


def qualifying_result(c, *, own_turn=False):
    h = health_result(c.event)
    if (h is None or h.flow != HealthFlow.DAMAGE.value or h.damage_dealt != 2 or
            h.target_controller != 3-c.player_id or own_turn and h.active_player != c.player_id):
        return None
    if h.source_controller is None:
        if h.damage_kind == DamageKind.FATIGUE.value: return None
        raise UnsupportedDefinitionError('Exactly-two damage requires known original source ownership')
    return h if h.source_controller == c.player_id else None


def register_damage_quest_reward_cards(registry):
    def progress(c):
        h = qualifying_result(c, own_turn=True)
        q = c.source.quest_progress
        if h is None or q is None: return ()
        return (AdvanceQuest(c.source_id,q.id,q.stage,key=f'health:{h.batch_id}:{h.packet_index}'),)

    def bonus(c):
        h = qualifying_result(c)
        if h is None or h.player_origin is not None and h.player_origin.spec_id == RULE:
            return ()
        if c.player_effect is None or c.player_effect.spec_id != RULE:
            raise ResolutionError('Gorishi bonus requires its actual accepted player program')
        return (PlayerEffectDamage(c.player_id,c.player_effect,h.target_id,2,original_target_result=h.payload()),)

    registry.register_behavior(PREFIX+'progress',progress)
    registry.register_behavior(PREFIX+'reward',lambda c:(AddToHand(c.player_id,REWARD,source_id=c.source_id),))
    registry.register_behavior(PREFIX+'install',lambda c:(AddPlayerEffect(c.player_id,RULE,c.source_id,capture_health_source=True),))
    registry.register_behavior(PREFIX+'bonus',bonus)
    d = load_batch()
    for row in (*d['cards'], *d['dependencies']):
        raw = row['record']; cid = raw['id']
        extra = dict(keywords=(Keyword.QUEST,),quest=QuestSpec('quest',(
            QuestStageSpec(QUEST,12,('health_resolved',),PREFIX+'progress',PREFIX+'reward'),))) if cid == QUEST else dict(battlecry=PREFIX+'install')
        card = CardDefinition(cid,raw['name'],CardType.SPELL if cid==QUEST else CardType.MINION,
            cost=raw['cost'],attack=raw['attack'] if cid==REWARD else 0,
            health=raw['health'] if cid==REWARD else 0,metadata=metadata_from_record(raw),**extra)
        registry.register_card(card)
        if cid not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_player_effect(PlayerEffectSpec(RULE,REWARD,
        triggers=(TriggerSpec('health_resolved',PREFIX+'bonus'),)))
