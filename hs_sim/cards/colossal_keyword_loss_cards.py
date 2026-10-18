"""Chromatus' four printed defenses and independent head Deathrattles."""
import json
from pathlib import Path

from hs_sim.engine.model import AppendageSpec, CardDefinition, CardType, Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference, RemoveCapturedKeyword
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

CARD = 'CATA_432'
HEADS = tuple(CARD+'t'+str(i) for i in range(1,5))
FLAGS = (Keyword.TAUNT, Keyword.LIFESTEAL, Keyword.ELUSIVE, Keyword.DIVINE_SHIELD)
ORDER = tuple(reversed(HEADS))
PREFIX = 'cards.chromatus.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/colossal-keyword-loss-v1.json'
BATCH_HASH = '77cc0888f4b0efca7a20352105c50a95eff83c473335b504d65e0587746445b3'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,)
            or tuple(x['record']['id'] for x in data['dependencies']) != HEADS):
        raise TargetValidationError('Chromatus requires all four original distinct heads')
    for row in data['cards']+data['dependencies']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Chromatus complete raw source changed')
    return data


def register_colossal_keyword_loss_cards(registry):
    data = load_batch()
    def remove(flag):
        def body(c):
            if c.deathrattle is None:
                raise ValueError('Chromatus head requires its actual Deathrattle context')
            return tuple(RemoveCapturedKeyword(MinionReference.capture(c.state.entities[i]),flag,c.source_id)
                for i in minions(c,registry,c.player_id) if c.state.entities[i].card_id == CARD)
        return body
    for head,flag in zip(HEADS,FLAGS):
        registry.register_behavior(PREFIX+head,remove(flag))
    for row in data['cards']+data['dependencies']:
        raw = row['record']; cid = raw['id']
        fields = dict(keywords=FLAGS+(Keyword.COLOSSAL,),
            colossal=tuple(AppendageSpec(head,'left' if n<2 else 'right') for n,head in enumerate(ORDER))) if cid == CARD else dict(
                keywords=(FLAGS[HEADS.index(cid)],), deathrattle=PREFIX+cid)
        card = CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],
            health=raw['health'],metadata=metadata_from_record(raw),**fields)
        registry.register_card(card)
        if cid not in registry.pool_cards:
            registry.register_pool_card(PoolCard.from_definition(card))
