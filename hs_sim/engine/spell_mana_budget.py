"""Sequential printed-mana spell picks, joined to the ordinary physical CASTs."""
from dataclasses import dataclass
import json

from .effects import Effect, _integer, _player, _source
from .errors import ResolutionError
from .lifecycle import active_abilities
from .model import CardClass, CardType, HealthOp, SpellManaBudgetLink, SpellSchool
from .pools import PoolQuery, resolve_candidates, sample_candidates


@dataclass(frozen=True)
class CastManaWorth(Effect):
    player_id: int
    pool_id: str
    school: SpellSchool | None
    amount: int
    source_id: int
    source_card_id: str
    mage_cast_id: int | None = None

    def __post_init__(self):
        _player(self.player_id);_source(self.source_id)
        if self.source_id is None:raise ValueError('Spell budget requires its original physical caster')
        SpellManaBudgetLink(self.pool_id,self.school,self.amount,self.amount,self.source_card_id,mage_cast_id=self.mage_cast_id)

    def validate_in_state(self,state,registry):
        self.__post_init__()
        link=SpellManaBudgetLink(self.pool_id,self.school,self.amount,self.amount,self.source_card_id,mage_cast_id=self.mage_cast_id)
        mage_origin(state,registry,link,self.player_id,self.source_id,active=True)


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
    if school is None:
        return PoolQuery(kinds=(CardType.SPELL,),collectible=True,min_cost=0,max_cost=remaining,
            class_mode='specified',classes=(CardClass.MAGE,),include_neutral=False)
    return PoolQuery(kinds=(CardType.SPELL,),collectible=True,min_cost=0,max_cost=remaining,
        spell_schools=(school,))


def mage_origin(state,registry,link,player_id,source_id,*,active=False):
    if link.mage_cast_id is None:return None
    from .spell_casts import active_cast,cast_record
    original=cast_record(state,link.mage_cast_id);source=registry.card(link.source_card_id)
    if (source.kind!=CardType.SPELL or source.metadata is None or CardClass.MAGE not in source.metadata.classes or
            (original.source_id,original.card_id,original.player_id)!=(source_id,link.source_card_id,player_id)or
            not original.payload_started or original.failure is not None):
        raise ValueError('Mage budget lost its original actual Mage spell CAST')
    if active and (original.completed or original.interrupted or active_cast(state,source_id,player_id)!=original):
        raise ValueError('Mage budget must continue inside its original active spell')
    return original


def matches_domain(card,link):
    return CardClass.MAGE in card.metadata.classes if link.mage_cast_id is not None else card.spell_school==link.school


def candidates(registry,context,link,player_id,remaining=None):
    amount=link.remaining if remaining is None else remaining
    rows=resolve_candidates(registry,context,link.pool_id,query(link.school,amount),
        source_card_id=link.source_card_id,player_id=player_id,exclude_source_by_rule=True)
    for row in rows:
        card=registry.card(row.card_id)
        if card.kind!=CardType.SPELL or not card.hand_playable or card.choice_only or not matches_domain(registry.pool_card(row.card_id),link):
            raise ValueError('Every eligible budget spell requires its complete original executable face')
    return rows


def remaining_after(registry,record):
    return record.mana_budget.remaining-registry.pool_card(record.card_id).cost


def validate_record(state,registry,record):
    record.__post_init__();link=record.mana_budget
    if link is None:return
    source=registry.card(link.source_card_id)
    if record.caster_id not in state.entities or link.mage_cast_id is None and source.kind!=CardType.MINION:
        raise ValueError('Spell budget lost its original minion source')
    original=mage_origin(state,registry,link,record.player_id,record.caster_id)
    if original is not None and (original.id>=record.id or original.turn!=record.turn or original.action>record.action):
        raise ValueError('Mage budget child preceded or left its original spell interval')
    card=registry.pool_card(record.card_id)
    if card.kind!=CardType.SPELL or not matches_domain(card,link) or card.cost>link.remaining:
        raise ValueError('Actual spell differs from its original printed-mana budget')
    if link.previous_cast_id is None:return
    previous=state.cast_history[link.previous_cast_id-1];parent=previous.mana_budget
    if (parent is None or not previous.completed or previous.interrupted or
            (previous.player_id,previous.caster_id,parent.pool_id,parent.school,parent.budget,parent.source_card_id,parent.mage_cast_id)!=
            (record.player_id,record.caster_id,link.pool_id,link.school,link.budget,link.source_card_id,link.mage_cast_id) or
            remaining_after(registry,previous)!=link.remaining):
        raise ValueError('Spell budget lost its complete actual preceding CAST and printed remainder')


def receipt(record):
    from dataclasses import asdict
    return json.dumps(asdict(record.mana_budget),ensure_ascii=False,sort_keys=True,separators=(',',':'))


def accept(r,player_id,source_id,link):
    mage_origin(r.state,r.registry,link,player_id,source_id,active=True)
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
    effect.validate_in_state(r.state,r.registry)
    return accept(r,effect.player_id,effect.source_id,SpellManaBudgetLink(effect.pool_id,effect.school,
        effect.amount,effect.amount,effect.source_card_id,mage_cast_id=effect.mage_cast_id))


def continue_budget(r,effect):
    record=effect.validate_in_state(r.state,r.registry)
    if not record.completed:raise ResolutionError('Spell budget preceded completion of its original CAST')
    remaining=remaining_after(r.registry,record)
    if remaining==0:return ()
    link=record.mana_budget
    return accept(r,record.player_id,record.caster_id,SpellManaBudgetLink(link.pool_id,link.school,
        link.budget,remaining,link.source_card_id,record.id,link.mage_cast_id))


def link_from_dict(value):
    if value is None:return None
    from .serialization import _row
    row=_row(value,SpellManaBudgetLink);row['school']=None if row['school'] is None else SpellSchool(row['school'])
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
    mage_ids={c.mana_budget.mage_cast_id for c in rows.values()if c.mana_budget.mage_cast_id is not None}
    mage_finishes={key:[]for key in mage_ids}
    if mage_ids:
        from .hero_health_history import effective_events
        for event in effective_events(game.events):
            key=dict(event.data).get('cast_id')if event.kind=='spell_cast_finished'else None
            if key in mage_finishes:mage_finishes[key].append(event.sequence)
    children={};cached={}
    def pool(record,remaining):
        link=record.mana_budget
        key=(link.pool_id,link.school,link.source_card_id,link.mage_cast_id,record.player_id,remaining)
        if key not in cached:cached[key]=candidates(registry,game._generation_context,link,record.player_id,remaining)
        return cached[key]
    for record in rows.values():
        validate_record(state,registry,record)
        mage_id=record.mana_budget.mage_cast_id
        if mage_id is not None:
            original=state.cast_history[mage_id-1];finishes=mage_finishes[mage_id]
            if (len(finishes)>1 or original.completed and len(finishes)!=1 or
                    finishes and record.recorded_event>=finishes[0]):
                raise ValueError('Budget child borrowed an already finished original Mage CAST')
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
