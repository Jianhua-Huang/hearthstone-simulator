"""Three native passive sources over original armor, entry and death facts."""
import json
from pathlib import Path

from hs_sim.engine.armor_gains import ArmorGainBonusProfile, EVENT, extra_from_context
from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardDefinition, CardType, CostSpec, Keyword,
    KeywordAuraSpec, TimedKeywordSpec, TriggerSpec, Zone)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.zones import CopyCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROCKSTAR, RHINO, DEAD = 'ETC_355', 'TRL_327', 'TRL_502'
DEPENDENCIES = (ROCKSTAR, RHINO, DEAD)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_passive_armor_spirit.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-passive-armor-spirit-cards-v1.json'
BATCH_HASH = 'd4a0ff6705490896c87b7a44e9f4d4ece7457e1d10dec86929958569c272a375'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(data['collectible_leaf_ids'])!=DEPENDENCIES or
            tuple(x['record']['id']for x in data['dependencies'])!=DEPENDENCIES or
            data['numeric_normalizations']!={RHINO:{'attack':0},DEAD:{'attack':0}} or
            any(data[k]for k in('cards','existing_dependencies','evidence_only','choice_only','skipped','display_normalizations'))or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in data['dependencies'])):
        raise TargetValidationError('Passive armor/spirit recipes lost their complete original sources')
    return data


def register_past_passive_armor_spirit_cards(registry):
    registry.register_behavior(PREFIX+'armor',lambda c:extra_from_context(c,registry))
    def dead(c):
        if c.event is None or c.event.kind!='minion_died':
            raise ResolutionError('Spirit of the Dead requires its original complete minion death')
        if c.event.player_id!=c.player_id:return ()
        identity=dict(c.event.data)['death_id']
        if type(identity)is not int:raise ResolutionError('Spirit of the Dead lost its original death identity')
        row=next((d for d in c.state.death_history if d.id==identity),None)
        if row is None:raise ResolutionError('Spirit of the Dead lost its original frozen death record')
        if row.controller!=c.player_id or row.zone!=Zone.BOARD:return ()
        if (row.entity_id,row.id)!=(c.event.target_id,dict(c.event.data)['death_id']):
            raise ResolutionError('Spirit of the Dead substituted its original physical death')
        return shuffled(c,(CopyCard(row,c.player_id,Zone.DECK,mode='base',source_id=c.source_id,
            cost=CostSpec(set_to=1)),))
    registry.register_behavior(PREFIX+'dead',dead)
    for item in load_batch()['dependencies']:
        raw=item['record'];cid=raw['id']
        if (raw['type'],raw['collectible'],raw['cost'],raw['attack'],raw['health'])!=(
                'MINION',True,1,1 if cid==ROCKSTAR else None,3):
            raise TargetValidationError('Passive armor/spirit printed body changed')
        if cid==ROCKSTAR:
            fields=dict(triggers=(TriggerSpec(EVENT,PREFIX+'armor'),))
        else:
            fields=dict(keywords=(Keyword.STEALTH,),timed_keywords=(TimedKeywordSpec(Keyword.STEALTH),))
            if cid==RHINO:
                fields['keyword_auras']=(KeywordAuraSpec(Keyword.IMMUNE,'friendly_minions',True,
                    condition='rush_summon_turn'),)
            else:
                fields['triggers']=(TriggerSpec('minion_died',PREFIX+'dead'),)
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=1,attack=raw['attack'] or 0,health=3,
            metadata=metadata_from_record(raw),**fields)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
        if cid==ROCKSTAR:
            registry.register_armor_gain_bonus_profile(ArmorGainBonusProfile(cid,PREFIX+'armor'))
