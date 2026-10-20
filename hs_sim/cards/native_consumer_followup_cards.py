"""Five real consumers of original plays, draws and successful physical entries."""
import json
from pathlib import Path

from hs_sim.engine.board_presence import resolve_board_presence
from hs_sim.engine.copy_followups import original_copy_reference
from hs_sim.engine.copy_materials import CopyEntryMaterial
from hs_sim.engine.effects import AddCostModifier, ForceAttack, Freeze
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (BoardPresenceReference, CardClass, CardDefinition, CardType,
    CostSpec, EndTurnSpec, TargetSpec, TriggerSpec)
from hs_sim.engine.named_summon_followups import original_named_reference
from hs_sim.engine.physical_draw_groups import DrawGroupReward, DrawGroupSlot, DrawPhysicalGroup
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import minions

GENERAL, CARRIER, JUDGMENT, SUMMONER, OMEN = 'BE_008', 'BE_150', 'BE_154', 'BE_196', 'BE_201'
ROOTS = COLLECTIBLE_ROOTS = (GENERAL, CARRIER, JUDGMENT, SUMMONER, OMEN)
DEPENDENCIES = ()
PREFIX = 'cards.native_consumer_followups.'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/native-consumer-followups-v1.json'
BATCH_HASH = '0bf132f9c2694cc354b96c049d65acea6384e7c4437130639ae915c9b19318b2'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(r['record']['id'] for r in data['cards']) != ROOTS or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(r['record']) != r['record_sha256'] for r in data['cards'])):
        raise TargetValidationError('Native followup consumers require five complete source faces')
    return data


def register_native_consumer_followup_cards(registry):
    def general(c):
        row = play_record(c.state, dict(c.event.data)['play_id'])
        if not row.completed or (row.source_id, row.player_id) != (c.event.source_id, c.event.player_id):
            raise ResolutionError('General requires its original completed play')
        if row.player_id != c.player_id or not living_source(c): return ()
        classes = row.played_face.metadata.classes
        if classes is None: raise ResolutionError('Neutral play requires known original printed classes')
        if classes != (CardClass.NEUTRAL,): return ()
        return (AddCostModifier(c.player_id, CostSpec(delta=-1, card_types=(CardType.SPELL,)),
            uses_remaining=1, source_id=c.source_id, expires_turn=c.state.turn),)

    def summoner(c):
        candidates = minions(c, registry, 3-c.player_id)
        if not candidates: return ()
        materials = tuple(CopyEntryMaterial.capture(c.state, c.state.entities[eid], 'board_copy', 'current',
            registry=registry, player_id=c.player_id, on_summon=PREFIX+'attack_original') for eid in candidates)
        return (SummonByCard(c.player_id, materials, SummonCause.capture(c), selection='random'),)

    def attack_original(c):
        original = original_copy_reference(c)
        target = BoardPresenceReference(original.entity_id, original.entered_order)
        if resolve_board_presence(c.state, target) is None: return ()
        attacker = c.state.entities[c.target_id]
        return (ForceAttack(BoardPresenceReference(attacker.id, attacker.entered_order), target,
            combat_relation='any_minions'),)

    bodies = {
        GENERAL: general,
        CARRIER: lambda c: (DiscoverFromPool(c.player_id, 'constructed.cards',
            PoolQuery(kinds=(CardType.SPELL,), collectible=True, class_mode='current'),
            source_id=c.source_id, destination='deck', position='top', cost=CostSpec(delta=-2)),),
        JUDGMENT: lambda c: (DrawPhysicalGroup(c.player_id, c.source_id, (DrawGroupSlot(),)*3,
            DrawGroupReward('set_drawn_minion_stats', 2)),),
        SUMMONER: summoner,
        'attack_original': attack_original,
        OMEN: lambda c: (Freeze(c.target_id, c.source_id), SummonFromPool(c.player_id, 'constructed.minions',
            PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=5, max_cost=5),
            source_id=c.source_id, cause=SummonCause.capture(c), on_summon=PREFIX+'freeze_summoned')),
        'freeze_summoned': lambda c: (Freeze(original_named_reference(c).entity_id, c.source_id),),
    }
    for cid, body in bodies.items(): registry.register_behavior(PREFIX+cid, body)
    for row in load_batch()['cards']:
        raw = row['record']; cid = raw['id']; kind = CardType(raw['type'].lower())
        fields = dict(attack=0 if cid == SUMMONER else raw['attack'], health=raw['health']) if kind == CardType.MINION else dict(spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')))
        if cid == GENERAL: fields['triggers'] = (TriggerSpec('card_played', PREFIX+cid),)
        elif cid == CARRIER: fields['battlecry'] = PREFIX+cid
        elif cid == SUMMONER: fields['triggers'] = (TriggerSpec('turn_ended', PREFIX+cid, EndTurnSpec()),)
        else: fields['on_play'] = PREFIX+cid
        if cid == OMEN: fields['targeting'] = TargetSpec(relation='enemy')
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'], metadata=metadata_from_record(raw), **fields)
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
