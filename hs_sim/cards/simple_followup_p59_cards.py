"""Original map offers, persistent Dragon Rush and explicit named token consumers."""
import json
from pathlib import Path

from hs_sim.engine.hand_choice_followups import DiscoverForPlayFollowup
from hs_sim.engine.model import (CardDefinition, CardType, HandProgressSpec, Keyword,
    PlayerEffectSpec, PlayerKeywordAuraSpec, SpellSchool, Zone)
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import ChooseFromZone
from hs_sim.targets import TargetValidationError, canonical_digest
from .entry_native_cards import PREFIX as ENTRY_PREFIX
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p59-v1.json'
BATCH_HASH = 'a4ee3d46b582ba352496f70f103b5a5ad733c04143519004ed9302c823b3b95e'
ABYSSIAN, UPGRADED = 'CATA_553', 'CATA_553t'
MURLOC_MAP, FEL_MAP, DECK_MAP = 'TLC_442', 'TLC_900', 'TLC_515'
UND_FORM, ELE_FORM, INF_FORM = 'TLC_452t3', 'TLC_452t6', 'TLC_452t28'
UND_TOKEN, ELE_TOKEN, INF_TOKEN = 'TTN_737t2', 'TTN_862t4', 'TTN_960t5'
ROOTS = (ABYSSIAN, UPGRADED, MURLOC_MAP, FEL_MAP, DECK_MAP,
    UND_FORM, ELE_FORM, INF_FORM, UND_TOKEN, ELE_TOKEN, INF_TOKEN)
EVIDENCE = ('TLC_452', 'TTN_737', 'TTN_862', 'TTN_960', 'TTN_737t1', 'TTN_862t3', 'TTN_960t3')
PREFIX, POOL_ID = 'cards.simple_followup_p59.', 'constructed.cards'
RUSH = PREFIX + 'dragon_rush'
MURLOCS = PoolQuery(collectible=True, tribes_any=('murloc',), class_mode='current')
FEL = PoolQuery(kinds=(CardType.SPELL,), collectible=True, spell_schools=(SpellSchool.FEL,), class_mode='current')
MAPPINGS = ((UND_FORM, UND_TOKEN, 2), (ELE_FORM, ELE_TOKEN, 4), (INF_FORM, INF_TOKEN, 2))


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != ROOTS
            or tuple(x['record']['id'] for x in data['evidence_only']) != EVIDENCE
            or any(data[k] for k in ('dependencies', 'existing_dependencies', 'skipped'))
            or tuple((x['form'], x['token'], x['count']) for x in data['token_mapping_basis']) != MAPPINGS):
        raise TargetValidationError('P59 complete source/explicit internal token mapping changed')
    for row in data['cards'] + data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('P59 complete original source row changed')
    return data


def register_simple_followup_p59_cards(registry):
    for cid, query in ((MURLOC_MAP, MURLOCS), (FEL_MAP, FEL)):
        registry.register_behavior(PREFIX + cid, lambda c, query=query: (
            DiscoverForPlayFollowup(DiscoverFromPool(c.player_id, POOL_ID, query, source_id=c.source_id)),))
    registry.register_behavior(PREFIX + DECK_MAP, lambda c: (DiscoverForPlayFollowup(
        ChooseFromZone(c.player_id, c.player_id, Zone.DECK, operation='take', distinct='entity', source_id=c.source_id)),))
    registry.register_behavior(PREFIX + 'abyssian', lambda c: (AddPlayerEffect(c.player_id, RUSH, c.source_id),))
    for form, token, count in MAPPINGS:
        registry.register_behavior(PREFIX + form, lambda c, token=token, count=count: tuple(
            SummonByCard(c.player_id, (SummonEntryMaterial(token),), SummonCause.capture(c)) for _ in range(count)))
    for row in load_batch()['cards']:
        raw = row['record']; cid = raw['id']; kind = CardType(raw['type'].lower()); kwargs = {}
        if cid in (ABYSSIAN, UPGRADED): kwargs['battlecry'] = PREFIX + 'abyssian'
        if cid == ABYSSIAN:
            kwargs['hand_progress'] = HandProgressSpec('event', 1, UPGRADED,
                event='card_committed', condition_id=ENTRY_PREFIX + 'dragon')
        if cid in (MURLOC_MAP, FEL_MAP, DECK_MAP): kwargs['on_play'] = PREFIX + cid
        if cid == DECK_MAP: kwargs['spell_school'] = SpellSchool.SHADOW
        if cid in (UND_FORM, ELE_FORM, INF_FORM): kwargs['battlecry'] = PREFIX + cid
        if cid == UND_TOKEN: kwargs['keywords'] = (Keyword.TAUNT, Keyword.REBORN)
        if cid == ELE_TOKEN: kwargs['keywords'] = (Keyword.TAUNT,)
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'],
            attack=raw['attack'] if kind == CardType.MINION else 0,
            health=raw['health'] if kind == CardType.MINION else 0, metadata=metadata_from_record(raw), **kwargs)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_player_effect(PlayerEffectSpec(RUSH, ABYSSIAN,
        keyword_auras=(PlayerKeywordAuraSpec(Keyword.RUSH, ('dragon',)),)))
