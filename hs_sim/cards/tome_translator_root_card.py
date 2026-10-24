"""Unresolved Tome Translator consumes fixed branches and ordinary held progress."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import ChoiceOption, InvokeBehavior
from hs_sim.engine.hand_upgrades import UpgradeHandCard
from hs_sim.engine.model import CardDefinition, CardType, HandProgressSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.random_effect_choices import ChooseRandomEffects
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .tome_translator_cards import FORMS, PREFIX

ROOT = 'BE_327'
COLLECTIBLE_ROOTS = (ROOT,)
BODY, REVEAL, OWN_TURN = (PREFIX+'root.'+name for name in ('battlecry', 'reveal', 'own_turn'))
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/tome-translator-root-v1.json'
BATCH_HASH = '32e3faa89e4920e7b261b30c84640a07ff7f5494ec68b4a6346d3584ab8f01ab'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['cards'] + data['existing_dependencies'] + data['evidence_only']
    if (canonical_digest(data) != BATCH_HASH or tuple(row['record']['id'] for row in rows) !=
            (ROOT, *FORMS, 'BE_327te', 'BE_327te2') or
            any(data[key] for key in ('dependencies', 'choice_only', 'skipped')) or
            len(data['random_form_order']) != 4 or set(data['random_form_order']) != set(FORMS) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in rows)):
        raise TargetValidationError('Tome Translator root lost its complete actual source children')
    by_dbf = {row['record']['dbf_id']: row['record']['id'] for row in data['existing_dependencies']}
    for observation in data['official_observations']:
        if tuple(by_dbf[cid] for cid in observation['face']['childIds']) != tuple(data['random_form_order']):
            raise TargetValidationError('Tome Translator root changed its complete primary child order')
    return data


def register_tome_translator_root_card(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        cid = row['record']['id']
        if canonical_digest(asdict(registry.card(cid))) != row['definition_sha256']:
            raise TargetValidationError('Tome Translator root changed an existing decoded body')
        registry.behavior(PREFIX+cid)
    order = tuple(data['random_form_order'])

    def battlecry(c):
        return (ChooseRandomEffects(c.player_id, c.source_id, tuple(ChoiceOption(cid, cid,
            (InvokeBehavior(PREFIX+cid, c.source_id, c.player_id, c.target_id,
                play_id=c.play.id if c.play is not None else None),)) for cid in order)),)

    def reveal(c):
        if c.source.zone != Zone.HAND or c.source.card_id != ROOT or c.trigger is None:
            return ()
        if not any(ability.id == c.trigger.id and ability.kind == 'hand_progress' and
                ability.consumed for ability in c.source.abilities):
            return ()
        reference = CardReference.capture(c.source)
        return (ChooseRandomEffects(c.player_id, c.source_id, tuple(ChoiceOption(cid, cid,
            (UpgradeHandCard(reference, cid, c.source_id),)) for cid in order)),)

    registry.register_behavior(BODY, battlecry)
    registry.register_behavior(REVEAL, reveal)
    registry.register_trigger_condition(OWN_TURN, lambda c: c.event is not None and
        c.event.kind == 'turn_started' and c.event.player_id == c.player_id)
    raw = data['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('CLASS'),
            raw['tags'].get('BATTLECRY'), raw['tags'].get('TAG_SCRIPT_DATA_NUM_1')) != (
                'MINION', 4, 5, 4, 12, 1, 2):
        raise TargetValidationError('Tome Translator root requires its original four-cost 5/4 two-turn face')
    card = CardDefinition(ROOT, raw['name'], CardType.MINION, cost=4, attack=5, health=4,
        metadata=metadata_from_record(raw), battlecry=BODY, hand_progress=HandProgressSpec('event',
            goal=2, event='turn_started', condition_id=OWN_TURN, on_complete=REVEAL))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
