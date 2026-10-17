"""Complete past Paladin Mech bodies, printed upgrades and attack rewards."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.cross_zone import BuffMinionsInZones, MinionScope, RandomBuffStoredMinion
from hs_sim.engine.dredge import Dredge
from hs_sim.engine.effects import CopyMinion, Draw
from hs_sim.engine.model import (AppendageSpec, AuraSpec, BoardPresenceReference, CardDefinition,
    CardType, HandActionSpec, HandProgressSpec, Keyword, KeywordAuraSpec, TriggerSpec, Zone)
from hs_sim.engine.ordered_group_batches import SummonOrderedGroup
from hs_sim.engine.ordered_summon_groups import OrderedGroupMember, OrderedSummonGroupSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import AddToDeck
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import completed_attack, living_source
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p73-v1.json'
BATCH_HASH = 'e9d97332b5ca59a311387fbf87c45853744ce9f9e5b8d0dbc4d965dfd90adc26'
GRYPHON, CORRUPTED, TROUPE, LEVIATHAN, CLAW, MOON, SUNKEN, HELLBAT, NOBLE, MUSCLE, FORGED = (
    'DMF_064', 'DMF_064t', 'ETC_321', 'TSC_030', 'TSC_030t2', 'TSC_644', 'TSC_644t',
    'SC_412t', 'TTN_852', 'YOG_525', 'YOG_525t')
ANNOY = 'CORE_GVG_085'
COLLECTIBLE_ROOTS = ()
DEPENDENCIES = (GRYPHON, CORRUPTED, TROUPE, LEVIATHAN, CLAW, MOON, SUNKEN, HELLBAT, NOBLE, MUSCLE, FORGED)
ROOTS = DEPENDENCIES
PREFIX = 'cards.simple_followup_p73.'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or d['cards'] or d['collectible_candidate_roots'] or d['skipped']
            or tuple(x['record']['id'] for x in d['dependencies']) != DEPENDENCIES
            or tuple(x['record']['id'] for x in d['existing_dependencies']) != (ANNOY,)):
        raise TargetValidationError('P73 complete dependency-only source scope changed')
    if any(canonical_digest(x['record']) != x['record_sha256']
            for key in ('dependencies', 'existing_dependencies', 'evidence_only') for x in d[key]):
        raise TargetValidationError('P73 complete original source row changed')
    return d


def register_simple_followup_p73_cards(registry):
    d = load_batch()
    for cid, pin in d['existing_dependency_definition_pins'].items():
        if canonical_digest(asdict(registry.card(cid))) != pin['sha256']:
            raise TargetValidationError('P73 requires the unchanged complete original dependency: ' + cid)

    def troupe(c):
        position = deathrattle_position(c)
        members = tuple(OrderedGroupMember('annoy-' + str(i), SummonEntryMaterial(ANNOY),
            None if position is None else position+i) for i in range(3))
        return (SummonOrderedGroup(OrderedSummonGroupSpec(c.player_id, SummonCause.capture(c), members)),)

    def own_attack(c):
        row = completed_attack(c) if c.event is not None else None
        return (row is not None and living_source(c) and row.source_kind == CardType.MINION
            and row.declaration.source_id == c.source_id and row.declaration.player_id == c.player_id
            and (row.source_zone_epoch, row.source_entered_order) == (c.source.zone_epoch, c.source.entered_order))

    def leviathan(c):
        return (Dredge(c.player_id, source_id=c.source_id),) if own_attack(c) else ()

    def claw(c):
        return (Draw(c.player_id, source_id=c.source_id),) if own_attack(c) else ()

    def noble(c):
        return (RandomBuffStoredMinion(c.player_id, 1, 1, source_id=c.source_id),) if own_attack(c) else ()

    def sunken(c):
        return (CopyMinion(BoardPresenceReference.capture(c.state, c.source_id), c.player_id,
            cause=SummonCause.capture(c)),) if living_source(c) else ()

    bodies = dict(troupe=troupe, leviathan=leviathan, claw=claw, noble=noble, sunken=sunken,
        moon=lambda c: (AddToDeck(c.player_id, SUNKEN, 'bottom', c.source_id),),
        muscle=lambda c: (BuffMinionsInZones(c.player_id, 1, 1, MinionScope((Zone.HAND,)), c.source_id),),
        forged=lambda c: (BuffMinionsInZones(c.player_id, 2, 2, MinionScope((Zone.HAND,)), c.source_id),))
    for name, body in bodies.items(): registry.register_behavior(PREFIX + name, body)

    for item in d['dependencies']:
        raw = item['record']; cid = raw['id']; kw = {}
        if cid == GRYPHON:
            kw.update(keywords=(Keyword.DIVINE_SHIELD, Keyword.CORRUPT),
                hand_progress=HandProgressSpec('corrupt', upgrade_card_id=CORRUPTED))
        if cid == CORRUPTED: kw['keywords'] = (Keyword.CORRUPTED, Keyword.DIVINE_SHIELD, Keyword.TAUNT)
        if cid == TROUPE: kw.update(keywords=(Keyword.TAUNT, Keyword.DIVINE_SHIELD), deathrattle=PREFIX+'troupe')
        if cid in (LEVIATHAN, CLAW):
            kw.update(keywords=(Keyword.RUSH, Keyword.DIVINE_SHIELD),
                triggers=(TriggerSpec('attack_finished', PREFIX + ('leviathan' if cid == LEVIATHAN else 'claw')),))
        if cid == LEVIATHAN:
            kw.update(keywords=(Keyword.COLOSSAL, Keyword.RUSH, Keyword.DIVINE_SHIELD), colossal=(AppendageSpec(CLAW, 'right'),))
        if cid in (MOON, SUNKEN): kw.update(keywords=(Keyword.DIVINE_SHIELD,), battlecry=PREFIX+('moon' if cid == MOON else 'sunken'))
        if cid == HELLBAT:
            kw.update(auras=(AuraSpec(attack=2),), keyword_auras=(KeywordAuraSpec(Keyword.RUSH, target='friendly_minions'),))
        if cid == NOBLE:
            kw.update(keywords=(Keyword.MAGNETIC,), magnetic_tribes=('mech',), triggers=(TriggerSpec('attack_finished', PREFIX+'noble'),))
        if cid in (MUSCLE, FORGED): kw['battlecry'] = PREFIX + ('muscle' if cid == MUSCLE else 'forged')
        if cid == MUSCLE: kw['hand_actions'] = (HandActionSpec('forge', 'forge', 2, FORGED),)
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'],
            health=raw['health'], metadata=metadata_from_record(raw), **kw)
        registry.register_card(card)
        if cid not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
