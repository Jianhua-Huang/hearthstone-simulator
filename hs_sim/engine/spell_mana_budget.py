"""Sequential printed-mana spell picks, joined to the ordinary physical CASTs."""
from dataclasses import dataclass
import json

from .effects import Effect, _integer, _player, _source
from .errors import ResolutionError
from .lifecycle import active_abilities
from .model import CardType, HealthOp, SpellManaBudgetLink, SpellSchool
from .pools import PoolQuery, resolve_candidates, sample_candidates


@dataclass(frozen=True)
class CastManaWorth(Effect):
    player_id: int
    pool_id: str
    school: SpellSchool
    amount: int
    source_id: int
    source_card_id: str

    def __post_init__(self):
        _player(self.player_id);_source(self.source_id)
        if self.source_id is None:raise ValueError('Spell budget requires its original physical caster')
        SpellManaBudgetLink(self.pool_id,self.school,self.amount,self.amount,self.source_card_id)


@dataclass(frozen=True)
class ContinueSpellManaWorth(Effect):
    cast_id: int

    def __post_init__(self):_integer(self.cast_id,'actual budget CAST',1)

    def validate_in_state(self,state,registry):
        self.__post_init__()
        if self.cast_id>len(state.cast_history):raise ValueError('Unknown original spell budget CAST')
        record=state.cast_history[self.cast_id-1]
        validate_record(state,registry,record)
        if record.mana_budget is None or record.interrupted:
            raise ValueError('Continuation needs an uninterrupted original budget CAST')
        return record


def blocks_enemy_spell(target,definition):
    return definition.kind==CardType.SPELL and any(a.health_rule.operation==HealthOp.SPELL_IMMUNITY and
        definition.spell_school in a.health_rule.schools for a in active_abilities(target,'health_rule'))


def query(school,remaining):
    return PoolQuery(kinds=(CardType.SPELL,),collectible=True,min_cost=0,max_cost=remaining,
        spell_schools=(school,))


def candidates(registry,context,link,player_id,remaining=None):
    amount=link.remaining if remaining is None else remaining
    rows=resolve_candidates(registry,context,link.pool_id,query(link.school,amount),
        source_card_id=link.source_card_id,player_id=player_id,exclude_source_by_rule=True)
    for row in rows:
        card=registry.card(row.card_id)
        if card.kind!=CardType.SPELL or not card.hand_playable or card.choice_only or card.spell_school!=link.school:
            raise ValueError('Every eligible budget spell requires its complete original executable face')
    return rows


def remaining_after(registry,record):
    return record.mana_budget.remaining-registry.pool_card(record.card_id).cost


def validate_record(state,registry,record):
    record.__post_init__();link=record.mana_budget
    if link is None:return
    source=registry.card(link.source_card_id)
    if source.kind!=CardType.MINION or record.caster_id not in state.entities:
        raise ValueError('Spell budget lost its original minion source')
    card=registry.pool_card(record.card_id)
    if card.kind!=CardType.SPELL or card.spell_school!=link.school or card.cost>link.remaining:
        raise ValueError('Actual spell differs from its original printed-mana budget')
    if link.previous_cast_id is None:return
    previous=state.cast_history[link.previous_cast_id-1];parent=previous.mana_budget
    if (parent is None or not previous.completed or previous.interrupted or
            (previous.player_id,previous.caster_id,parent.pool_id,parent.school,parent.budget,parent.source_card_id)!=
            (record.player_id,record.caster_id,link.pool_id,link.school,link.budget,link.source_card_id) or
            remaining_after(registry,previous)!=link.remaining):
        raise ValueError('Spell budget lost its complete actual preceding CAST and printed remainder')


def receipt(record):
    from dataclasses import asdict
    return json.dumps(asdict(record.mana_budget),ensure_ascii=False,sort_keys=True,separators=(',',':'))


def accept(r,player_id,source_id,link):
    rows=candidates(r.registry,r.game._generation_context,link,player_id)
    if not rows:return ()
    selected,=sample_candidates(r.game._rng,rows,1,replacement=True)
    from .automatic_targets import AutomaticTargetPreference
    from .spell_casts import CastSpell,cast_generated
    cast_id=len(r.state.cast_history)+1
    work=cast_generated(r,CastSpell(player_id,selected,source_id,
        target_preference=AutomaticTargetPreference.ENEMY_IF_AVAILABLE,mana_budget=link))
    record=r.state.cast_history[cast_id-1]
    if record.mana_budget!=link:raise ResolutionError('Spell budget lost its accepted ordinary CAST')
    return (*work,ContinueSpellManaWorth(cast_id))


def start(r,effect):
    effect.__post_init__()
    return accept(r,effect.player_id,effect.source_id,SpellManaBudgetLink(effect.pool_id,effect.school,
        effect.amount,effect.amount,effect.source_card_id))


def continue_budget(r,effect):
    record=effect.validate_in_state(r.state,r.registry)
    if not record.completed:raise ResolutionError('Spell budget preceded completion of its original CAST')
    remaining=remaining_after(r.registry,record)
    if remaining==0:return ()
    link=record.mana_budget
    return accept(r,record.player_id,record.caster_id,SpellManaBudgetLink(link.pool_id,link.school,
        link.budget,remaining,link.source_card_id,record.id))


def link_from_dict(value):
    if value is None:return None
    from .serialization import _row
    row=_row(value,SpellManaBudgetLink);row['school']=SpellSchool(row['school'])
    return SpellManaBudgetLink(**row)


def validate_boundary(game):
    state,registry=game._state,game.registry
    rows={c.id:c for c in state.cast_history if c.mana_budget is not None}
    controls=[]
    frame=game._frame
    if frame is not None:
        controls=[w for w in (*frame.prefix,*frame.continuation,
            *(w for o in frame.options for w in o.effects)) if type(w) is ContinueSpellManaWorth]
    if not rows and not controls:return
    children={};cached={}
    def pool(record,remaining):
        link=record.mana_budget
        key=(link.pool_id,link.school,link.source_card_id,record.player_id,remaining)
        if key not in cached:cached[key]=candidates(registry,game._generation_context,link,record.player_id,remaining)
        return cached[key]
    for record in rows.values():
        validate_record(state,registry,record)
        if record.card_id not in {m.card_id for m in pool(record,record.mana_budget.remaining)}:
            raise ValueError('Budget CAST outside its original complete eligible pool')
        previous=record.mana_budget.previous_cast_id
        if previous is not None:
            if previous in children:raise ValueError('One actual budget CAST forked into two later picks')
            children[previous]=record.id
    pending={}
    for control in controls:
        control.validate_in_state(state,registry)
        pending[control.cast_id]=pending.get(control.cast_id,0)+1
    if state.status!='playing':
        if controls:raise ValueError('Terminal spell budget retained live continuations')
        return
    for record in rows.values():
        remaining=remaining_after(registry,record)
        needs_more=not record.interrupted and (not record.completed or remaining>0 and bool(pool(record,remaining)))
        following=int(record.id in children)+pending.get(record.id,0)
        if needs_more and following!=1 or not needs_more and (
                record.id in children or pending.get(record.id,0)>1):
            raise ValueError('Spell budget lost, duplicated or invented its remaining continuation')
        if not record.completed and record.id in children:raise ValueError('Later budget CAST preceded actual completion')


def register(mechanics):
    mechanics.register_payload_type(SpellManaBudgetLink)
    mechanics.register(CastManaWorth,start)
    mechanics.register(ContinueSpellManaWorth,continue_budget)
