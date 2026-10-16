"""Real physical tutors, native Kindred and finite hero Attack followups."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.effects import Buff, TriggerDeathrattles
from hs_sim.engine.kindred import repeat_components, request as kindred_request
from hs_sim.engine.model import CardDefinition, CardType, KindredProfile, Keyword, PlayerEffectSpec, RewindSpec, TriggerSpec, Zone
from hs_sim.engine.physical_draw_groups import DrawGroupReward, DrawGroupSlot, DrawPhysicalGroup
from hs_sim.engine.play_history import starting_deck_identity
from hs_sim.engine.player_effects import AddPlayerEffect, RemovePlayerEffect
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion, MinionReference
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-draw-followups-v1.json'
BATCH_HASH = '981c4ec75359df91fa48c86536bdfd9db0d247acd00bbd788f8c684877344cb7'
DREAMWARDEN = 'EDR_256'; VANGUARD = 'TIME_003'; SLAGCLAW = 'TLC_482'; CHRONIKAR = 'END_006'; CINDER = 'TLC_249'
ROOTS = (DREAMWARDEN, VANGUARD, SLAGCLAW, CHRONIKAR)
PREFIX = 'cards.native_draw_followup.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Native draw followups lost their complete reviewed pin')
    if tuple(row['record']['id'] for row in data['cards']) != ROOTS or data['dependencies']:
        raise TargetValidationError('Unreviewed native draw-followup roots or dependencies')
    for row in data['cards'] + data['existing_dependencies'] + data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Native draw-followup full source row changed')
    return data


def register_native_draw_followup_cards(registry):
    data = load_batch()
    existing, = data['existing_dependencies']
    if existing['record']['id'] != CINDER or canonical_digest(asdict(registry.card(CINDER))) != existing['definition_sha256']:
        raise TargetValidationError('Slagclaw requires the complete original Sizzling Cinder')

    def dreamwarden(c):
        original, _ = starting_deck_identity(c.state)
        original = set(original[c.player_id - 1])
        if not any(i not in original or c.state.entities[i].face_replaced for i in c.state.players[c.player_id].deck):
            return ()
        reward = (() if c.source.kind != CardType.MINION or c.source.zone != Zone.BOARD else
                  (BuffCapturedMinion(MinionReference.capture(c.source), 2, 2, c.source_id),))
        return (DrawPhysicalGroup(c.player_id, c.source_id,
                    (DrawGroupSlot(PoolQuery(), starting_deck=False),)), *reward)

    def slag_prepare(c):
        item = SummonByCard(c.player_id, (SummonEntryMaterial(CINDER),), SummonCause.capture(c))
        return item, item, *repeat_components(c)

    def slag_active(c):
        return tuple(TriggerDeathrattles(i, c.source_id) for i in minions(c, registry, c.player_id)
                     if c.state.entities[i].card_id == CINDER)

    def attack(c):
        return Buff(c.state.players[c.player_id].hero_id, attack=3, source_id=c.source_id, expires_turn=c.state.turn)

    def future(c, remaining):
        if c.event is None or c.event.kind != 'turn_started' or c.event.player_id != c.player_id:
            return ()
        if c.player_effect is None:
            raise ValueError('Chronikar lost its original independent future grant')
        tail = (AddPlayerEffect(c.player_id, PREFIX + 'last_turn', c.source_id),) if remaining == 2 else ()
        return attack(c), RemovePlayerEffect(c.player_id, c.player_effect.id), *tail

    bodies = {
        'dreamwarden': dreamwarden,
        'vanguard': lambda c: (DrawPhysicalGroup(c.player_id, c.source_id,
            (DrawGroupSlot(PoolQuery(kinds=(CardType.MINION,))),), DrawGroupReward('buff_all', 2)),),
        'slagclaw': lambda c: kindred_request(c, SLAGCLAW),
        'slag_prepare': slag_prepare, 'slag_active': slag_active,
        'chronikar': lambda c: (attack(c), AddPlayerEffect(c.player_id, PREFIX + 'next_turn', c.source_id)),
        'next_turn': lambda c: future(c, 2), 'last_turn': lambda c: future(c, 1),
    }
    for name, body in bodies.items():
        registry.register_behavior(PREFIX + name, body)
    for name in ('next_turn', 'last_turn'):
        # Ordinary persistent sources avoid borrowing the capacity-limited
        # objective area. Each accepted stage removes itself at its real turn.
        registry.register_player_effect(PlayerEffectSpec(PREFIX + name, CHRONIKAR,
            triggers=(TriggerSpec('turn_started', PREFIX + name),)))
    for row in data['cards']:
        raw = row['record']; cid = raw['id']
        if raw['type'] != 'MINION' or raw['collectible'] is not True:
            raise TargetValidationError('Native draw-followup root is not its complete collectible minion')
        body = {DREAMWARDEN: 'dreamwarden', VANGUARD: 'vanguard', SLAGCLAW: 'slagclaw', CHRONIKAR: 'chronikar'}[cid]
        kwargs = {'battlecry': PREFIX + body}
        if cid == DREAMWARDEN:
            kwargs['keywords'] = (Keyword.TAUNT,)
        elif cid == VANGUARD:
            kwargs.update(keywords=(Keyword.REWIND,), rewind=RewindSpec())
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'], health=raw['health'],
            metadata=replace(metadata_from_record(raw), deck_identity=cid), **kwargs)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_kindred_profile(KindredProfile(SLAGCLAW, 'body', wrapper=PREFIX + 'slagclaw',
        prepare=PREFIX + 'slag_prepare', active=PREFIX + 'slag_active'))
