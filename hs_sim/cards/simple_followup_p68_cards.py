"""Shared native improvements, actual stat gains and repeatable Murloc rewards."""
from dataclasses import asdict
from pathlib import Path
import json

from hs_sim.engine.effects import AddToHand, Damage, Draw, GainArmor, RefreshMana
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_followups import InvokeHealthResult
from hs_sim.engine.health_loss import GainMaxHealth
from hs_sim.engine.model import (AppendageSpec, CardDefinition, CardType, DamageKind,
    HealthFlow, Keyword, PlayerEffectSpec, QuestSpec, QuestStageSpec,
    TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.quests import AdvanceQuest
from hs_sim.engine.sacrifice import BuffCapturedMinion, DestroyCapturedMinion, MinionReference
from hs_sim.engine.spell_history import CastFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.engine.zones import FillHandWithCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import completed_attack
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p68-v1.json'
BATCH_HASH = '55043080cfadc6d4ded20de630d55075880fcb8926de948a600628e01936f868'
SOUL, SCYTHE, VOIDSCALE, BLAST, AMIRDRASSIL, WICKERFANG, QUEST = (
    'JAIL_732', 'JAIL_730', 'JAIL_733', 'JAIL_891', 'FIR_907', 'CATA_139', 'TLC_426')
CAVE, OSK_HEALTH, OSK_TENDRILS, TENDRIL = 'TLC_426t', 'TLC_452t1', 'TLC_452t33', 'YOG_514'
COLLECTIBLE_ROOTS = (SOUL, SCYTHE, VOIDSCALE, BLAST, AMIRDRASSIL, WICKERFANG, QUEST)
DEPENDENCIES = (CAVE, OSK_HEALTH, OSK_TENDRILS, TENDRIL)
ROOTS = COLLECTIBLE_ROOTS + DEPENDENCIES
LEGS = ('CATA_139t', 'CATA_139t2', 'CATA_139t3', 'CATA_139t4')
PREFIX, POOL_ID = 'cards.simple_followup_p68.', 'constructed.cards'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != COLLECTIBLE_ROOTS
            or tuple(x['record']['id'] for x in d['dependencies']) != DEPENDENCIES
            or tuple(x['record']['id'] for x in d['existing_dependencies']) != LEGS or d['skipped']):
        raise TargetValidationError('P68 complete original scope changed')
    if any(canonical_digest(x['record']) != x['record_sha256'] for key in
            ('cards', 'dependencies', 'existing_dependencies', 'evidence_only') for x in d[key]):
        raise TargetValidationError('P68 complete original raw record changed')
    return d


def register_simple_followup_p68_cards(registry):
    d = load_batch()
    for cid, pin in d['existing_dependency_definition_pins'].items():
        if canonical_digest(asdict(registry.card(cid))) != pin['sha256']:
            raise TargetValidationError('P68 requires its complete original native leg: ' + cid)

    def level(c, family):
        n = 1 + sum(e.spec_id == PREFIX + family for e in c.state.players[c.player_id].player_effects)
        return min(10, n) if family in ('soul_progress', 'tendril_progress') else n

    def improve(c, family):
        return AddPlayerEffect(c.player_id, PREFIX + family, c.source_id)

    def soul(c):
        n = level(c, 'soul_progress')
        return GenerateFromPool(c.player_id, POOL_ID, PoolQuery(kinds=(CardType.MINION,), collectible=True,
            min_cost=n, max_cost=n, tribes_any=('demon',)), destination='board', source_id=c.source_id,
            cause=SummonCause.capture(c)), improve(c, 'soul_progress')

    def tendril(c):
        n = level(c, 'tendril_progress')
        return CastFromPool(c.player_id, POOL_ID, PoolQuery(kinds=(CardType.SPELL,), collectible=True,
            min_cost=n, max_cost=n), source_id=c.source_id), improve(c, 'tendril_progress')

    def location(c):
        n = level(c, 'location_progress')
        return (GenerateFromPool(c.player_id, POOL_ID, PoolQuery(kinds=(CardType.MINION,), collectible=True,
            min_cost=n, max_cost=n), destination='board', source_id=c.source_id, cause=SummonCause.capture(c)),
            GainArmor(c.player_id, n), Draw(c.player_id, n, c.source_id), RefreshMana(c.player_id, n),
            improve(c, 'location_progress'))

    def scythe(c):
        row = completed_attack(c)
        return (AddToHand(c.player_id, SOUL, c.source_id),) if row is not None and (
            row.source_kind == CardType.HERO and row.declaration.player_id == c.player_id) else ()

    def blast_result(c):
        if c.health_result is None:
            raise ResolutionError('Void Blast lost its original complete health result')
        return (InvokeHealthResult(PREFIX + 'blast_death', c.event),)

    def blast_death(c):
        result = c.health_result
        if result is None:
            raise ResolutionError('Void Blast lost its original deferred health result')
        died = result.flow == HealthFlow.DAMAGE.value and result.target_id == result.original_target_id and any(
            row.entity_id == result.original_target_id and row.cause.kind in ('damage', 'poison')
            and row.cause.result == result.payload() for row in c.state.death_history)
        return (AddToHand(c.player_id, SOUL, c.source_id),) if died else ()

    def wickerfang(c):
        leg = c.state.entities.get(c.event.target_id)
        if leg is None or leg.card_id not in LEGS or leg.controller != c.player_id:
            return ()
        data = dict(c.event.data)
        if 'attack_delta' in data and 'health_delta' in data:
            attack, health = max(0, data['attack_delta']), max(0, data['health_delta'])
        elif all(k in data for k in ('attack', 'old_attack', 'max_health', 'old_max_health')):
            attack, health = max(0, data['attack'] - data['old_attack']), max(0, data['max_health'] - data['old_max_health'])
        else:
            raise ResolutionError('Wickerfang requires the complete native stat-change contribution')
        return (BuffCapturedMinion(MinionReference.capture(c.source), attack, health, c.source_id),) if attack or health else ()

    def summoned_murloc(c):
        e = c.state.entities.get(c.event.target_id)
        return e if c.event.player_id == c.player_id and e is not None and e.kind == CardType.MINION and (
            e.zone == Zone.BOARD and e.controller == c.player_id and e.active and not e.doomed
            and e.health > 0 and has_any_tribe(registry, e, ('murloc',), basis='current')) else None

    def quest(c):
        if summoned_murloc(c) is None: return ()
        progress = c.source.quest_progress
        return (AdvanceQuest(c.source_id, progress.id, progress.stage),)

    def cave(c):
        e = summoned_murloc(c)
        return (BuffCapturedMinion(MinionReference.capture(e), 1, 1, c.source_id),) if e is not None else ()

    def osk_health(c):
        if c.target_id is None: return ()
        victim = c.state.entities[c.target_id]
        return (DestroyCapturedMinion(MinionReference.capture(victim), c.source_id,
            (BuffCapturedMinion(MinionReference.capture(c.source), health=victim.health, source_id=c.source_id),
                GainMaxHealth(c.player_id, victim.health, c.source_id))),)

    bodies = dict(soul=soul, tendril=tendril, location=location, scythe=scythe,
        get_soul=lambda c:(AddToHand(c.player_id, SOUL, c.source_id),),
        blast=lambda c:(Damage(c.target_id, 3, c.source_id, DamageKind.SPELL, PREFIX + 'blast_result'),),
        blast_result=blast_result, blast_death=blast_death, wickerfang=wickerfang,
        quest=quest, cave=cave, install_cave=lambda c:(AddPlayerEffect(c.player_id, PREFIX + 'cave', c.source_id),),
        osk_health=osk_health, osk_tendrils=lambda c:(FillHandWithCard(c.player_id, TENDRIL, c.source_id),))
    for name, body in bodies.items(): registry.register_behavior(PREFIX + name, body)
    for name, cid in (('soul_progress', SOUL), ('tendril_progress', TENDRIL), ('location_progress', AMIRDRASSIL)):
        registry.register_player_effect(PlayerEffectSpec(PREFIX + name, cid))
    registry.register_player_effect(PlayerEffectSpec(PREFIX + 'cave', CAVE,
        triggers=(TriggerSpec('minion_summoned', PREFIX + 'cave'),)))
    for item in (*d['cards'], *d['dependencies']):
        raw = item['record']; cid = raw['id']; kind = CardType(raw['type'].lower()); kw = {}
        if cid in (SOUL, BLAST, CAVE): kw['on_play'] = PREFIX + {SOUL:'soul', BLAST:'blast', CAVE:'install_cave'}[cid]
        if cid == BLAST: kw['targeting'] = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
        if cid == SCYTHE: kw['triggers'] = (TriggerSpec('attack_finished', PREFIX + 'scythe'),)
        if cid == VOIDSCALE: kw.update(keywords=(Keyword.TAUNT,), deathrattle=PREFIX + 'get_soul')
        if cid == AMIRDRASSIL: kw['on_use'] = PREFIX + 'location'
        if cid == WICKERFANG:
            kw.update(keywords=(Keyword.COLOSSAL,), colossal=tuple(AppendageSpec(i, 'left' if n < 2 else 'right')
                for n, i in enumerate(LEGS)), triggers=(TriggerSpec('stats_changed', PREFIX + 'wickerfang'),))
        if cid == QUEST:
            kw.update(keywords=(Keyword.QUEST,), quest=QuestSpec('repeatable_quest', (
                QuestStageSpec(QUEST, 6, ('minion_summoned',), PREFIX + 'quest', PREFIX + 'install_cave'),)))
        if cid in (OSK_HEALTH, OSK_TENDRILS, TENDRIL): kw['battlecry'] = PREFIX + {
            OSK_HEALTH:'osk_health', OSK_TENDRILS:'osk_tendrils', TENDRIL:'tendril'}[cid]
        if cid == OSK_HEALTH: kw['targeting'] = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='enemy', mode=TargetMode.IF_AVAILABLE)
        numbers = d['numeric_normalizations'].get(cid, {})
        card = CardDefinition(cid, raw['name'], kind,
            cost=raw['cost'] if raw['cost'] is not None else numbers['cost'],
            attack=(raw['attack'] if raw['attack'] is not None else numbers['attack']) if kind in (CardType.MINION, CardType.WEAPON) else 0,
            health=raw['health'] if kind == CardType.MINION else 0,
            durability=raw['health'] if kind in (CardType.WEAPON, CardType.LOCATION) else 0,
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')), metadata=metadata_from_record(raw), **kw)
        registry.register_card(card)
        # Candidate metadata is assembled later by the central/catalog caller.
        # Add only truly absent rows, preserving every existing complete PoolCard.
        if cid not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
