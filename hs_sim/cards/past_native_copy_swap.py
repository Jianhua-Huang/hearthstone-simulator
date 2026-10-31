"""Five real original deck, held-play, spell-memory and multi-zone copy consumers."""
from dataclasses import asdict
import hashlib, json
from pathlib import Path

from hs_sim.engine.model import (CardDefinition, CardType, HandProgressSpec, NativeDeathrattleSpec,
    TargetMode, TargetSpec, Zone)
from hs_sim.engine.native_copy_consumers import (TransformIntoDeckDemon, CopyMinionToThreeZones,
    TransformHeldPlayedMinion, SwapDeathrattleWithDeck)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_deathrattle_memory_cards import memory

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-native-copy-swap-v1.json'
BATCH_HASH = 'cc8b59fc47b263838ba143995d0ad245c4e746b0ed27e7682d042ed20407f285'
CARIA, MORRIGAN, FLOOP, ZEREK, SATHROVARR = ROOTS = ('AV_267', 'BOT_433', 'BOT_434', 'BOT_258', 'DRG_402')
DEPENDENCIES = EXISTING = ()
EVIDENCE = ('MIS_701',)
PREFIX = 'cards.past_native_copy_swap.'


def make_definition(raw):
    cid = raw['id']
    if cid not in ROOTS or raw['type'] != 'MINION' or any(type(raw[k]) is not int for k in ('cost','attack','health')):
        raise TargetValidationError('Native copy/swap requires its complete original minion face')
    fields = {}
    if cid in (CARIA, SATHROVARR): fields['battlecry'] = PREFIX+cid
    if cid == SATHROVARR:
        fields['targeting'] = TargetSpec(TargetMode.IF_AVAILABLE, zones=(Zone.BOARD,),
            kinds=(CardType.MINION,), relation='friendly')
    if cid in (MORRIGAN, ZEREK): fields['deathrattle'] = PREFIX+cid
    if cid == ZEREK: fields['native_deathrattle'] = NativeDeathrattleSpec('targeted_spells')
    if cid == FLOOP:
        fields['defining_hand_source'] = HandProgressSpec('event', repeat=True, event='card_played', on_complete=PREFIX+cid)
    return CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'],
        health=raw['health'], metadata=metadata_from_record(raw), **fields)


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != ROOTS or
            any(d[k] for k in ('dependencies','existing_dependencies','complete_past_source_bound','new_standard_roots',
                'membership_uses_executable_coverage','formal_pool_complete','cn_calibrated')) or
            tuple(x['record']['id'] for x in d['evidence_only']) != EVIDENCE or len(d['official_observations']) != 12):
        raise TargetValidationError('Native copy/swap changed its complete source roles or claimed full support')
    for row in d['cards']+d['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete original native copy/swap row')
    p = ROOT/d['full_reference_document']
    if hashlib.sha256(p.read_bytes()).hexdigest() != d['full_reference_sha256']:
        raise TargetValidationError('Changed complete past source')
    ref = json.loads(p.read_text(encoding='utf8'))
    rows = {x['record']['id']:x['record'] for x in ref['candidate_records']}
    if (len(ref['candidate_ids']) != 732 or ref['candidate_ids'] != d['original_candidate_ids'] or
            any(row['record'] != rows[row['record']['id']] for row in d['cards'])):
        raise TargetValidationError('Cropped original past source')
    return d


def register_past_native_copy_swap(registry):
    d = load_batch(); prepared = []
    for row in d['cards']:
        card = make_definition(row['record'])
        if (card.id in registry.cards or canonical_digest(asdict(card)) != row['definition_sha256'] or
                canonical_digest(asdict(PoolCard.from_definition(card))) != row['pool_card_sha256']):
            raise TargetValidationError('Native copy/swap changed or replaced another original face')
        registry._validate_card(card); prepared.append(card)
    def caria(c):
        return (TransformIntoDeckDemon(MinionReference.capture(c.source), SummonCause.capture(c)),)
    def morrigan(c):
        if c.deathrattle is None: raise ValueError('Morrigan requires her actual original Deathrattle')
        return (SwapDeathrattleWithDeck(c.deathrattle.id, SummonCause.capture(c)),)
    def floop(c):
        if c.play is None or c.trigger is None: raise ValueError('Floop requires its original accepted held-play witness')
        return (TransformHeldPlayedMinion(CardReference.capture(c.source), c.trigger.id, c.play.id),)
    def zerek(c):
        if not memory(c, 'targeted_spells').targeted_spells: return ()
        # A new printed body has fresh native memory. Never forge a natural DeathRecord.
        return (SummonByCard(c.player_id, (SummonEntryMaterial(ZEREK),), SummonCause.capture(c)),)
    def sathrovarr(c):
        if c.target_id is None: return ()
        return (CopyMinionToThreeZones(MinionReference.capture(c.state.entities[c.target_id]), SummonCause.capture(c)),)
    for cid, body in ((CARIA,caria),(MORRIGAN,morrigan),(FLOOP,floop),(ZEREK,zerek),(SATHROVARR,sathrovarr)):
        registry.register_behavior(PREFIX+cid, body)
    for card in prepared:
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
