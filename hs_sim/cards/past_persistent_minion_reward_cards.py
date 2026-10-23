"""Physical permanent growth is distinct from a whole-game named family aura."""
import json
from pathlib import Path

from hs_sim.engine.copy_materials import CapturedCardCopyMaterial
from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.model import (CardDefinition,CardType,Keyword,LimitedTriggerSpec,
    PlayerAuraSpec,PlayerEffectSpec)
from hs_sim.engine.permanent_minion_stats import CreateGrowingMinion
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .recruit_cards import shuffle

RAPTOR,FEEDER,DISPLAY='BAR_031','TSC_653','TOY_803'
DEPENDENCIES=(RAPTOR,FEEDER,DISPLAY)
COLLECTIBLE_ROOTS=()
PREFIX='cards.past_persistent_minion_rewards.'
PROGRAM=PREFIX+'jade_display'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/past-persistent-minion-rewards-v1.json'
BATCH_HASH='ca8eb15e63a9ce224e59ee2dd10432162ae5c8208fe959193dc50f59a3fe4091'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(data['collectible_leaf_ids'])!=DEPENDENCIES or
            tuple(x['record']['id']for x in data['dependencies'])!=DEPENDENCIES or
            any(data[k]for k in('cards','existing_dependencies','choice_only','skipped',
                                'numeric_normalizations','display_normalizations')) or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in data['dependencies']+data['evidence_only'])):
        raise TargetValidationError('Persistent native minions lost their complete reviewed source')
    return data


def register_past_persistent_minion_reward_cards(registry):
    def grow(c,health,position):
        request=CreateGrowingMinion(CapturedCardCopyMaterial.capture(c.state,c.source),
            c.player_id,2,health,position)
        return shuffled(c,(request,))if position=='random'else(request,)
    registry.register_behavior(PREFIX+RAPTOR,lambda c:grow(c,1,'random'))
    registry.register_behavior(PREFIX+FEEDER,lambda c:grow(c,2,'bottom'))
    registry.register_player_effect(PlayerEffectSpec(PROGRAM,DISPLAY,
        auras=(PlayerAuraSpec(1,1,(DISPLAY,),'controlled_minion_cards'),)))
    registry.register_behavior(PREFIX+DISPLAY,lambda c:(AddPlayerEffect(c.player_id,PROGRAM,c.source_id),
        *shuffle(c,DISPLAY,2)))
    for row in load_batch()['dependencies']:
        raw=row['record'];cid=raw['id']
        if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['collectible'])!=(
                'MINION',1,1,1 if cid==DISPLAY else 3,True):
            raise TargetValidationError('Persistent minion original body changed')
        fields={'metadata':metadata_from_record(raw)}
        if cid==RAPTOR:
            if raw['tags'].get('FRENZY')!=1:raise TargetValidationError('Raptor requires its native Frenzy')
            fields.update(keywords=(Keyword.FRENZY,),limited_triggers=(LimitedTriggerSpec.frenzy(PREFIX+cid),))
        else:
            if raw['tags'].get('DEATHRATTLE')!=1:raise TargetValidationError('Persistent minion requires its native Deathrattle')
            fields['deathrattle']=PREFIX+cid
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=1,attack=1,
            health=raw['health'],**fields)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
