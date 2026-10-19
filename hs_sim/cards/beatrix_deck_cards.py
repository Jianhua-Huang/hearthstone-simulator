"""Commander Beatrix's original construction selection and ordinary start copies."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.deck_shuffles import ShuffleDeckCards
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType, Keyword, OpeningHook
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sideboards import DeckCopySideboardProfile, deck_copy_selection_error
from hs_sim.engine.zones import AddToDeck
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT='JAIL_397'; BODY='cards.beatrix_deck.opening'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/beatrix-deck-copies-v1.json'
BATCH_HASH='655a790dc5c4a2b9cc68b289198b827d54b6475eaa61239e126cc212048c2efc'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(ROOT,)
            or any(data[k]for k in ('dependencies','existing_dependencies','evidence_only'))
            or canonical_digest(data['cards'][0]['record'])!=data['cards'][0]['record_sha256']):
        raise TargetValidationError('Beatrix requires her complete original construction source')
    return data


def register_beatrix_deck_cards(registry):
    def opening(c):
        state=c.state;player=state.players[c.player_id];window=state.opening
        if (window is None or window.stage!='dealing' or c.source_id not in window.original_entities[c.player_id-1]
                or player.original_deck[window.original_entities[c.player_id-1].index(c.source_id)]!=ROOT):
            raise ResolutionError('Beatrix requires her actual original before-deal opening source')
        profile=registry.sideboards[ROOT]
        band=next((b for b in player.sideboards if b.source_card_id==ROOT),None)
        if band is None or band.taken_slots or deck_copy_selection_error(profile,band.cards,registry) is not None:
            raise ResolutionError('Beatrix lost her original valid construction selection')
        entries=tuple(AddToDeck(c.player_id,band.cards[0],source_id=c.source_id)for _ in range(profile.copies))
        return (ShuffleDeckCards(c.player_id,c.player_id,entries,c.source_id),)
    registry.register_behavior(BODY,opening)
    raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'])!=('MINION',5,5,6) or any(
            raw['tags'].get(k)!=v for k,v in {'TAUNT':1,'MAX_SIDEBOARD_CARDS':1,'SIDEBOARD_TYPE':3,
                'ALLOWED_SIDEBOARD_SUBSET':74,'SIDEBOARD_CARDS_COUNT_AS_MAX':1,'START_OF_GAME_KEYWORD':1}.items()):
        raise TargetValidationError('Beatrix changed her original face or sideboard declaration')
    card=CardDefinition(ROOT,raw['name'],CardType.MINION,cost=5,attack=5,health=6,keywords=(Keyword.TAUNT,),
        opening_hooks=(OpeningHook('before_deal',BODY),),metadata=replace(metadata_from_record(raw),deck_identity=ROOT))
    registry.register_card(card);registry.register_sideboard(DeckCopySideboardProfile(ROOT))
    if ROOT not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
