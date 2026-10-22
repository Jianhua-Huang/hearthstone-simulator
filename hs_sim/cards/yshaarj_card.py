"""Y'Shaarj's actual paid-Minion condition and four ordinary shared recipes."""
import json
from pathlib import Path

from hs_sim.engine.board_presence import capture_board_presence
from hs_sim.engine.effects import AddCostModifier, AddToHand, ForceAttack
from hs_sim.engine.model import (ActivatedAbilitySpec, CardDefinition, CardType, CostSpec,
    Keyword, PaymentType, TimedKeywordSpec)
from hs_sim.engine.named_summon_followups import original_pool_delivery
from hs_sim.engine.play_history import played_cards
from hs_sim.engine.pools import PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.sacrifice import BuffCapturedMinion, GrantCapturedKeyword
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import minions

CARD = 'BE_784'
GAZE, MIGHT, SPAWN, DOMAIN = 'BE_784t1', 'BE_784t3', 'BE_784t2', 'BE_784t4'
SKILLS = (GAZE, MIGHT, SPAWN, DOMAIN)
PREFIX = 'cards.yshaarj.'
COPY = PREFIX+'original_copy'
IMMUNITY = TimedKeywordSpec(Keyword.IMMUNE)
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/yshaarj-v1.json'
BATCH_HASH = '68c8f5ab21b652933047165b1c0baec57af52ca9731f54f6ea454d3de851ec57'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(r['record']['id'] for r in data['cards']) != (CARD,) or
            tuple(r['record']['id'] for r in data['dependencies']) != SKILLS or
            any(data[k] for k in ('existing_dependencies', 'evidence_only', 'skipped')) or
            any(canonical_digest(r['record']) != r['record_sha256'] for r in data['cards']+data['dependencies']) or
            data['official_faces_verified'] != 10):
        raise TargetValidationError('Yshaarj requires five complete pinned rows and ten full primary faces')
    return data


def register_yshaarj_card(registry):
    batch = load_batch(); raw = batch['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['collectible'],
            raw['tags'].get('OLD_GOD'), raw['tags'].get('BATTLECRY'),
            raw['tags'].get('TAG_SCRIPT_DATA_NUM_1')) != ('MINION', 10, 10, 10, True, 1, 1, 30):
        raise TargetValidationError('Yshaarj lost its actual ten-cost 10/10 thirty-Mana Battlecry')
    def battlecry(c):
        # Original paid hand roots include this minion's own committed payment.
        # Powers, hand actions, summons, effect casts and other resources are absent.
        spent = sum(row.cost for row in played_cards(c.state, c.player_id, kind=CardType.MINION)
            if row.payment == PaymentType.MANA)
        if spent < 30 or not living_source(c): return ()
        return (GrantCapturedKeyword(capture_board_presence(c.state, c.source_id), Keyword.IMMUNE,
            c.source_id, duration=IMMUNITY),)
    def gaze(c):
        if not living_source(c): return ()
        source = capture_board_presence(c.state, c.source_id)
        return tuple(ForceAttack(capture_board_presence(c.state, identity), source)
            for identity in minions(c, registry, 3-c.source.controller))
    def might(c):
        if not living_source(c): return ()
        board = c.state.players[c.source.controller].board; index = board.index(c.source_id)
        neighbors = {board[i] for i in (index-1, index+1) if 0 <= i < len(board)}
        actors = tuple(c.state.entities[i] for i in minions(c, registry, c.source.controller) if i in neighbors)
        return (BuffCapturedMinion(capture_board_presence(c.state, c.source_id),
            sum(e.attack for e in actors), sum(e.health for e in actors), c.source_id),)
    def spawn(c):
        return (SummonFromPool(c.player_id, 'constructed.cards',
            PoolQuery(kinds=(CardType.MINION,), min_cost=8, collectible=True), source_id=c.source_id,
            cause=SummonCause.capture(c), on_summon=COPY, followup_policy='original_delivery'),)
    def copy(c):
        original = original_pool_delivery(c)
        return (AddToHand(c.player_id, original.card_id, c.source_id),)
    def domain(c):
        return (AddCostModifier(c.player_id, CostSpec(delta=-5), uses_remaining=1, source_id=c.source_id),)
    registry.register_behavior(PREFIX+'battlecry', battlecry)
    registry.register_behavior(COPY, copy)
    for cid, body in ((GAZE, gaze), (MIGHT, might), (SPAWN, spawn), (DOMAIN, domain)):
        registry.register_behavior(PREFIX+cid, body)
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=10, attack=10, health=10,
        keywords=(Keyword.OLD_GOD,), metadata=metadata_from_record(raw), battlecry=PREFIX+'battlecry',
        activated_abilities=tuple(ActivatedAbilitySpec(cid, PREFIX+cid, card_id=cid) for cid in SKILLS))
    registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
    for entry in batch['dependencies']:
        r = entry['record']
        registry.register_card(CardDefinition(r['id'], r['name'], CardType.SPELL, cost=0,
            choice_only=True, metadata=metadata_from_record(r)))
