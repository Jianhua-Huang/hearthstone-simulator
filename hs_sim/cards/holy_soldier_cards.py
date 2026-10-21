"""Two real Holy spells share the original numerical/Shield soldier entry."""
import json
from pathlib import Path

from hs_sim.engine.model import (CardDefinition, CardType, Keyword, PlayerEffectSpec, SpellSchool,
    SummonStats, TriggerSpec)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.remaining_mana_numbers import RemainingManaNumbersProfile
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.spell_source_costs import (SpellSourceCostObserverProfile, SpellSourceCostProfile,
    amount as source_cost, validate_record as validate_source_cost)
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

MARCH,AURA,TOKEN='BE_142','BE_146','BE_142t'
P='cards.holy_soldiers.';SPEC=P+'oathbinder'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/holy-soldiers-v1.json'
BATCH_HASH='4812a79b6e014f61941093de6292379a141a152bf5adf1f66838ccb79f56987a'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=(MARCH,AURA) or
            tuple(x['record']['id']for x in d['dependencies'])!=(TOKEN,) or
            any(d[k]for k in('existing_dependencies','evidence_only','skipped')) or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in d['cards']+d['dependencies'])):
        raise TargetValidationError('Holy soldiers lost their complete two roots and actual shared dependency')
    return d


def register_holy_soldier_cards(registry):
    d=load_batch();rows={x['record']['id']:x['record']for x in d['cards']+d['dependencies']}
    def summon(c,number):
        return(SummonByCard(c.player_id,(SummonEntryMaterial(TOKEN,stats=SummonStats(number,number)),),
            SummonCause.capture(c)),)
    def march(c):
        source_cost(c,registry)
        return summon(c,c.cast.source_cost.quote_input.base_cost)
    def oathbinder(c):
        if c.event is None or c.event.kind!='spell_cast_finished':
            raise ValueError('Oathbinder requires the actual original completed CAST')
        row=cast_record(c.state,dict(c.event.data)['cast_id'])
        if ((row.source_id,row.player_id)!=(c.event.source_id,c.event.player_id) or not row.completed or
                row.interrupted or row.failure is not None):
            raise ValueError('Oathbinder changed its original completed spell identity')
        if row.player_id!=c.player_id or registry.card(row.card_id).spell_school!=SpellSchool.HOLY:return()
        validate_source_cost(c.state,registry,row)
        if row.source_cost is None:raise ValueError('Holy CAST lost its original observed cost')
        return summon(c,row.source_cost.amount)
    registry.register_behavior(P+'march',march);registry.register_behavior(P+'after_holy',oathbinder)
    raw=rows[TOKEN]
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['collectible'],raw['tags'].get('DIVINE_SHIELD'))!=('MINION',1,1,1,False,1):
        raise TargetValidationError('Holy soldiers require the real one-cost 1/1 Shield token')
    card=CardDefinition(TOKEN,raw['name'],CardType.MINION,cost=1,attack=1,health=1,
        keywords=(Keyword.DIVINE_SHIELD,),metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    raw=rows[MARCH]
    if (raw['type'],raw['cost'],raw['tags'].get('CLASS'),raw['tags'].get('SPELL_SCHOOL'),raw['tags'].get('4958'))!=('SPELL',1,5,5,1):
        raise TargetValidationError('March lost its real remaining-mana Holy spell declaration')
    card=CardDefinition(MARCH,raw['name'],CardType.SPELL,cost=1,on_play=P+'march',
        spell_school=SpellSchool.HOLY,metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_spell_source_cost_profile(SpellSourceCostProfile(MARCH))
    registry.register_remaining_mana_numbers_profile(RemainingManaNumbersProfile(MARCH))
    raw=rows[AURA]
    if (raw['type'],raw['cost'],raw['tags'].get('PALADIN_AURA'),raw['tags'].get('OBJECTIVE_AURA'),
            raw['tags'].get('TAG_SCRIPT_DATA_NUM_1'),raw['tags'].get('QUEST_PROGRESS_TOTAL'))!=('SPELL',3,1,1,3,3):
        raise TargetValidationError('Oathbinder lost its original three-turn Holy Aura')
    registry.register_player_effect(PlayerEffectSpec(SPEC,AURA,kind='aura',duration=3,tick_event='turn_ended',
        triggers=(TriggerSpec('spell_cast_finished',P+'after_holy'),)))
    card=CardDefinition(AURA,raw['name'],CardType.SPELL,cost=3,spell_school=SpellSchool.HOLY,
        ongoing_effect_id=SPEC,metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_spell_source_cost_observer(SpellSourceCostObserverProfile(SPEC))
