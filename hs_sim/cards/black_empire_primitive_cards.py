"""Announced Black Empire candidates composed from existing native mechanisms."""
import json
from pathlib import Path

from hs_sim.engine.cross_zone import BuffMinionsInZones, MinionScope
from hs_sim.engine.effects import Buff, Draw, Freeze, GainArmor, GrantKeyword, Heal, Silence
from hs_sim.engine.equipment import equipped_weapon
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardDefinition, CardType, CostAuraSpec, CostSpec,
    Keyword, PaymentType, TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion, MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

ANVIL, HERALD, RAY, PROTOTYPE, SERVANT, WYRM, KNIGHT, VANGUARD, ANIMATOR, WARBAND, CULTIST, ANOMALY, GOLEM = (
    'BE_042', 'BE_169', 'BE_193', 'BE_207', 'BE_228', 'BE_255', 'BE_285',
    'BE_572', 'BE_600', 'BE_701', 'BE_729', 'BE_842', 'BE_861')
ROOTS = COLLECTIBLE_ROOTS = (ANVIL, HERALD, RAY, PROTOTYPE, SERVANT, WYRM, KNIGHT,
    VANGUARD, ANIMATOR, WARBAND, CULTIST, ANOMALY, GOLEM)
DEPENDENCIES = ()
PREFIX = 'cards.black_empire_primitives.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/black-empire-primitives-v1.json'
BATCH_HASH = 'b3acf39924eeb3c5e6307de26b7004436c35194fadf1270a66eebd3d2f58d9ec'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(r['record']['id'] for r in data['cards']) != ROOTS or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(r['record']) != r['record_sha256'] for r in data['cards']) or
            data['reviewed_zero_attack'] != {PROTOTYPE: 0}):
        raise TargetValidationError('Black Empire primitives require thirteen complete original candidate faces')
    raw = next(r['record'] for r in data['cards'] if r['record']['id'] == PROTOTYPE)
    faces = [o['face'] for o in data['official_observations'] if o['card_id'] == PROTOTYPE]
    if raw['attack'] is not None or 'ATK' in raw['tags'] or len(faces) != 2 or any(f['attack'] != 0 for f in faces):
        raise TargetValidationError('Prototype zero Attack requires both exact primary zero observations')
    return data


def register_black_empire_primitive_cards(registry):
    def other_minion_play(c):
        row = play_record(c.state, dict(c.event.data)['play_id'])
        if not row.completed or (row.source_id, row.player_id) != (c.event.source_id, c.event.player_id):
            raise ResolutionError('Black Empire trigger lost its actual completed physical play')
        return (row.player_id == c.player_id and row.kind == CardType.MINION and
            row.source_id != c.source_id and living_source(c))

    def animator(c):
        event = c.event
        if event is None or event.kind != 'armor_gained':
            raise ResolutionError('Steel Animator requires its original armor-gain notification')
        if (event.player_id != c.player_id or event.target_id != c.state.players[c.player_id].hero_id or
                event.amount <= 0 or not living_source(c)): return ()
        return (Draw(c.player_id, source_id=c.source_id),)

    def herald(c):
        if equipped_weapon(c.state, c.state.players[c.player_id]) is None: return ()
        return (Buff(c.source_id, 1, 1, c.source_id), GrantKeyword(c.source_id, Keyword.RUSH, c.source_id))

    bodies = dict(
        anvil=lambda c: (Buff(c.state.players[c.player_id].hero_id, attack=4,
            source_id=c.source_id, expires_turn=c.state.turn),),
        herald=herald,
        prototype=lambda c: (BuffMinionsInZones(c.player_id, 1, 1,
            MinionScope(zones=(Zone.HAND,)), c.source_id),),
        silence=lambda c: (Silence(c.target_id),) if c.target_id is not None else (),
        wyrm=lambda c: (BuffCapturedMinion(MinionReference.capture(c.source), health=1,
            source_id=c.source_id),) if other_minion_play(c) else (),
        armor=lambda c: (GainArmor(c.player_id, 3),),
        animator=animator,
        warband=lambda c: (Draw(c.player_id, source_id=c.source_id),) if other_minion_play(c) else (),
        anomaly=lambda c: (Freeze(c.target_id, c.source_id), GainArmor(c.player_id, 3), Draw(c.player_id, source_id=c.source_id)),
        golem=lambda c: (Heal(c.state.players[c.player_id].hero_id, 3, c.source_id),))
    for name, body in bodies.items(): registry.register_behavior(PREFIX+name, body)
    keywords = {RAY: (Keyword.POISONOUS,), PROTOTYPE: (Keyword.REBORN,), KNIGHT: (Keyword.LIFESTEAL,),
        VANGUARD: (Keyword.TAUNT,), GOLEM: (Keyword.TAUNT, Keyword.REBORN)}
    for row in load_batch()['cards']:
        raw = row['record']; cid = raw['id']; kind = CardType(raw['type'].lower()); fields = {}
        if kind == CardType.MINION:
            attack = 0 if cid == PROTOTYPE else raw['attack']
            if type(attack) is not int or type(raw['health']) is not int:
                raise TargetValidationError('Unreviewed Black Empire printed minion numbers')
            fields.update(attack=attack, health=raw['health'])
        else: fields['spell_school'] = SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL'))
        if cid == ANVIL:
            if raw['tags'].get('CARD_ALTERNATE_COST') != 2 or raw['cost'] != 2:
                raise TargetValidationError('Anvil lost its original armor payment declaration')
            fields.update(cost_payment=PaymentType.ARMOR, on_play=PREFIX+'anvil')
        elif cid == HERALD: fields['battlecry'] = PREFIX+'herald'
        elif cid == PROTOTYPE: fields['deathrattle'] = PREFIX+'prototype'
        elif cid == SERVANT:
            fields.update(battlecry=PREFIX+'silence', targeting=TargetSpec(TargetMode.IF_AVAILABLE,
                zones=(Zone.BOARD,), kinds=(CardType.MINION,)))
        elif cid == VANGUARD: fields.update(battlecry=PREFIX+'armor', deathrattle=PREFIX+'armor')
        elif cid in (WYRM, WARBAND): fields['triggers'] = (TriggerSpec('card_played', PREFIX+('wyrm' if cid == WYRM else 'warband')),)
        elif cid == ANIMATOR: fields['triggers'] = (TriggerSpec('armor_gained', PREFIX+'animator'),)
        elif cid == CULTIST: fields['cost_auras'] = (CostAuraSpec(CostSpec(delta=1, card_types=(CardType.SPELL,)), relation='any'),)
        elif cid == ANOMALY:
            fields.update(on_play=PREFIX+'anomaly', targeting=TargetSpec(relation='enemy'))
        elif cid == GOLEM: fields['deathrattle'] = PREFIX+'golem'
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'],
            keywords=keywords.get(cid, ()), metadata=metadata_from_record(raw), **fields)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
