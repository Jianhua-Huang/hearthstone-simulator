"""Real targeted and whole-inventory consumers of local physical spell bonuses."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, TargetMode, TargetSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.stored_spell_damage import GrantStoredSpellDamage
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/stored-spell-bonus-v1.json'
BATCH_HASH = 'c25aa174b4ec867c8510e26308889c1fecb3745f71933db1378e68f6bc95f134'
BOMBER = 'CATA_209'
KALEC = 'CATA_458'
ROOTS = (BOMBER, KALEC)
PREFIX = 'cards.stored_spell_bonus.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Stored spell bonus source pin changed')
    if tuple(row['record']['id'] for row in data['cards']) != ROOTS or data['dependencies'] or data['evidence_only']:
        raise TargetValidationError('Unreviewed stored spell bonus family')
    for row in data['cards']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Stored spell bonus complete source row changed')
    return data


def register_stored_spell_bonus_cards(registry):
    def bomber(c):
        return () if c.target_id is None else (GrantStoredSpellDamage(
            CardReference.capture(c.state.entities[c.target_id]), 1, c.source_id),)

    def kalec(c):
        player = c.state.players[c.player_id]
        return tuple(GrantStoredSpellDamage(CardReference.capture(c.state.entities[i]), 1, c.source_id)
            for i in (*player.hand, *player.deck) if c.state.entities[i].kind == CardType.SPELL)

    registry.register_behavior(PREFIX+'bomber', bomber)
    registry.register_behavior(PREFIX+'kalec', kalec)
    for row in load_batch()['cards']:
        raw = row['record']; cid = raw['id']
        if raw['type'] != 'MINION' or not raw['collectible'] or raw['tags'].get('BATTLECRY') != 1:
            raise TargetValidationError('Stored spell bonus requires its complete real battlecry face')
        target = TargetSpec(TargetMode.IF_AVAILABLE, zones=(Zone.HAND,), kinds=(CardType.SPELL,),
                            relation='friendly') if cid == BOMBER else None
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'],
            health=raw['health'], battlecry=PREFIX+('bomber' if cid == BOMBER else 'kalec'), targeting=target,
            metadata=replace(metadata_from_record(raw), deck_identity=cid))
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
