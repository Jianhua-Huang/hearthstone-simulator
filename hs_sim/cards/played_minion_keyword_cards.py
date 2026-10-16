"""Two real played-minion listeners over original paid/entry facts."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.bonus_effects import GrantRandomBonusEffects
from hs_sim.engine.effects import InvokeBehavior
from hs_sim.engine.board_presence import resolve_board_presence
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BoardPresenceReference,CardDefinition,CardType,Keyword,TriggerSpec
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import GrantCapturedKeyword,MinionReference
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/played-minion-keywords-v1.json'
BATCH_HASH='53df0d5ab1cac5c5c58e95ad6d3c1f6a9706a80193099de21807c89ada793578'
PREFIX='cards.played_minion.'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Played-minion keyword recipes lost their complete source pin')
    return data


def played_minion(c):
    row=play_record(c.state,dict(c.event.data)['play_id'])
    if not row.completed or(row.source_id,row.player_id)!=(c.event.source_id,c.event.player_id):
        raise ResolutionError('Played-minion listener lost its original completed paid play')
    if row.player_id!=c.player_id or row.kind!=CardType.MINION or row.source_id==c.source_id or row.countered:return None
    return row


def original_recipient(c,row):
    if row.minion_result in ('countered','board_full'):return None
    if row.minion_result!='summoned':raise UnsupportedDefinitionError('Played-minion keyword recipient requires a reviewed original physical summon; magnetic recipient remains unsupported')
    # The first real entry in the same external action is the played body.
    # Transformation can retain that residence; leaving and re-entering cannot.
    entry=next((x for x in c.state.successful_summon_history if x.entity_id==row.source_id and x.action==row.action),None)
    if entry is None:raise ResolutionError('Played-minion listener lost its original successful entry')
    target=resolve_board_presence(c.state,BoardPresenceReference(row.source_id,entry.minion.entered_order))
    return target if target is not None and target.active and target.health>0 and not target.doomed else None


def register_played_minion_keyword_cards(registry):
    def deathrattle_rush(c):
        row=played_minion(c)
        if row is None:return ()
        if row.submitted_cost is None:raise ResolutionError('Deathrattle listener lost the original submitted ability inventory')
        if not any(x.kind=='deathrattle'and not x.consumed for x in row.submitted_cost.quote.quote_input.abilities):return ()
        return(InvokeBehavior(PREFIX+'rush_current',row.source_id,row.player_id,c.source_id,row.id),)
    def minion_bonus(c):
        row=played_minion(c)
        return(InvokeBehavior(PREFIX+'bonus_current',row.source_id,row.player_id,c.source_id,row.id),)if row is not None else()
    def rush_current(c):
        target=original_recipient(c,c.play)
        return(GrantCapturedKeyword(MinionReference.capture(target),Keyword.RUSH,c.target_id),)if target is not None else()
    def bonus_current(c):
        target=original_recipient(c,c.play)
        return(GrantRandomBonusEffects(target.id,1,c.target_id),)if target is not None else()
    for name,body in dict(deathrattle_rush=deathrattle_rush,minion_bonus=minion_bonus,rush_current=rush_current,bonus_current=bonus_current).items():registry.register_behavior(PREFIX+name,body)
    for item in load_batch()['cards']:
        raw,recipe=item['record'],item['recipe'];script=recipe['script']
        if canonical_digest(raw)!=item['record_sha256']or(raw['id'],script)not in (('JAIL_880','deathrattle_rush'),('EDR_849','minion_bonus')):
            raise TargetValidationError('Unreviewed played-minion keyword source')
        card=CardDefinition(raw['id'],raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            triggers=(TriggerSpec('card_played',PREFIX+script),),metadata=replace(metadata_from_record(raw),deck_identity=raw['id']))
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
