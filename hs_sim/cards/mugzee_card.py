"""Original Mug'Zee opening qualifications and its two native passive skills."""
import json
from pathlib import Path

from hs_sim.engine.deck_conditions import DeckCondition,matches_deck_condition
from hs_sim.engine.effects import ReplaceHeroPower
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hero_powers import AddHeroPower
from hs_sim.engine.model import (BattlecryRepeatSpec,CardDefinition,CardType,CostAuraSpec,
    CostSpec,OpeningHook)
from hs_sim.engine.opening_deck_copies import is_hook_source
from hs_sim.engine.passive_hero_powers import PassiveHeroPowerProfile
from hs_sim.engine.play_history import starting_deck_identity
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT,MUG,ZEE='JAIL_800','JAIL_800hp1','JAIL_800hp2'
OPENING='cards.mugzee.opening'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/mugzee-v1.json'
BATCH_HASH='181f69064fa09f68abac7295d530ed7dc819f6ae77a57ce69355f0366a2d7756'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=(ROOT,)or
            tuple(x['record']['id']for x in d['dependencies'])!=(MUG,ZEE)or
            tuple(x['record']['id']for x in d['evidence_only'])!=('JAIL_800e','JAIL_800hp1e','JAIL_800hp2e')or
            d['existing_dependencies']or d['skipped']):raise TargetValidationError('MugZee requires complete root and both passive power sources')
    for row in d['cards']+d['dependencies']+d['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('MugZee complete original source changed')
    raw=d['cards'][0]['record'];mug,zee=(x['record']for x in d['dependencies'])
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],mug['tags'].get('TAG_SCRIPT_DATA_NUM_1'),
            zee['tags'].get('ENTITY_TAG_THRESHOLD_VALUE'))!=('MINION',6,6,7,3,5):
        raise TargetValidationError('MugZee changed its printed body, turn unlock or fifth-minion threshold')
    if any(x['tags'].get('COLLECTION_RELATED_CARD_DATABASE_ID')!=raw['dbf_id']for x in(mug,zee)):
        raise TargetValidationError('MugZee skills lost their real original root')
    return d


def register_mugzee_card(registry):
    d=load_batch()
    def opening(c):
        if not is_hook_source(c.state,c.source_id,c.player_id,ROOT):raise ResolutionError('MugZee requires its genuine original before-deal source')
        _entities,submitted=starting_deck_identity(c.state)
        mug=all(cid==ROOT or registry.card(cid).kind!=CardType.MINION for cid in submitted[c.player_id-1])
        zee=matches_deck_condition(c.state,registry,c.player_id,DeckCondition('starting','no_spells'))
        work=[]
        if mug:work.append(ReplaceHeroPower(c.player_id,MUG,source_id=c.source_id))
        if zee:work.append((AddHeroPower if mug else ReplaceHeroPower)(c.player_id,ZEE,source_id=c.source_id))
        return tuple(work)
    registry.register_behavior(OPENING,opening)
    raw=d['cards'][0]['record']
    registry.register_card(CardDefinition(ROOT,raw['name'],CardType.MINION,cost=6,attack=6,health=7,
        opening_hooks=(OpeningHook('before_deal',OPENING),),metadata=metadata_from_record(raw)))
    for item in d['dependencies']:
        raw=item['record'];cid=raw['id']
        kw={'cost_auras':(CostAuraSpec(CostSpec(delta=-2,card_types=(CardType.MINION,)),first_per_turn=True),)}if cid==MUG else{
            'battlecry_repeats':(BattlecryRepeatSpec(2,(CardType.MINION,)),)}
        registry.register_card(CardDefinition(cid,raw['name'],CardType.HERO_POWER,cost=0,
            passive_hero_power=True,target_rule='any_entity',metadata=metadata_from_record(raw),**kw))
    registry.register_passive_hero_power_profile(PassiveHeroPowerProfile(MUG,unlock_owner_turn=3))
    registry.register_passive_hero_power_profile(PassiveHeroPowerProfile(ZEE,battlecry_period=5))
    for cid in(ROOT,MUG,ZEE):
        if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(registry.card(cid)))
