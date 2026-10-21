"""Show of Force reads actual current-turn armor grants, not the balance."""
import json
from pathlib import Path

from hs_sim.engine.armor_gains import gained_this_turn
from hs_sim.engine.effects import Damage, Destroy, InvokeBehavior
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, TargetSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'BE_559'
BODY = 'cards.armor_gain_history.show_of_force'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/armor-gain-history-v1.json'
BATCH_HASH = '2017f360661d2efea5885d159bd8ffa017ee862c2e4881b5c63c7cf3dc0a3bed'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Show of Force lost its complete reviewed face')
    return data


def register_armor_gain_history_card(registry):
    def body(c):
        return ((Destroy(c.target_id, c.source_id) if gained_this_turn(c.state, c.player_id) else
            Damage(c.target_id, 3, c.source_id, DamageKind.SPELL)),)
    # The original payload context can precede captured start reactions. Read
    # the condition at this effect's execution, then keep that accepted branch.
    registry.register_behavior(BODY, lambda c: (InvokeBehavior(BODY+'.resolve', c.source_id, c.player_id, c.target_id),))
    registry.register_behavior(BODY+'.resolve', body)
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['tags'].get('CLASS'), raw['tags'].get('SPELL_SCHOOL')) != ('SPELL', 2, 10, None):
        raise TargetValidationError('Show of Force requires its complete original Warrior spell')
    card = CardDefinition(CARD, raw['name'], CardType.SPELL, cost=2, on_play=BODY,
        targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)), metadata=metadata_from_record(raw))
    registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
