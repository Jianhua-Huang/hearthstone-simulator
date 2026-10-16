"""Real spell-granted Deathrattles using the existing attachment lifecycle."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import Buff, Damage, DamageBatch, GrantDeathrattle, GrantKeyword, InvokeBehavior, SetStats
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, Keyword, TargetSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/granted-deathrattle-effects-v1.json'
BATCH_HASH = '382613a42f2ce69e6b13bcbed50183361569aa6f445211babc26a7a837186f85'
STEED = 'CORE_UNG_952'
STEGODON = 'UNG_810'
BODY = 'cards.granted_deathrattle.steed'
PAYLOAD = 'cards.granted_deathrattle.stegodon'
MASK = 'DINO_429'
LAST_STAND = 'CATA_610'
MASK_BODY = 'cards.granted_deathrattle.sheep_mask'
MASK_PAYLOAD = 'cards.granted_deathrattle.sheep_blast'
LAST_BODY = 'cards.granted_deathrattle.last_stand'
LAST_PAYLOAD = 'cards.granted_deathrattle.hand_recruit'


def load_batch():
    batch = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(batch) != BATCH_HASH:
        raise TargetValidationError('Granted Deathrattle complete source pin changed')
    return batch


def register_granted_deathrattle_cards(registry):
    batch = load_batch()
    rows = {row['record']['id']: row for row in batch['cards']}
    if len(batch['cards']) != 4 or set(rows) != {STEED, STEGODON, MASK, LAST_STAND}:
        raise TargetValidationError('Unreviewed granted Deathrattle family')
    if (rows[STEED]['record']['tags']['COLLECTION_RELATED_CARD_DATABASE_ID'] != batch['dependency_dbf_id']
            or rows[STEGODON]['record']['dbf_id'] != batch['dependency_dbf_id']):
        raise TargetValidationError('Granted Deathrattle dependency lost its explicit DBF')

    def grant(context):
        return (Buff(context.target_id, 2, 6, context.source_id),
                GrantKeyword(context.target_id, Keyword.TAUNT, context.source_id),
                GrantDeathrattle(context.target_id, PAYLOAD, context.source_id))

    def summon(context):
        board = context.state.players[context.player_id].board
        position = (context.death.position if context.death is not None else
                    board.index(context.source_id) + 1 if context.source_id in board else None)
        return (SummonByCard(context.player_id, (SummonEntryMaterial(STEGODON),),
                             SummonCause.capture(context), position=position),)

    registry.register_behavior(BODY, grant)
    registry.register_behavior(PAYLOAD, summon)
    registry.register_behavior(MASK_BODY, lambda c: (SetStats(c.target_id, 1, 1, c.source_id),
        GrantDeathrattle(c.target_id, MASK_PAYLOAD, c.source_id)))
    registry.register_behavior(MASK_PAYLOAD, lambda c: (InvokeBehavior(MASK_PAYLOAD+'.now', c.source_id, c.player_id),))
    registry.register_behavior(MASK_PAYLOAD+'.now', lambda c: (DamageBatch(tuple(
        Damage(eid, 2, c.source_id, DamageKind.MINION_ABILITY)
        for pid in (1, 2) for eid in minions(c, registry, pid))),))
    registry.register_behavior(LAST_BODY, lambda c: (GrantDeathrattle(c.target_id, LAST_PAYLOAD, c.source_id),))
    def recruit(context):
        board = context.state.players[context.player_id].board
        position = (context.death.position if context.death is not None else
                    board.index(context.source_id) + 1 if context.source_id in board else None)
        return (SummonFromZone(context.player_id, zone=Zone.HAND, position=position,
            source_id=context.source_id, cause=SummonCause.capture(context)),)
    registry.register_behavior(LAST_PAYLOAD, recruit)
    bodies = {STEED: BODY, MASK: MASK_BODY, LAST_STAND: LAST_BODY}
    for cid, row in rows.items():
        raw, recipe = row['record'], row['recipe']
        if canonical_digest(raw) != row['record_sha256'] or raw['collectible'] is not True:
            raise TargetValidationError('Granted Deathrattle face lost its reviewed identity')
        kwargs = (dict(on_play=bodies[cid], targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)))
                  if cid in bodies else dict(health=raw['health']))
        card = CardDefinition(cid, raw['name'], CardType(raw['type'].lower()), cost=raw['cost'],
            attack=raw['attack'] or 0, keywords=tuple(Keyword(k) for k in recipe['keywords']),
            metadata=replace(metadata_from_record(raw), deck_identity=recipe['deck_identity']), **kwargs)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
