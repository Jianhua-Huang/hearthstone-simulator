"""Real Skulker over current equipped-weapon custody and native Deathrattles."""
import json
from pathlib import Path
from hs_sim.engine.consumed_cards import ConsumptionProfile,ConsumeEquippedWeapon,ResolveConsumedDeathrattle
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,Keyword,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

SKULKER='DEEP_012'
DEPENDENCIES=(SKULKER,)
COLLECTIBLE_ROOTS=()
P='cards.past_equipped_weapon_custody.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/past-equipped-weapon-custody-v1.json'
BATCH_HASH='90cca3f7364ac72ce065f157e3ef5b716e0b5609477648be0b7023b977ed3618'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(d['collectible_leaf_ids'])!=DEPENDENCIES or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            any(d[k]for k in('cards','existing_dependencies','evidence_only','choice_only','skipped',
                'numeric_normalizations','display_normalizations')) or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in d['dependencies'])):
        raise TargetValidationError('Equipped weapon custody lost its complete original source')
    return d


def register_past_equipped_weapon_custody_cards(registry):
    def take(c):
        if c.source.zone!=Zone.BOARD:return ()
        return(ConsumeEquippedWeapon(MinionReference.capture(c.source),SKULKER),)
    def payload(c):
        if c.deathrattle is None:raise ResolutionError('Skulker return requires its actual Deathrattle')
        if c.deathrattle.ability.consumed_card_id is None:return ()
        return(ResolveConsumedDeathrattle(c.deathrattle.id),)
    registry.register_behavior(P+'take',take);registry.register_behavior(P+'payload',payload)
    raw=load_batch()['dependencies'][0]['record']
    if(raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('RUSH'),
            raw['tags'].get('BATTLECRY'),raw['tags'].get('DEATHRATTLE'))!=('MINION',1,1,1,1,1,1):
        raise TargetValidationError('Skulker requires its actual complete Rush/weapon face')
    card=CardDefinition(SKULKER,raw['name'],CardType.MINION,cost=1,attack=1,health=1,
        keywords=(Keyword.RUSH,),battlecry=P+'take',deathrattle=P+'payload',metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_consumption_profile(ConsumptionProfile(SKULKER,'equipped_weapon'))
