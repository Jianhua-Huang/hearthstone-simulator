"""Godfrey's genuine opening program; later minion play has no opening effect."""
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType,OpeningHook,PlayerEffectSpec
from hs_sim.engine.overdraw_returns import SOURCE,PROGRAM
from hs_sim.engine.opening_deck_copies import is_hook_source
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/overdraw-return-v1.json'
BATCH_HASH='d8ce321a271ee641a24988c1155accfe44ae11fa849f0fb13fbeaf8bcc19538b'
OPEN='cards.godfrey.opening'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=(SOURCE,)or
            tuple(x['record']['id']for x in d['evidence_only'])!=('JAIL_509e',)or
            any(d[k]for k in ('dependencies','existing_dependencies','skipped'))):
        raise TargetValidationError('Godfrey requires his complete reviewed face and native program hint')
    for x in (*d['cards'],*d['evidence_only']):
        if canonical_digest(x['record'])!=x['record_sha256']:raise TargetValidationError('Godfrey complete source row changed')
    return d


def register_overdraw_return_card(registry):
    def opening(c):
        if c.state.opening is None or not is_hook_source(c.state,c.source_id,c.player_id,SOURCE):
            raise ValueError('Godfrey requires his original accepted opening source')
        if any(p.spec_id==PROGRAM for p in c.state.players[c.player_id].player_effects):return ()
        return (AddPlayerEffect(c.player_id,PROGRAM,c.source_id),)
    registry.register_behavior(OPEN,opening)
    registry.register_player_effect(PlayerEffectSpec(PROGRAM,SOURCE))
    raw=load_batch()['cards'][0]['record']
    registry.register_card(CardDefinition(SOURCE,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        opening_hooks=(OpeningHook('before_deal',OPEN),),metadata=metadata_from_record(raw)))
