"""Complete printed Nythendra/token plus explicit internal native subforms."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, Keyword, TriggerSpec
from hs_sim.engine.nythendra_reform import (ROOT, BEETLE, FORMS, SPLIT_BODY, REFORM_BODY,
    SplitNythendra, ReformNythendra)
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/nythendra-beetles-v1.json'
BATCH_HASH = 'd07521c935bd4807703202f4ba228fd27fc484f3ca136252261893aefe070003'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (ROOT, BEETLE) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped')) or
            tuple(x['card_id'] for x in data['derived_forms']) != tuple(FORMS[n] for n in range(1, 7))):
        raise TargetValidationError('Nythendra requires both complete faces and explicit compiled forms')
    for row in data['cards']:
        if canonical_digest(row['record']) != row['record_sha256']: raise TargetValidationError('Nythendra complete source row changed')
    return data


def register_nythendra_beetle_cards(registry):
    def split(c):
        if c.deathrattle is None: raise ValueError('Nythendra requires an actual Deathrattle invocation')
        return (SplitNythendra(c.deathrattle.id, SummonCause.capture(c), deathrattle_position(c)),)
    def reform(c):
        if c.event.player_id != c.player_id: return ()
        return (ReformNythendra(MinionReference.capture(c.source), SummonCause.capture(c), c.event),)
    registry.register_behavior(SPLIT_BODY, split)
    registry.register_behavior(REFORM_BODY, reform)
    root_raw, token_raw = (x['record'] for x in load_batch()['cards'])
    root = CardDefinition(ROOT, root_raw['name'], CardType.MINION, cost=7, attack=7, health=7,
        keywords=(Keyword.TAUNT,), deathrattle=SPLIT_BODY, metadata=metadata_from_record(root_raw))
    registry.register_card(root)
    registry.register_card(CardDefinition(BEETLE, token_raw['name'], CardType.MINION, cost=1, attack=1, health=1,
        triggers=(TriggerSpec('turn_started', REFORM_BODY),), metadata=metadata_from_record(token_raw)))
    for n in range(1, 7):
        registry.register_card(replace(root, id=FORMS[n], cost=n, attack=n, health=n,
            metadata=replace(root.metadata, collectible=False, deck_identity=ROOT)))
