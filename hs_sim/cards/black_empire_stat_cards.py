"""Real Black Empire stat, cost and health-result consumers of native effects."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.cross_zone import BuffMinionsInZones, MinionScope, minion_references
from hs_sim.engine.effects import (Buff, ChoiceOption, Damage, DamageBatch, Draw,
    GrantKeyword, InvokeBehavior, RandomDamage, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard, SetStoredMinionStats
from hs_sim.engine.model import (BoardMinionCostSpec, CardDefinition, CardType,
    CostSpec, DamageKind, Keyword, SpellSchool, TargetMode, TargetSpec, Zone)
from hs_sim.engine.pools import PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference, DrawMatching, ModifyStoredCost
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import characters, minions

DANCE, SHAPE, RAIN, BRAWLER, UNKNOWABLE, ZAKAJZ, SLAMMER, FIRE, BEAR, FREYA, FOX, IMP, TROGG = (
    'BE_071', 'BE_208', 'BE_258', 'BE_560', 'BE_725', 'BE_728', 'BE_733',
    'BE_854', 'BE_855', 'BE_856', 'BE_859', 'BE_993', 'BE_994')
ROOTS = COLLECTIBLE_ROOTS = (DANCE, SHAPE, RAIN, BRAWLER, UNKNOWABLE, ZAKAJZ,
    SLAMMER, FIRE, BEAR, FREYA, FOX, IMP, TROGG)
DEPENDENCIES = ()
PREFIX = 'cards.black_empire_stats.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/black-empire-stats-v1.json'
BATCH_HASH = 'a471cdf9c356f771a66f8924415f1b31f56a31ab89594c2f083bcec5e3dfa33e'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(r['record']['id'] for r in data['cards']) != ROOTS or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(r['record']) != r['record_sha256'] for r in data['cards']) or
            data['reviewed_zero_cost'] != {DANCE: 0}):
        raise TargetValidationError('Black Empire stat cards require thirteen complete reviewed originals')
    raw = next(r['record'] for r in data['cards'] if r['record']['id'] == DANCE)
    faces = [o['face'] for o in data['official_observations'] if o['card_id'] == DANCE]
    if raw['cost'] is not None or 'COST' in raw['tags'] or len(faces) != 2 or any(f['manaCost'] != 0 for f in faces):
        raise TargetValidationError('Shadow Dance zero Cost requires both complete primary zero faces')
    return data


def register_black_empire_stat_cards(registry):
    def invoke(c, name):
        return InvokeBehavior(PREFIX+name, c.source_id, c.player_id, c.target_id,
            None if c.play is None else c.play.id)

    def dance(c):
        return (DamageBatch(tuple(Damage(eid, 1, c.source_id, DamageKind.SPELL)
            for eid in characters(c, registry, 3-c.player_id)
            if c.state.entities[eid].health == c.state.entities[eid].max_health)),)

    def unknowable(c):
        refs = minion_references(c.state, registry, c.player_id, MinionScope((Zone.HAND,)), c.source_id)
        return tuple(SetStoredMinionStats(ref, 6, 6, c.source_id) for ref in refs
            if Keyword.COMBO in c.state.entities[ref.entity_id].keywords)

    def zakajz(c):
        cards = (c.state.entities[i] for zone in (Zone.HAND, Zone.DECK)
            for i in getattr(c.state.players[c.player_id], zone.value))
        return tuple(ModifyStoredCost(CardReference.capture(e),
            CostSpec(delta=-1 if e.kind == CardType.MINION else 1), c.source_id)
            for e in cards if e.kind in (CardType.MINION, CardType.SPELL))

    def freya(c):
        refs = minion_references(c.state, registry, c.player_id,
            MinionScope((Zone.HAND, Zone.DECK), PoolQuery(tribes_any=('beast',)), tribe_basis='current'), c.source_id)
        return tuple(BuffStoredCard(ref, c.state.entities[ref.entity_id].attack,
            c.state.entities[ref.entity_id].health, c.source_id) for ref in refs)

    def fox(c):
        amount = c.death.attack if c.death is not None and c.death.entity_id==c.source_id else c.source.attack
        return (Draw(c.player_id, amount, c.source_id),) if amount else ()

    def imp(c):
        cards = (c.state.entities[i] for i in c.state.players[c.player_id].hand)
        refs = tuple(CardReference.capture(e) for e in cards
            if e.kind == CardType.SPELL and registry.card(e.card_id).spell_school == SpellSchool.SHADOW)
        options = tuple(ChoiceOption(json.dumps(asdict(ref), sort_keys=True),
            'Original held Shadow spell', card_id=ref.card_id, entity_id=ref.entity_id) for ref in refs)
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
            sample_size=1, on_select=PREFIX+'imp_selected'),) if options else ()

    def imp_selected(c):
        if c.choice is None or c.choice.selected_ids or len(c.choice.choice.options) != 1:
            raise ResolutionError('Winged Imp lost its original sampled physical Shadow spell')
        material = json.loads(c.choice.choice.options[0].id)
        material['zone'] = Zone(material['zone'])
        return (ModifyStoredCost(CardReference(**material), CostSpec(delta=-2), c.source_id),)

    def trogg_result(c):
        result = c.health_result
        if result is None:
            raise ResolutionError('Stone Trogg requires its original health-result continuation')
        target = c.state.entities[result.original_target_id]
        if target.kind != CardType.MINION or target.zone != Zone.BOARD or not target.active or target.health <= 0 or target.doomed:
            return ()
        return (Buff(c.source_id, health=6, source_id=c.source_id),
            GrantKeyword(c.source_id, Keyword.TAUNT, c.source_id))

    bodies = dict(dance=dance,
        shape=lambda c: (DrawMatching(c.player_id, PoolQuery(kinds=(CardType.MINION,)), 'skip',
            selection='random', source_id=c.source_id), BuffMinionsInZones(c.player_id, 2, 2,
                MinionScope((Zone.HAND,), PoolQuery(tribes_any=('beast',)), tribe_basis='current'), c.source_id)),
        rain=lambda c: tuple(invoke(c, 'rain_packet') for _ in range(5)),
        rain_packet=lambda c: (RandomDamage(minions(c, registry, 3-c.player_id), 2, c.source_id, DamageKind.SPELL),),
        brawler=lambda c: (Buff(c.source_id, 4, 4, c.source_id),)
            if c.state.entities[c.state.players[c.player_id].hero_id].armor >= 10 else (),
        unknowable=unknowable, zakajz=zakajz,
        fire=lambda c: (Damage(c.target_id, 3, c.source_id, DamageKind.SPELL),
            SummonFromPool(c.player_id, 'constructed.minions',
                PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=3, max_cost=3),
                source_id=c.source_id, cause=SummonCause.capture(c))),
        bear=lambda c: (Buff(c.state.players[c.player_id].hero_id, attack=c.source.attack,
            source_id=c.source_id, expires_turn=c.state.turn),),
        freya=freya, fox=fox, imp=imp, imp_selected=imp_selected,
        trogg=lambda c: (Damage(c.target_id, 6, c.source_id, DamageKind.MINION_ABILITY, PREFIX+'trogg_result'),)
            if c.target_id is not None else (), trogg_result=trogg_result)
    for name, body in bodies.items(): registry.register_behavior(PREFIX+name, body)
    keyword_map = {BRAWLER: (Keyword.CHARGE,), SLAMMER: (Keyword.RUSH, Keyword.WINDFURY,), FOX: (Keyword.TAUNT,)}
    battlecries = {BRAWLER: 'brawler', UNKNOWABLE: 'unknowable', ZAKAJZ: 'zakajz',
        BEAR: 'bear', FREYA: 'freya', TROGG: 'trogg'}
    spells = {DANCE: 'dance', SHAPE: 'shape', RAIN: 'rain', FIRE: 'fire'}
    for row in load_batch()['cards']:
        raw = row['record']; cid = raw['id']; kind = CardType(raw['type'].lower()); fields = {}
        if kind == CardType.MINION:
            fields.update(attack=raw['attack'], health=raw['health'])
        else: fields.update(spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')), on_play=PREFIX+spells[cid])
        if cid in battlecries: fields['battlecry'] = PREFIX+battlecries[cid]
        if cid == SLAMMER: fields['board_minion_cost'] = BoardMinionCostSpec('enemy')
        if cid in (FOX, IMP): fields['deathrattle'] = PREFIX+('fox' if cid == FOX else 'imp')
        if cid == TROGG:
            fields['targeting'] = TargetSpec(TargetMode.IF_AVAILABLE, zones=(Zone.BOARD,), kinds=(CardType.MINION,))
        if cid == FIRE: fields['targeting'] = TargetSpec()
        card = CardDefinition(cid, raw['name'], kind, cost=0 if cid == DANCE else raw['cost'],
            keywords=keyword_map.get(cid, ()), metadata=metadata_from_record(raw), **fields)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
