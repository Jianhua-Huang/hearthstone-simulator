"""Soulrest Ceremony grants each original minion ordinary removable attachments."""
import json
from pathlib import Path
from hs_sim.engine.limited_triggers import GrantLimitedTrigger
from hs_sim.engine.model import CardDefinition,CardType,EndTurnSpec,Keyword,LimitedTriggerSpec,SpellSchool
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion,DestroyCapturedMinion,GrantCapturedKeyword,MinionReference
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-ceremony-v1.json'
BATCH_HASH='93e4f5f61c15e5d2f925fea9d20a27cdf4c5d01f6fc32f31223d4136ec5ae7b6'
CEREMONY='DINO_417';PREFIX='cards.native_ceremony.'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=(CEREMONY,)
            or any(d[k]for k in('dependencies','existing_dependencies','evidence_only','skipped'))):
        raise TargetValidationError('Ceremony requires its complete reviewed source')
    if any(canonical_digest(x['record'])!=x['record_sha256']for x in d['cards']):
        raise TargetValidationError('Ceremony original full source row changed')
    return d


def register_native_ceremony_cards(registry):
    for player in(1,2):
        registry.register_trigger_condition(PREFIX+f'caster{player}',lambda c,p=player:c.event.player_id==p)
    registry.register_behavior(PREFIX+'destroy',lambda c:(DestroyCapturedMinion(
        MinionReference.capture(c.source),c.trigger.source_id),))
    def body(c):
        refs=tuple(MinionReference.capture(c.state.entities[i])for i in minions(c,registry,c.player_id))
        spec=LimitedTriggerSpec('turn_ended',PREFIX+'destroy',condition_id=PREFIX+f'caster{c.player_id}',
            end_turn=EndTurnSpec('either'))
        return tuple(effect for ref in refs for effect in(
            BuffCapturedMinion(ref,1,0,c.source_id),GrantCapturedKeyword(ref,Keyword.RUSH,c.source_id),
            GrantLimitedTrigger(ref.entity_id,spec,c.source_id,recipient=ref)))
    registry.register_behavior(PREFIX+'body',body)
    raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['tags'].get('SPELL_SCHOOL'))!=('SPELL',6):
        raise TargetValidationError('Ceremony requires its actual Shadow spell')
    card=CardDefinition(CEREMONY,raw['name'],CardType.SPELL,cost=raw['cost'],spell_school=SpellSchool.SHADOW,
        metadata=metadata_from_record(raw),on_play=PREFIX+'body')
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
