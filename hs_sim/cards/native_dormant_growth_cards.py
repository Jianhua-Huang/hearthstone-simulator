"""Petrified Ogre: one original dormant self, one ordinary automatic coin flip."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.dormancy import AwakenCapturedMinion, GrowDormantMinion
from hs_sim.engine.effects import ChoiceOption, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType, TriggerSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'TLC_253'
BODY = 'cards.native_dormant_growth.ogre'
SELECTED = BODY + '_selected'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-dormant-growth-v1.json'
BATCH_HASH = 'bc8a66853f0fb671bce3cf536d87f8fa228af866b7e828f3e5fc2df2cc956680'


def load_batch():
    batch = json.loads(BATCH_PATH.read_text('utf-8'))
    if (canonical_digest(batch) != BATCH_HASH or len(batch['cards']) != 1 or
            batch['cards'][0]['record']['id'] != CARD or
            canonical_digest(batch['cards'][0]['record']) != batch['cards'][0]['record_sha256']):
        raise TargetValidationError('Petrified Ogre requires its complete reviewed original source')
    return batch


def register_native_dormant_growth_cards(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['collectible']) != (
            'MINION', 3, 5, 5, True):
        raise TargetValidationError('Petrified Ogre printed face changed')

    def start(c):
        if c.event.player_id != c.player_id or c.source.dormancy is None:
            return ()
        original = dict(reference=asdict(MinionReference.capture(c.source)),
                        dormancy_id=c.source.dormancy.id)
        options = tuple(ChoiceOption(json.dumps(dict(original, branch=branch), sort_keys=True), label)
                        for branch, label in (('grow', '+2/+2'), ('wake', 'Awaken')))
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
                              sample_size=1, on_select=SELECTED),)

    def selected(c):
        if c.choice is None or c.choice.selected_ids or len(c.choice.choice.options) != 1:
            raise ResolutionError('Petrified Ogre lost its original automatic outcome')
        row = json.loads(c.choice.choice.options[0].id)
        reference = MinionReference(**row['reference'])
        if reference.entity_id != c.source_id or reference.player_id != c.player_id:
            raise ResolutionError('Petrified Ogre outcome changed its original self')
        if row['branch'] == 'grow':
            return (GrowDormantMinion(reference, row['dormancy_id'], 2, 2),)
        if row['branch'] == 'wake':
            return (AwakenCapturedMinion(reference, row['dormancy_id'], c.source_id),)
        raise ResolutionError('Petrified Ogre outcome is unknown')

    registry.register_behavior(BODY, start)
    registry.register_behavior(SELECTED, selected)
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=3, attack=5, health=5,
                          dormant_turns=None, dormant_triggers=(TriggerSpec('turn_started', BODY),),
                          metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
