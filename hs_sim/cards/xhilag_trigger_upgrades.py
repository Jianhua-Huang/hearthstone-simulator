"""Xhilag upgrades the current physical Stalks using ordinary unit modifiers."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.model import AppendageSpec, CardDefinition, CardType, Keyword, TriggerSpec
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.native_trigger_values import TriggerValueProfile, UpgradeNativeTrigger
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT / 'data/cards/xhilag-trigger-upgrades-v1.json'
BATCH_HASH = '2b1bceac1461258b71fc016333fb94b2ba1b599ac9c945db750e44140cb474af'
CARD = 'TSC_219'
PARTS = ('TSC_219t', 'TSC_219t2', 'TSC_219t3', 'TSC_219t4')
PROFILE = 'native-xhilag-stalk-damage-unit-v1'
BODY = 'cards.xhilag_trigger_upgrades.start'
COLLECTIBLE_ROOTS = ()
DEPENDENCIES = (CARD,)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            tuple(x['record']['id'] for x in data['existing_dependencies']) != PARTS or
            tuple(x['record']['id'] for x in data['evidence_only']) != ('TSC_219e',) or
            data['profile_id'] != PROFILE or data['producer_behavior_id'] != BODY or
            data['initial_value'] != 2 or data['increment'] != 1 or
            any(data[k] for k in ('dependencies', 'skipped')) or data['formal_pool_complete'] is not False or
            data['cn_calibrated'] is not False or any(canonical_digest(x['record']) != x['record_sha256']
                for x in data['cards'] + data['existing_dependencies'] + data['evidence_only'])):
        raise TargetValidationError('Xhilag requires its full original source, four Stalks and actual enchantment')
    reference = json.loads((ROOT/data['reference_document']).read_text(encoding='utf8'))
    if canonical_digest(reference) != data['reference_canonical_sha256']:
        raise TargetValidationError('Xhilag lost its independent full past reference')
    return data


def register_xhilag_trigger_upgrades(registry):
    data = load_batch()
    if CARD in registry.cards: raise TargetValidationError('Xhilag cannot overwrite a native definition')
    if PROFILE in registry.trigger_value_profiles or any(
            set(p.recipient_ids) & set(PARTS) for p in registry.trigger_value_profiles.values()):
        raise TargetValidationError('Xhilag cannot replace an existing native trigger value declaration')
    for row in data['existing_dependencies']:
        cid = row['record']['id']
        if (canonical_digest(asdict(registry.card(cid))) != row['definition_sha256'] or
                canonical_digest(asdict(registry.pool_card(cid))) != row['pool_card_sha256'] or
                row['record']['tags'].get('TAG_SCRIPT_DATA_NUM_1') != 2):
            raise TargetValidationError('Xhilag lost an original complete printed Stalk: ' + cid)
    def start(c):
        if c.event is None or c.event.kind != 'turn_started' or c.source.card_id != CARD:
            raise ResolutionError('Xhilag requires its actual native start-turn producer')
        if not living_source(c) or c.event.player_id != c.player_id: return ()
        source = MinionReference.capture(c.source)
        return tuple(UpgradeNativeTrigger(PROFILE, MinionReference.capture(c.state.entities[i]), source)
            for i in minions(c, registry, c.player_id) if c.state.entities[i].card_id in PARTS)
    raw = data['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health']) != ('MINION', 7, 3, 6):
        raise TargetValidationError('Xhilag lost its original seven-mana 3/6 face')
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=7, attack=3, health=6,
        keywords=(Keyword.COLOSSAL,), metadata=metadata_from_record(raw),
        colossal=tuple(AppendageSpec(cid, side) for cid, side in zip(PARTS, ('left', 'left', 'right', 'right'))),
        triggers=(TriggerSpec('turn_started', BODY),))
    registry._validate_card(card)
    metadata = PoolCard.from_definition(card)
    if CARD in registry.pool_cards and registry.pool_card(CARD) != metadata:
        raise TargetValidationError('Xhilag cannot replace independent printed metadata')
    registry.register_behavior(BODY, start); registry.register_card(card)
    if CARD not in registry.pool_cards: registry.register_pool_card(metadata)
    registry.register_trigger_value_profile(TriggerValueProfile(PROFILE, CARD, BODY, PARTS,
        data['recipient_behavior_id'], data['initial_value'], data['enchantment_card_id']))
