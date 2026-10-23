"""Historical original-event listeners and native conditional providers."""
import json
from pathlib import Path

from hs_sim.engine.effects import AddToHand, Damage, DamageBatch, InvokeBehavior
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (
    AuraSpec, CardDefinition, CardType, DamageKind, EndTurnSpec, Keyword, KeywordAuraSpec,
    StatRelationLayer, StatRelationOperand, StatRelationSpec, TargetMode, TargetSpec, TriggerSpec, Zone,
)
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion, GrantCapturedKeyword, MinionReference
from hs_sim.engine.target_predicates import TargetPredicateSpec
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.engine.zones import DrawMatching
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .played_minion_keyword_cards import original_recipient, played_minion


SECRETKEEPER, UNDERTAKER, BERSERKER, SKIPPER, SINGER, CORPSE, SOLOIST, TOXFIN, TAR, BUCCANEER, DECKHAND, WOLF, TEMPEST = (
    'EX1_080', 'FP1_028', 'ICC_238', 'YOD_022', 'JAM_001', 'LEG_RLK_079', 'ETC_358',
    'DAL_077', 'TOY_000', 'WON_351', 'CS2_146', 'DS1_175', 'DRG_216')
LEAVES = (SECRETKEEPER, UNDERTAKER, BERSERKER, SKIPPER, SINGER, CORPSE, SOLOIST, TOXFIN,
    TAR, BUCCANEER, DECKHAND, WOLF, TEMPEST)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_one_cost_event_conditions.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-one-cost-event-conditions-v1.json'
BATCH_HASH = '8f83a302c77147ea894fbdf3f314e30a2f3ab3fb7cfb462db94253e3a66d8529'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(row['record']['id'] for row in data['dependencies']) != LEAVES or
            any(data[k] for k in ('cards', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            data['numeric_normalizations'] != {TAR: {'attack': 0}} or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in data['dependencies'])):
        raise TargetValidationError('Historical event consumers lost their complete sources')
    return data


def register_past_one_cost_event_condition_cards(registry):
    data = load_batch()
    registry.register_target_predicate(TargetPredicateSpec(PREFIX + 'murloc', current_tribes_any=('murloc',)))

    def secretkeeper(c):
        row = play_record(c.state, dict(c.event.data)['play_id'])
        if not row.completed or (row.source_id, row.player_id) != (c.event.source_id, c.event.player_id):
            raise ResolutionError('Secretkeeper lost its original completed hand play')
        if row.kind != CardType.SPELL or not living_source(c):
            return ()
        if row.submitted_cost is None:
            raise ResolutionError('Secretkeeper requires the original physical paid input')
        secret = any(a.kind == 'keyword' and a.keyword == Keyword.SECRET and not a.consumed
            for a in row.submitted_cost.quote.quote_input.abilities)
        return (BuffCapturedMinion(MinionReference.capture(c.source), 1, 1, c.source_id),) if secret else ()

    def undertaker(c):
        if c.event.player_id != c.player_id or c.event.target_id == c.source_id or not living_source(c):
            return ()
        rows = [r for r in c.state.successful_summon_history if r.event_sequence == c.event.sequence]
        if len(rows) != 1 or (rows[0].entity_id, rows[0].player_id) != (c.event.target_id, c.event.player_id):
            raise ResolutionError('Undertaker lost its original successful summon')
        return (BuffCapturedMinion(MinionReference.capture(c.source), 1, 1, c.source_id),) if rows[0].deathrattle_ids else ()

    def paid_listener(c, behavior):
        row = played_minion(c)
        return (InvokeBehavior(PREFIX + behavior, row.source_id, row.player_id, c.source_id, row.id),) \
            if row is not None and living_source(c) else ()

    def berserker_now(c):
        target = original_recipient(c, c.play)
        return (Damage(target.id, 1, c.target_id, DamageKind.MINION_ABILITY),) if target is not None else ()

    def skipper_now(c):
        targets = tuple(i for p in (1, 2) for i in c.state.players[p].board for e in (c.state.entities[i],)
            if e.kind == CardType.MINION and registry.card(e.card_id).interactable is None
            and e.active and e.health > 0 and not e.doomed)
        return (DamageBatch(tuple(Damage(i, 1, c.target_id, DamageKind.MINION_ABILITY) for i in targets)),)

    def corpse(c):
        targets = (() if c.target_id is None else (c.target_id,)) + (c.state.players[c.player_id].hero_id,)
        return (DamageBatch(tuple(Damage(i, 2, c.source_id, DamageKind.MINION_ABILITY) for i in targets)),)

    def soloist(c):
        others = any(i != c.source_id and c.state.entities[i].kind == CardType.MINION and
            registry.card(c.state.entities[i].card_id).interactable is None for i in c.state.players[c.player_id].board)
        return () if others else (AddToHand(c.player_id, SOLOIST, c.source_id),)

    def toxfin(c):
        target = c.state.entities.get(c.target_id)
        if (target is None or target.kind != CardType.MINION or target.zone != Zone.BOARD or
                target.controller != c.player_id or not target.active or target.health <= 0 or target.doomed or
                not has_any_tribe(registry, target, ('murloc',))):
            return ()
        return (GrantCapturedKeyword(MinionReference.capture(target), Keyword.POISONOUS, c.source_id),)

    bodies = {
        SECRETKEEPER: secretkeeper, UNDERTAKER: undertaker,
        BERSERKER: lambda c: paid_listener(c, 'berserker_now'), SKIPPER: lambda c: paid_listener(c, 'skipper_now'),
        'berserker_now': berserker_now, 'skipper_now': skipper_now,
        SINGER: lambda c: (DrawMatching(c.player_id, PoolQuery(kinds=(CardType.SPELL,),
            keywords_all=(Keyword.SECRET,)), 'skip', source_id=c.source_id),),
        CORPSE: corpse, SOLOIST: soloist, TOXFIN: toxfin,
    }
    for cid, body in bodies.items(): registry.register_behavior(PREFIX + cid, body)
    relations = {TAR: (StatRelationOperand.CONTROLLER_OPPONENT_TURN, 2),
        BUCCANEER: (StatRelationOperand.CONTROLLER_HAS_WEAPON, 2),
        TEMPEST: (StatRelationOperand.CONTROLLER_OVERLOADED_MANA, 1)}
    for row in data['dependencies']:
        raw = row['record']; cid = raw['id']; fields = {}
        attack = 0 if cid == TAR else raw['attack']
        if (raw['type'] != 'MINION' or raw['cost'] != 1 or raw['collectible'] is not True or
                type(attack) is not int or type(raw['health']) is not int or
                cid == TAR and (raw['attack'] is not None or 'ATK' in raw['tags'])):
            raise TargetValidationError('Historical event consumer lost its native minion body')
        if cid in (SECRETKEEPER, BERSERKER, SKIPPER):
            fields['triggers'] = (TriggerSpec('card_played', PREFIX + cid),)
        elif cid == UNDERTAKER:
            fields['triggers'] = (TriggerSpec('minion_summoned', PREFIX + cid),)
        elif cid == SINGER:
            fields['triggers'] = (TriggerSpec('turn_ended', PREFIX + cid, EndTurnSpec()),)
        elif cid in (CORPSE, SOLOIST, TOXFIN):
            fields['battlecry'] = PREFIX + cid
        if cid in (CORPSE, TOXFIN):
            fields['targeting'] = TargetSpec(TargetMode.IF_AVAILABLE,
                zones=(Zone.HERO, Zone.BOARD) if cid == CORPSE else (Zone.BOARD,),
                kinds=(CardType.HERO, CardType.MINION) if cid == CORPSE else (CardType.MINION,),
                relation='enemy' if cid == CORPSE else 'friendly')
            if cid == TOXFIN: fields['target_rule'] = PREFIX + 'murloc'
        if cid in relations:
            operand, amount = relations[cid]
            fields['stat_relations'] = (StatRelationSpec(operand=operand,
                layer=StatRelationLayer.CONDITIONAL_ATTACK, amount=amount),)
        if cid == TAR: fields['keywords'] = (Keyword.TAUNT,)
        elif cid == DECKHAND:
            fields['keyword_auras'] = (KeywordAuraSpec(Keyword.CHARGE, target='self', condition='controller_has_weapon'),)
        elif cid == WOLF: fields['auras'] = (AuraSpec(attack=1, tribes_any=('beast',)),)
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=1, attack=attack, health=raw['health'],
            metadata=metadata_from_record(raw), **fields)
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
