"""Original Akama shuffle and a native persistent self Stealth source."""
from dataclasses import asdict
import hashlib, json
from pathlib import Path
from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.model import CardDefinition, CardType, Keyword, KeywordAuraSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.zones import AddToDeck
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/akama-prime-v1.json'
BATCH_HASH = 'f0cdddc5e57fd368006957b16f5ef575b2c4b393a726a01bbc89f465d3afb359'
AKAMA, PRIME = 'BT_713', 'BT_713t'
ROOTS, DEPENDENCIES, EVIDENCE = (AKAMA,), (PRIME,), ('MIS_701',)
EXISTING = ()
PREFIX = 'cards.akama_prime.'
PERMANENT = KeywordAuraSpec(Keyword.STEALTH, target='self')


def make_definition(raw):
    cid = raw['id']
    if (cid not in (*ROOTS, *DEPENDENCIES) or raw['type'] != 'MINION' or raw['tags'].get('STEALTH') != 1 or
            any(type(raw[k]) is not int for k in ('cost', 'attack', 'health'))):
        raise TargetValidationError('Akama lost its full original physical Stealth face')
    if cid == PRIME and '永久' not in raw['text']:
        raise TargetValidationError('Akama Prime requires its actual permanent Stealth text')
    return CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'], health=raw['health'],
        metadata=metadata_from_record(raw), keywords=(Keyword.STEALTH,),
        deathrattle=PREFIX+'shuffle' if cid == AKAMA else None, keyword_auras=(PERMANENT,) if cid == PRIME else ())


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != ROOTS or
            tuple(x['record']['id'] for x in d['dependencies']) != DEPENDENCIES or d['existing_dependencies'] or
            tuple(x['record']['id'] for x in d['evidence_only']) != EVIDENCE or len(d['official_observations']) != 6 or
            any(d[k] for k in ('complete_past_source_bound', 'new_standard_roots', 'membership_uses_executable_coverage', 'formal_pool_complete', 'cn_calibrated'))):
        raise TargetValidationError('Akama changed source roles or claimed a full past source')
    if any(canonical_digest(x['record']) != x['record_sha256'] for key in ('cards', 'dependencies', 'evidence_only') for x in d[key]):
        raise TargetValidationError('Akama changed an original full source row')
    parent, child = d['cards'][0]['record'], d['dependencies'][0]['record']
    if parent['tags']['COLLECTION_RELATED_CARD_DATABASE_ID'] != child['dbf_id'] or child['collectible']:
        raise TargetValidationError('Akama changed the exact noncollectible named Prime')
    path = ROOT/d['full_reference_document']
    if hashlib.sha256(path.read_bytes()).hexdigest() != d['full_reference_sha256']:
        raise TargetValidationError('Akama changed the complete original past reference')
    ref = json.loads(path.read_text(encoding='utf8')); rows = {x['record']['id']: x['record'] for x in ref['candidate_records']}
    if len(ref['candidate_ids']) != 732 or d['original_candidate_ids'] != ref['candidate_ids'] or parent != rows[AKAMA]:
        raise TargetValidationError('Akama cropped the complete original past source')
    return d


def register_akama_prime_cards(registry):
    d = load_batch(); prepared = []
    for row in d['cards']+d['dependencies']:
        card = make_definition(row['record'])
        if (card.id in registry.cards or canonical_digest(asdict(card)) != row['definition_sha256'] or
                canonical_digest(asdict(PoolCard.from_definition(card))) != row['pool_card_sha256']):
            raise TargetValidationError('Akama cannot replace another original face')
        registry._validate_card(card); prepared.append(card)
    registry.register_behavior(PREFIX+'shuffle', lambda c: shuffled(c, (AddToDeck(c.player_id, PRIME, source_id=c.source_id),)))
    for card in prepared:
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
