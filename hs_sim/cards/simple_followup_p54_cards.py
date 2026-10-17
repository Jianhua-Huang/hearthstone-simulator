"""Twelve complete physical Osk battlecry faces, independent of hand cycling."""
import json
from pathlib import Path

from hs_sim.engine.cross_zone import TakeCapturedMinion
from hs_sim.engine.effects import Buff, Damage, Draw, DrawToHandLimit, GainArmor, Heal, RefreshMana
from hs_sim.engine.model import CardClass, CardDefinition, CardType, DamageKind, Keyword, TargetMode, TargetSpec, Zone
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion, GrantCapturedKeyword, MinionReference
from hs_sim.engine.spell_history import CastFromPool
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p54-v1.json'
BATCH_HASH = '0a1efe5dfcb1985b2a6270a5ff308fc1d21d3f969b3cd5502e61f527363193e9'
DRAW = 'TLC_452t7'
HEAL = 'TLC_452t8'
REFRESH = 'TLC_452t9'
DAMAGE = 'TLC_452t13'
SECRET = 'TLC_452t14'
TEAM = 'TLC_452t17'
SELF_DRAW = 'TLC_452t23'
ELUSIVE = 'TLC_452t24'
NUKE = 'TLC_452t26'
ARMOR = 'TLC_452t30'
ATTACK = 'TLC_452t31'
CONTROL = 'TLC_452t35'
ROOTS = (DRAW, HEAL, REFRESH, DAMAGE, SECRET, TEAM, SELF_DRAW, ELUSIVE, NUKE, ARMOR, ATTACK, CONTROL)
PARENT = 'TLC_452'
PREFIX = 'cards.simple_followup_p54.'
POOL_ID = 'constructed.cards'
SECRET_QUERY = PoolQuery(kinds=(CardType.SPELL,), collectible=True, class_mode='specified',
    classes=(CardClass.MAGE,), include_neutral=False, keywords_all=(Keyword.SECRET,))


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != ROOTS
            or tuple(x['record']['id'] for x in data['evidence_only']) != (PARENT,)
            or data['dependencies'] or data['existing_dependencies'] or data['skipped']):
        raise TargetValidationError('P54 complete twelve physical faces changed')
    for row in data['cards'] + data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('P54 complete original source row changed')
    return data


def register_simple_followup_p54_cards(registry):
    def self_buff(c, attack=0, health=0):
        return (BuffCapturedMinion(MinionReference.capture(c.source), attack, health, c.source_id),) if c.source.zone == Zone.BOARD else ()

    def heal(c):
        hero = c.state.entities[c.state.players[c.player_id].hero_id]
        return (Heal(hero.id, hero.max_health, c.source_id),)

    def damage(c, amount):
        return (Damage(c.target_id, amount, c.source_id, DamageKind.MINION_ABILITY),) if c.target_id is not None else ()

    def team(c):
        return tuple(BuffCapturedMinion(MinionReference.capture(c.state.entities[i]), 2, 2, c.source_id)
                     for i in minions(c, registry, c.player_id) if i != c.source_id)

    def elusive(c):
        if c.source.zone != Zone.BOARD:
            return ()
        ref = MinionReference.capture(c.source)
        return (BuffCapturedMinion(ref, 0, 3, c.source_id), GrantCapturedKeyword(ref, Keyword.ELUSIVE, c.source_id))

    def control(c):
        if c.target_id is None:
            return ()
        if (c.play is not None and c.play.source_id == c.source_id and c.play.target_id == c.target_id
                and c.play.body_targets is None and c.battlecry is not None and c.battlecry.origin == 'hand'):
            return (TakeCapturedMinion(None, c.player_id, c.source_id, c.play.id),)
        target = c.state.entities.get(c.target_id)
        if target is None or target.zone != Zone.BOARD or target.kind != CardType.MINION or not target.active or target.health <= 0 or target.doomed:
            return ()
        return (TakeCapturedMinion(MinionReference.capture(target), c.player_id, c.source_id),)

    bodies = {
        DRAW: lambda c: (DrawToHandLimit(c.player_id),),
        HEAL: heal,
        REFRESH: lambda c: (RefreshMana(c.player_id, c.state.players[c.player_id].max_mana),),
        DAMAGE: lambda c: damage(c, 5),
        SECRET: lambda c: (CastFromPool(c.player_id, POOL_ID, SECRET_QUERY, source_id=c.source_id),),
        TEAM: team,
        SELF_DRAW: lambda c: (*self_buff(c, 1, 2), Draw(c.player_id, 1, c.source_id)),
        ELUSIVE: elusive,
        NUKE: lambda c: damage(c, 20),
        ARMOR: lambda c: (*self_buff(c, health=5), GainArmor(c.player_id, 5)),
        ATTACK: lambda c: (*self_buff(c, attack=5), Buff(c.state.players[c.player_id].hero_id,
            attack=5, source_id=c.source_id, expires_turn=c.state.turn)),
        CONTROL: control,
    }
    for row in load_batch()['cards']:
        raw = row['record']
        cid = raw['id']
        if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['collectible'], raw['tags'].get('BATTLECRY')) != (
                'MINION', 6, 6, 6, False, 1):
            raise TargetValidationError('P54 physical battlecry face changed')
        registry.register_behavior(PREFIX + cid, bodies[cid])
        kwargs = {}
        if cid == DAMAGE:
            kwargs['targeting'] = TargetSpec(TargetMode.IF_AVAILABLE)
        if cid in (NUKE, CONTROL):
            kwargs['targeting'] = TargetSpec(TargetMode.IF_AVAILABLE, zones=(Zone.BOARD,),
                kinds=(CardType.MINION,), relation='enemy' if cid == CONTROL else 'any', exclude_source=True)
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=6, attack=6, health=6,
            metadata=metadata_from_record(raw), battlecry=PREFIX + cid, **kwargs)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
