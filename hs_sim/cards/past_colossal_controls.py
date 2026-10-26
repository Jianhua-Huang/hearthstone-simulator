"""Two real past Colossals reuse native appendages, Freeze and continuous auras."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import AppendageSpec, AuraSpec, CardDefinition, CardType, Keyword, TriggerSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import DestroyCapturedMinion, MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT / 'data/cards/past-colossal-controls-v1.json'
BATCH_HASH = 'eccd901fd3071435cd24e23f8a39390f6ad16db62e4171ecfad24604b8e634e6'
REFERENCE_PATH = ROOT / 'data/cards/past-colossal-local-reference-v1.json'
REFERENCE_HASH = '6f4881cac0e225c31ede9eb6f83e115d942ace6641246e36f1030950eb9c4bdf'
SINDRAGOSA, CRABATOA = 'NX2_037', 'TSC_937'
BODY = 'cards.past_colossal_controls.destroy_frozen'
COLLECTIBLE_ROOTS = ()
DEPENDENCIES = (SINDRAGOSA, CRABATOA)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    reference = json.loads(REFERENCE_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data) != BATCH_HASH or canonical_digest(reference) != REFERENCE_HASH or
            tuple(row['record']['id'] for row in data['cards']) != DEPENDENCIES or
            any(data[k] for k in ('dependencies', 'evidence_only', 'skipped')) or
            data['reference_canonical_sha256'] != REFERENCE_HASH or
            data['reference_document'] != REFERENCE_PATH.relative_to(ROOT).as_posix() or
            len(reference['candidate_ids']) != 13 or reference['membership_uses_executable_coverage'] is not False or
            reference['runtime_bindings_added'] is not False or data['formal_pool_complete'] is not False or
            data['cn_calibrated'] is not False):
        raise TargetValidationError('Past Colossals require complete independent candidates and original native records')
    if any(canonical_digest(row['record']) != row['record_sha256']
            for row in data['cards'] + data['existing_dependencies']):
        raise TargetValidationError('Past Colossal body or appendage lost its complete original row')
    return data


def destroy_frozen(c):
    if c.event is None or c.event.kind != 'frozen':
        raise ResolutionError('Sindragosa requires the actual new Freeze notification')
    target = c.state.entities.get(c.event.target_id)
    if (not living_source(c) or target is None or target.kind != CardType.MINION or
            target.zone != Zone.BOARD or not target.active or target.health <= 0 or target.doomed or
            target.controller == c.player_id or not target.frozen):
        return ()
    return (DestroyCapturedMinion(MinionReference.capture(target), c.source_id),)


def register_past_colossal_controls(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        cid = row['record']['id']
        if (canonical_digest(asdict(registry.card(cid))) != row['definition_sha256'] or
                canonical_digest(asdict(registry.pool_card(cid))) != row['pool_card_sha256']):
            raise TargetValidationError('Past Colossal changed a complete existing appendage or weapon: ' + cid)
    cards = []
    for row in data['cards']:
        raw = row['record']; cid = raw['id']
        if cid in registry.cards:
            raise TargetValidationError('Past Colossal cannot overwrite a native identity')
        limbs = data['appendages'][cid]
        fields = dict(triggers=(TriggerSpec('frozen', BODY),)) if cid == SINDRAGOSA else dict(auras=(
            AuraSpec(attack=2, card_ids=tuple(limbs)),
            AuraSpec(attack=2, target='friendly_weapon', card_ids=(data['named_weapon_id'],))))
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'],
            attack=raw['attack'], health=raw['health'], keywords=(Keyword.COLOSSAL,),
            colossal=(AppendageSpec(limbs[0], 'left'), AppendageSpec(limbs[1], 'right')),
            metadata=metadata_from_record(raw), **fields)
        registry._validate_card(card); cards.append(card)
    registry.register_behavior(BODY, destroy_frozen)
    for card in cards:
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
