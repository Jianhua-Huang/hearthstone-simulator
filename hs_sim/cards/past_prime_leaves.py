"""Four real Prime roots and all four named generated bodies; ordinary public executors."""
from dataclasses import asdict
import hashlib, json
from pathlib import Path

from hs_sim.engine.character_attacks import completed_attack
from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.effects import CopyMinion, GainArmor
from hs_sim.engine.model import BoardPresenceReference, CardDefinition, CardType, CostAuraSpec, CostSpec, DamageKind, Keyword, TriggerSpec
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.spell_sequences import DrawMatchingWithCostReduction
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import DeathQuery, Resurrect
from hs_sim.engine.zones import AddToDeck
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-prime-leaves-v1.json'
BATCH_HASH='d4622d34b03b9d377dcad358132ffeda38d98f185ce208248455ed5d0f21de75'
VASHJ, KARGATH, ZIXOR, KANRETHAD = ROOTS = ('BT_109', 'BT_123', 'BT_210', 'BT_309')
DEPENDENCIES = tuple(cid+'t' for cid in ROOTS)
VASHJ_PRIME, KARGATH_PRIME, ZIXOR_PRIME, KANRETHAD_PRIME = DEPENDENCIES
EXISTING = ()
EVIDENCE = ('BT_109te', 'BT_309e', 'MIS_701')
PREFIX = 'cards.past_prime_leaves.'
SPELLS = PoolQuery(kinds=(CardType.SPELL,))
DEMONS = DeathQuery(cards=PoolQuery(tribes_any=('demon',)))
DEMON_DISCOUNT = CostAuraSpec(CostSpec(delta=-1, card_types=(CardType.MINION,)), tribes_any=('demon',))


def make_definition(raw):
    cid = raw['id']
    if (cid not in (*ROOTS, *DEPENDENCIES) or raw['type'] != 'MINION' or
            any(type(raw[k]) is not int for k in ('cost', 'attack', 'health'))):
        raise TargetValidationError('Prime family lost a complete original physical minion face')
    kwargs = dict(keywords=(Keyword.RUSH,) if raw['tags'].get('RUSH') == 1 else (),
        spell_damage=raw['tags'].get('SPELLPOWER', 0))
    if cid in ROOTS: kwargs['deathrattle'] = PREFIX+'shuffle.'+cid
    if cid == KANRETHAD: kwargs['cost_auras'] = (DEMON_DISCOUNT,)
    if cid == KARGATH_PRIME: kwargs['triggers'] = (TriggerSpec('attack_finished', PREFIX+'armor'),)
    if cid in (VASHJ_PRIME, ZIXOR_PRIME, KANRETHAD_PRIME):
        kwargs['battlecry'] = PREFIX+{VASHJ_PRIME: 'draw', ZIXOR_PRIME: 'copies', KANRETHAD_PRIME: 'demons'}[cid]
    return CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'],
        health=raw['health'], metadata=metadata_from_record(raw), **kwargs)


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != ROOTS or
            tuple(x['record']['id'] for x in d['dependencies']) != DEPENDENCIES or d['existing_dependencies'] or
            tuple(x['record']['id'] for x in d['evidence_only']) != EVIDENCE or
            len(d['official_observations']) != 18 or any(d[k] for k in ('complete_past_source_bound',
                'new_standard_roots', 'membership_uses_executable_coverage', 'formal_pool_complete', 'cn_calibrated'))):
        raise TargetValidationError('Prime families changed complete source roles or claimed a full past pool')
    records = d['cards']+d['dependencies']+d['evidence_only']
    if any(canonical_digest(x['record']) != x['record_sha256'] for x in records):
        raise TargetValidationError('Prime family changed an original complete source row')
    by_id = {x['record']['id']: x['record'] for x in records}
    if any(by_id[parent]['tags']['COLLECTION_RELATED_CARD_DATABASE_ID'] != by_id[child]['dbf_id']
            for parent, child in zip(ROOTS, DEPENDENCIES)):
        raise TargetValidationError('Prime family substituted its actual client-linked named generated body')
    if any(by_id[cid]['collectible'] is not False for cid in DEPENDENCIES):
        raise TargetValidationError('Generated Prime body cannot acquire constructed membership')
    reference = ROOT/d['full_reference_document']
    if hashlib.sha256(reference.read_bytes()).hexdigest() != d['full_reference_sha256']:
        raise TargetValidationError('Prime families changed the full original past reference')
    ref = json.loads(reference.read_text(encoding='utf8')); rows = {x['record']['id']: x['record'] for x in ref['candidate_records']}
    if (len(ref['candidate_ids']) != 732 or d['original_candidate_ids'] != ref['candidate_ids'] or
            any(x['record'] != rows[x['record']['id']] for x in d['cards'])):
        raise TargetValidationError('Prime families cropped the complete original past source')
    return d


def register_past_prime_leaves(registry):
    d = load_batch(); prepared = []
    for row in d['cards']+d['dependencies']:
        card = make_definition(row['record'])
        if (card.id in registry.cards or canonical_digest(asdict(card)) != row['definition_sha256'] or
                canonical_digest(asdict(PoolCard.from_definition(card))) != row['pool_card_sha256']):
            raise TargetValidationError('Prime family cannot replace another registered original face')
        registry._validate_card(card); prepared.append(card)
    for parent, child in zip(ROOTS, DEPENDENCIES):
        def death(c, child=child):
            return shuffled(c, (AddToDeck(c.player_id, child, source_id=c.source_id),))
        registry.register_behavior(PREFIX+'shuffle.'+parent, death)
    def armor(c):
        row = completed_attack(c)
        if (row is None or row.source_kind != CardType.MINION or row.declaration.source_id != c.source_id or
                not living_source(c) or (c.source.card_id, c.source.zone_epoch, c.source.entered_order) !=
                (row.combat.source_card_id, row.combat.source_zone_epoch, row.combat.source_entered_order)):
            return ()
        target = c.state.entities[row.delivery.target_id]
        causes = ((target.death_cause,) if target.death_cause is not None else ())+tuple(
            death.cause for death in c.state.death_history if death.entity_id == row.delivery.target_id)
        for cause in causes:
            result = cause.health_result
            if (cause.kind in ('damage', 'poison') and result is not None and result.target_kind == CardType.MINION.value and
                    (cause.source_id, cause.source_card_id, cause.source_zone_epoch, cause.source_entered_order) ==
                    (c.source_id, row.combat.source_card_id, row.combat.source_zone_epoch, row.combat.source_entered_order) and
                    result.damage_kind == DamageKind.COMBAT.value and result.original_target_id == row.delivery.target_id and
                    row.combat.event_cursor < result.batch_id <= row.terminal.event_cursor):
                return (GainArmor(c.player_id, 10),)
        return ()
    def copies(c):
        if not living_source(c): return ()
        source = BoardPresenceReference.capture(c.state, c.source_id); cause = SummonCause.capture(c)
        return tuple(CopyMinion(source, c.player_id, cause=cause) for _ in range(3))
    registry.register_behavior(PREFIX+'draw', lambda c: tuple(
        DrawMatchingWithCostReduction(c.player_id, 3, c.source_id, SPELLS) for _ in range(3)))
    registry.register_behavior(PREFIX+'armor', armor)
    registry.register_behavior(PREFIX+'copies', copies)
    registry.register_behavior(PREFIX+'demons', lambda c: (Resurrect(c.player_id, 3, DEMONS,
        source_id=c.source_id, cause=SummonCause.capture(c)),))
    for card in prepared:
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
