"""Real damage, healing and completed-action consumers of public effects."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import (AddToHand, Buff, Damage, DamageBatch, Destroy,
    Heal, InvokeBehavior, RandomDamage)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardDefinition, CardType, DamageKind, HealingKind,
    Keyword, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import completed_attack, living_source
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import characters, minions

VOID, DESCENT, FLAMER, PATROL, BEAST = 'BE_284', 'BE_325', 'BE_552', 'BE_723', 'BE_749'
OVERDRIVE = 'BE_553t'
ROOTS = COLLECTIBLE_ROOTS = (VOID, DESCENT, FLAMER, PATROL, BEAST)
DEPENDENCIES = ()
PREFIX = 'cards.native_combat_consumers.'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/native-combat-consumers-v1.json'
BATCH_HASH = 'e876c26db57d54f481e03bd485469265652b7bb0dd09a40b278a1bd347868b41'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(r['record']['id'] for r in data['cards']) != ROOTS or
            any(data[k] for k in ('dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            tuple(r['record']['id'] for r in data['existing_dependencies']) != (OVERDRIVE,) or
            any(canonical_digest(r['record']) != r['record_sha256']
                for key in ('cards', 'existing_dependencies') for r in data[key])):
        raise TargetValidationError('Native combat consumers require their complete reviewed source')
    return data


def register_native_combat_consumer_cards(registry):
    data = load_batch()
    if canonical_digest(asdict(registry.card(OVERDRIVE))) != data['existing_dependencies'][0]['definition_sha256']:
        raise TargetValidationError('Flamer lost its original complete Overdrive dependency')

    def void(c):
        target = c.state.entities[c.target_id]
        board = c.state.players[target.controller].board
        if target.id not in minions(c, registry, target.controller): return ()
        index = board.index(target.id)
        neighbors = {board[i] for i in (index-1, index+1) if 0 <= i < len(board)}
        return (DamageBatch((Damage(target.id, 4, c.source_id, DamageKind.SPELL),) +
            tuple(Damage(i, 2, c.source_id, DamageKind.SPELL)
                for i in minions(c, registry, target.controller) if i in neighbors)),)

    def descent(c):
        target = c.state.entities[c.target_id]
        if target.id not in minions(c, registry, target.controller): return ()
        # Freeze the amount and recipient before destruction and its reactions.
        return (Destroy(target.id, c.source_id), Heal(c.state.players[target.controller].hero_id,
            target.health, c.source_id, HealingKind.SPELL))

    def flamer(c):
        row = completed_attack(c)
        if (row is None or row.source_kind != CardType.HERO or
                row.declaration.player_id != c.player_id): return ()
        return (AddToHand(c.player_id, OVERDRIVE, c.source_id),)

    def patrol(c):
        row = play_record(c.state, dict(c.event.data)['play_id'])
        if not row.completed or (row.source_id, row.player_id) != (c.event.source_id, c.event.player_id):
            raise ResolutionError('Patrol requires its original completed physical play')
        if row.player_id != c.player_id or not living_source(c): return ()
        face = registry.card(row.card_id)
        if face.combo is None and Keyword.COMBO not in face.keywords: return ()
        return (RandomDamage(characters(c, registry, 3-c.player_id), 3, c.source_id, DamageKind.MINION_ABILITY),)

    def beast(c):
        summon = SummonFromPool(c.player_id, 'constructed.minions',
            PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=1, max_cost=1),
            source_id=c.source_id, cause=SummonCause.capture(c))
        return (summon, summon, InvokeBehavior(PREFIX+'beast_buff', c.source_id, c.player_id))

    bodies = {VOID: void, DESCENT: descent, FLAMER: flamer, PATROL: patrol, BEAST: beast,
        'beast_buff': lambda c: tuple(Buff(i, 3, 0, c.source_id) for i in minions(c, registry, c.player_id))}
    for cid, body in bodies.items(): registry.register_behavior(PREFIX+cid, body)
    for row in data['cards']:
        raw = row['record']; cid = raw['id']; kind = CardType(raw['type'].lower())
        fields = (dict(attack=raw['attack'], health=raw['health']) if kind == CardType.MINION else
            dict(attack=raw['attack'], durability=raw['health']) if kind == CardType.WEAPON else
            dict(spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL'))))
        if cid in (VOID, DESCENT):
            fields.update(on_play=PREFIX+cid, targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)))
        elif cid == FLAMER: fields['triggers'] = (TriggerSpec('attack_finished', PREFIX+cid),)
        elif cid == PATROL: fields['triggers'] = (TriggerSpec('card_played', PREFIX+cid),)
        elif cid == BEAST: fields['deathrattle'] = PREFIX+cid
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'], metadata=metadata_from_record(raw), **fields)
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
