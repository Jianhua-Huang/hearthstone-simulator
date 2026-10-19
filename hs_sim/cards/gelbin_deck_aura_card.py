"""Gelbin's real Fabled family and one original deck card per Aura identity."""
import json
from pathlib import Path

from hs_sim.engine.aura_duration import aura_spec
from hs_sim.engine.deck_auras import PutStoredAura
from hs_sim.engine.fabled_decks import FabledSpec
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'TIME_009'
COMPANIONS = ('TIME_009t1', 'TIME_009t2')
BODY = 'cards.gelbin_deck_aura.put'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/gelbin-deck-aura-v1.json'
BATCH_HASH = '2a4810f4c8c0682c9b9b2e2bfd674a65825b8f27ae63cd849af310516dedb30c'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['cards']) != (CARD,) or
            data['dependencies'] or data['skipped'] or tuple(data['fabled_companions']) != COMPANIONS):
        raise TargetValidationError('Gelbin requires his complete original family and Aura source domain')
    rows = data['cards']+data['existing_dependencies']+data['evidence_only']
    for row in rows:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete original Gelbin or Aura record')
    if data['aura_ids'] != sorted(row['record']['id'] for row in rows if row['record']['tags'].get('PALADIN_AURA') == 1):
        raise TargetValidationError('Gelbin Aura eligibility lost its complete fixed-source tag inventory')
    by_id = {row['record']['id']:row['record'] for row in rows}
    children = {by_id[cid]['dbf_id'] for cid in COMPANIONS}
    if len(data['official_observations']) != 2 or any(set(row['face']['childIds']) != children for row in data['official_observations']):
        raise TargetValidationError('Gelbin Fabled companions differ from his full primary card responses')
    return data


def register_gelbin_deck_aura_card(registry):
    data = load_batch()
    domain = frozenset(data['aura_ids'])
    def put(c):
        seen = set()
        work = []
        for entity_id in c.state.players[c.player_id].deck:
            entity = c.state.entities[entity_id]
            if entity.card_id not in domain or entity.card_id in seen:
                continue
            # Known eligible content without executable Aura text is an error.
            # Do not silently trim it or substitute a different physical card.
            aura_spec(registry, entity.card_id)
            seen.add(entity.card_id)
            work.append(PutStoredAura(CardReference.capture(entity), c.player_id, c.source_id))
        return tuple(work)
    registry.register_behavior(BODY, put)
    raw = data['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('FABLED')) != ('MINION',8,6,6,1):
        raise TargetValidationError('Gelbin changed his actual printed body or Fabled requirement')
    for cid in COMPANIONS:
        aura_spec(registry, cid)
    card = CardDefinition(CARD,raw['name'],CardType.MINION,cost=8,attack=6,health=6,
        battlecry=BODY,metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_fabled(FabledSpec(CARD,COMPANIONS))
