"""Three native Druid Battlecries consume frozen mana-held conditions."""
import json
from dataclasses import asdict
from pathlib import Path
from hs_sim.engine.effects import AddToHand, ChangeManaCrystals, GainTemporaryMana
from hs_sim.engine.held_mana import satisfied
from hs_sim.engine.model import CardDefinition, CardType, CostSpec, HandProgressSpec, Keyword
from hs_sim.engine.pools import FillHandFromPool, GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import canonical_digest, TargetValidationError
from .metadata import metadata_from_record

TREANT, DRAGON, MERITHRA, WHELP = 'CATA_131', 'CATA_132', 'CATA_140', 'CATA_132t'
ROOTS = (TREANT, DRAGON, MERITHRA)
PREFIX = 'cards.native_held_mana.'
PATH = Path(__file__).resolve().parents[2]/'data/cards/native-held-mana-v1.json'
PIN = 'bd45711d7682dba3fdb6c8f51d409800ccf1ba61073163e907a9214daa422e63'


def load_batch():
    d = json.loads(PATH.read_text('utf-8'))
    if (canonical_digest(d) != PIN or tuple(x['record']['id'] for x in d['cards']) != ROOTS or
            tuple(x['record']['id'] for x in d['dependencies']) != (WHELP,) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in d['cards']+d['dependencies'])):
        raise TargetValidationError('Held mana native sources changed')
    return d


def register_native_held_mana_cards(r):
    def treant(c):
        return (ChangeManaCrystals(c.player_id, 1, filled=True),) if satisfied(c) else (GainTemporaryMana(c.player_id, 1),)
    def dragon(c):
        if satisfied(c):
            return tuple(SummonByCard(c.player_id, (SummonEntryMaterial(WHELP),), SummonCause.capture(c)) for _ in range(2))
        return tuple(AddToHand(c.player_id, WHELP, c.source_id) for _ in range(2))
    def merithra(c):
        return (FillHandFromPool(GenerateFromPool(c.player_id, 'constructed.cards',
            PoolQuery(kinds=(CardType.MINION,), collectible=True, tribes_any=('dragon',)), source_id=c.source_id,
            cost=CostSpec(set_to=1) if satisfied(c) else None)),)
    for cid, body in ((TREANT, treant), (DRAGON, dragon), (MERITHRA, merithra)):
        r.register_behavior(PREFIX+cid, body)
    d = load_batch()
    for item in d['cards']+d['dependencies']:
        raw = item['record']; cid = raw['id']; kw = {}
        if cid == WHELP: kw['keywords'] = (Keyword.TAUNT,)
        else:
            kw.update(battlecry=PREFIX+cid, hand_progress=HandProgressSpec('mana_spent',
                      goal=raw['tags']['TAG_SCRIPT_DATA_NUM_1'], amount_basis='event_amount'))
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'],
                              health=raw['health'], metadata=metadata_from_record(raw), **kw)
        if cid in r.cards:
            if cid != WHELP or json.loads(json.dumps(asdict(r.card(cid)))) != d['existing_definition_pins'][cid]:
                raise TargetValidationError('Held mana dependency changed its complete accepted declaration')
        else: r.register_card(card)
        if cid not in r.pool_cards: r.register_pool_card(PoolCard.from_definition(card))
