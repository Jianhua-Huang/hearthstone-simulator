"""Three real native live providers over the existing damage/aura/cost layers."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import AuraSpec,CardDefinition,CardType,CostAuraSpec,CostSpec,Keyword,NativeSourceCondition
from hs_sim.engine.effects import Damage,Draw,InvokeBehavior
from hs_sim.engine.model import DamageKind
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-conditional-sources-v1.json'
BATCH_HASH='ac612c5d137cb1592a48ae55145e9645a3b4144f31da491a77030e1a2c47fede'
SCRIPTS={'END_022':'damaged_spell_damage','JAIL_202':'own_turn_hero_attack','TIME_606':'small_hand_power_cost'}


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(value)!=BATCH_HASH:raise TargetValidationError('Native conditional sources lost their complete reviewed source pin')
    return value


def register_native_conditional_cards(registry):
    data=load_batch()
    row=data['dependencies'][0];raw=row['record']
    if (len(data['dependencies'])!=1 or raw['id']!='HERO_07bp'or raw['type']!='HERO_POWER'or
            canonical_digest(raw)!=row['record_sha256']or row['recipe']!=dict(script='life_tap',draw=1,self_damage=2)):
        raise TargetValidationError('Life Tap lost its complete actual Hero Power dependency')
    registry.register_behavior('cards.native_conditions.life_tap_after',lambda c:(
        Damage(c.state.players[c.player_id].hero_id,2,c.source_id,DamageKind.HERO_POWER),))
    registry.register_behavior('cards.native_conditions.life_tap',lambda c:(Draw(c.player_id,source_id=c.source_id),
        InvokeBehavior('cards.native_conditions.life_tap_after',c.source_id,c.player_id)))
    registry.register_card(CardDefinition(raw['id'],raw['name'],CardType.HERO_POWER,cost=raw['cost'],
        on_use='cards.native_conditions.life_tap',metadata=metadata_from_record(raw)))
    for row in data['cards']:
        raw,recipe=row['record'],row['recipe'];script=recipe['script']
        if canonical_digest(raw)!=row['record_sha256']or raw['type']!='MINION'or not raw['collectible']or SCRIPTS.get(raw['id'])!=script:
            raise TargetValidationError('Unreviewed native conditional minion face')
        if script=='damaged_spell_damage':
            kwargs=dict(spell_damage=recipe['amount'],native_condition=NativeSourceCondition('self_damaged'))
        elif script=='own_turn_hero_attack':
            kwargs=dict(auras=(AuraSpec(attack=recipe['amount'],target='friendly_hero',condition='controller_turn'),))
        else:
            kwargs=dict(cost_auras=(CostAuraSpec(CostSpec(set_to=recipe['set_to'],card_types=(CardType.HERO_POWER,))),),
                native_condition=NativeSourceCondition('controller_hand_at_most',recipe['max_hand']))
        card=CardDefinition(raw['id'],raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),keywords=tuple(Keyword(x)for x in recipe['keywords']),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
