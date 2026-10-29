"""Actual Varian deck-top slots and Vol'jin's original physical swap."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.minion_hand_swaps import SwapWithControllerHand
from hs_sim.engine.model import CardDefinition, CardType, TargetMode, TargetSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.recruit_summons import RecruitTopMinionOrDraw
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT / 'data/cards/varian-voljin-dependencies-v1.json'
BATCH_HASH = '3b18d6ce597068337d5e23294b9c06ccf5ac8e50118e91fa610f77a6d42544af'
VARIAN, VOLJIN = CARDS = ('AT_072', 'BAR_080')
PREFIX = 'cards.varian_voljin.'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d) != BATCH_HASH or d['schema'] != 1 or d['slot_count'] != 3 or
            tuple(v['record']['id'] for v in d['cards']) != CARDS or
            len(d['official_observations']) != 4 or
            any(d[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only',
                'new_standard_roots', 'membership_uses_executable_coverage', 'formal_pool_complete', 'cn_calibrated'))):
        raise TargetValidationError('Varian and Voljin require their complete native source rows and explicit local policies')
    parent = json.loads((ROOT / d['parent_source_document']).read_text(encoding='utf8'))
    if (canonical_digest(parent) != d['parent_source_document_canonical_sha256'] or
            parent['source_parent']['record']['id'] != 'WON_113'):
        raise TargetValidationError('Varian and Voljin lost the original faction-source document')
    for row in d['cards']:
        raw = row['record']
        if (canonical_digest(raw) != row['record_sha256'] or raw['type'] != 'MINION' or
                raw['collectible'] is not True or raw['tags'].get('BATTLECRY') != 1 or
                raw['dbf_id'] not in parent['source_parent']['child_ids']):
            raise TargetValidationError('Varian or Voljin changed its complete raw identity or source role')
    return d


def register_varian_voljin_dependencies(registry):
    d = load_batch(); cards = []
    for row in d['cards']:
        raw = row['record']; cid = raw['id']
        extra = {} if cid == VARIAN else {'targeting': TargetSpec(TargetMode.IF_AVAILABLE,
            zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='any', exclude_source=True)}
        expected_kind = 'three_current_top_minion_or_draw_slots' if cid == VARIAN else 'original_target_controller_hand_swap'
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'],
            health=raw['health'], on_play=PREFIX + ('varian' if cid == VARIAN else 'voljin'),
            metadata=metadata_from_record(raw), **extra)
        if (row['recipe']['kind'] != expected_kind or canonical_digest(asdict(card)) != row['definition_sha256'] or
                cid in registry.cards or cid in registry.pool_cards):
            raise TargetValidationError('Varian or Voljin cannot replace another native face or recipe')
        cards.append(card)

    def varian(c):
        cause = SummonCause.capture(c)
        return (RecruitTopMinionOrDraw(c.player_id, cause),) * 3

    def voljin(c):
        target = c.state.entities.get(c.target_id)
        if (target is None or target.zone != Zone.BOARD or target.kind != CardType.MINION or
                not target.active or target.health <= 0 or target.doomed or
                registry.card(target.card_id).interactable is not None):
            return ()
        return (SwapWithControllerHand(MinionReference.capture(target), SummonCause.capture(c)),)

    registry.register_behavior(PREFIX + 'varian', varian)
    registry.register_behavior(PREFIX + 'voljin', voljin)
    for card in cards:
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
