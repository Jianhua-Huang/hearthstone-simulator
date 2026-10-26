"""Native Colaque presence and Gaia's original completed Mech attacks."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.character_attacks import completed_attack, completed_minion_types
from hs_sim.engine.effects import Damage, DamageBatch
from hs_sim.engine.model import AppendageSpec, CardDefinition, CardType, DamageKind, Keyword, KeywordAuraSpec, TriggerSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import characters

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT / 'data/cards/past-colaque-gaia-v1.json'
BATCH_HASH = 'd3c5f26e7d1540b3abfeefca08dd8f6fba0a14a464efb653125c6c8d5fac8556'
REFERENCE_PATH = ROOT / 'data/cards/past-colossal-local-reference-v1.json'
REFERENCE_HASH = '6f4881cac0e225c31ede9eb6f83e115d942ace6641246e36f1030950eb9c4bdf'
COLAQUE, GAIA, SHELL = 'TSC_026', 'TSC_029', 'TSC_026t'
DRILLS = ('TSC_029t', 'TSC_029t2')
BODY = 'cards.past_colaque_gaia.mech_attack'
COLLECTIBLE_ROOTS = ()
DEPENDENCIES = (COLAQUE, GAIA)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    reference = json.loads(REFERENCE_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data) != BATCH_HASH or canonical_digest(reference) != REFERENCE_HASH or
            tuple(r['record']['id'] for r in data['cards']) != DEPENDENCIES or
            tuple(r['record']['id'] for r in data['existing_dependencies']) != (SHELL, *DRILLS) or
            any(data[k] for k in ('dependencies', 'evidence_only', 'skipped')) or
            data['reference_document'] != REFERENCE_PATH.relative_to(ROOT).as_posix() or
            data['reference_canonical_sha256'] != REFERENCE_HASH or data['formal_pool_complete'] is not False or
            data['cn_calibrated'] is not False or any(canonical_digest(r['record']) != r['record_sha256']
                for r in data['cards'] + data['existing_dependencies'])):
        raise TargetValidationError('Colaque and Gaia require their complete native records and unchanged reference')
    return data


def register_past_colaque_gaia(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        cid = row['record']['id']
        if (canonical_digest(asdict(registry.card(cid))) != row['definition_sha256'] or
                canonical_digest(asdict(registry.pool_card(cid))) != row['pool_card_sha256']):
            raise TargetValidationError('Colaque/Gaia changed a complete old appendage: ' + cid)
    cards = []
    for row in data['cards']:
        raw = row['record']; cid = raw['id']; limbs = data['appendages'][cid]
        if cid in registry.cards: raise TargetValidationError('Colaque/Gaia cannot overwrite an old definition')
        fields = dict(keyword_auras=(KeywordAuraSpec(Keyword.IMMUNE, target='self',
            condition='controller_controls_named_minion', card_ids=(SHELL,)),)) if cid == COLAQUE else dict(
                triggers=(TriggerSpec('attack_finished', BODY),))
        positions = ('right',) if cid == COLAQUE else ('left', 'right')
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'],
            health=raw['health'], metadata=metadata_from_record(raw), keywords=(Keyword.COLOSSAL,),
            colossal=tuple(AppendageSpec(limb, side) for limb, side in zip(limbs, positions)), **fields)
        registry._validate_card(card); cards.append(card)
    def mech_attack(c):
        attack = completed_attack(c)
        if (attack is None or not living_source(c) or attack.source_kind != CardType.MINION or
                attack.combat.player_id != c.player_id): return ()
        types = completed_minion_types(c, registry)
        if not types.matches_any(('mech',)): return ()
        return (DamageBatch(tuple(Damage(i, 1, c.source_id, DamageKind.MINION_ABILITY)
            for i in characters(c, registry, 3-c.player_id))),)
    registry.register_behavior(BODY, mech_attack)
    for card in cards:
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
