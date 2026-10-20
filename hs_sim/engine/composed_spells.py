"""Two reviewed Potion ingredients, carried by one immutable physical spell face."""
from dataclasses import asdict,dataclass,replace
import base64
import binascii
import json
import random

from .effects import Effect,_integer,_player,_source
from .model import CardClass,CardType,TargetSpec,_name

PREFIX='potion:'
VERSION='potion-recipe-v1'
CREATED='composed_spell_created'
STEP='composed_spell_component'
END='composed_spell_finished'


@dataclass(frozen=True)
class ComposedSpellComponent:
    card_id:str
    behavior_id:str
    targeting:TargetSpec|None=None


@dataclass(frozen=True)
class ComposedSpellProfile:
    template_card_id:str
    ingredients:tuple[ComposedSpellComponent,...]
    behavior_id:str

    @property
    def ingredient_card_ids(self):return tuple(p.card_id for p in self.ingredients)


def validate_profile(registry,p):
    if type(p)is not ComposedSpellProfile or type(p.ingredients)is not tuple or any(type(x)is not ComposedSpellComponent for x in p.ingredients)or len(p.ingredients)!=9 or len(set(p.ingredient_card_ids))!=9:
        raise ValueError('Potion requires its nine distinct reviewed one-cost ingredients')
    _name(p.template_card_id,'Potion template');_name(p.behavior_id,'Potion body')
    registry.behavior(p.behavior_id)
    template=registry._cards[p.template_card_id]
    if (template.kind!=CardType.SPELL or template.cost!=1 or template.manual_playable or template.choice_only or
            template.metadata is None or template.metadata.collectible is not False or template.spell_school is not None):
        raise ValueError('Potion requires its uninitialized original one-cost spell template')
    for component in p.ingredients:
        cid=component.card_id
        registry.behavior(component.behavior_id)
        c=registry._cards[cid]
        if (c.kind!=CardType.SPELL or c.cost!=1 or not c.choice_only or c.on_play is not None or
                c.metadata is None or c.metadata.classes!=(CardClass.NEUTRAL,) or c.spell_school is not None):
            raise ValueError('Potion ingredients are original nonphysical one-cost neutral effect declarations')
        registry._validate_card(replace(template,manual_playable=True,on_play=p.behavior_id,targeting=component.targeting))


@dataclass(frozen=True)
class ComposedSpellRecipe:
    template_card_id:str
    first_card_id:str
    second_card_id:str

    def __post_init__(self):
        for value in(self.template_card_id,*self.parts):
            _name(value,'Potion recipe identity')
            if value.startswith((PREFIX,'crafted:','assemble:')):raise ValueError('Recursive Potion ingredients are unsupported')
        if len(set((self.template_card_id,*self.parts)))!=3:raise ValueError('Potion needs two distinct actual ingredients')

    @property
    def parts(self):return(self.first_card_id,self.second_card_id)

    @property
    def card_id(self):
        raw=json.dumps([VERSION,self.template_card_id,*self.parts],separators=(',',':')).encode('utf8')
        return PREFIX+base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def recipe_from_id(cid):
    if type(cid)is not str or not cid.startswith(PREFIX)or len(cid)>2048:raise ValueError('Expected bounded immutable Potion identity')
    token=cid[len(PREFIX):]
    try:
        data=json.loads(base64.b64decode(token+'='*((-len(token))%4),altchars=b'-_',validate=True).decode('utf8'))
    except(ValueError,UnicodeError,binascii.Error)as exc:raise ValueError('Invalid Potion recipe encoding')from exc
    if type(data)is not list or len(data)!=4 or data[0]!=VERSION:raise ValueError('Unknown Potion recipe version or fields')
    recipe=ComposedSpellRecipe(*data[1:])
    if recipe.card_id!=cid:raise ValueError('Noncanonical Potion identity')
    return recipe


def checked_recipe(registry,cid):
    recipe=recipe_from_id(cid);p=registry._composed_spell_profiles[recipe.template_card_id]
    indices=[p.ingredient_card_ids.index(cid)for cid in recipe.parts]
    if indices!=sorted(indices):raise ValueError('Potion ingredient order differs from its reviewed recipe order')
    return recipe,p


def resolve_face(registry,cid):
    from .registry import UnsupportedDefinitionError
    try:
        recipe,p=checked_recipe(registry,cid)
        template=registry._cards[recipe.template_card_id]
        targets=[component.targeting for component in p.ingredients if component.card_id in recipe.parts and component.targeting is not None]
        if len(targets)>1:raise ValueError('Potion has an unreviewed multiple directed target domain')
        face=replace(template,id=cid,manual_playable=True,on_play=p.behavior_id,targeting=targets[0]if targets else None)
        registry._validate_card(face);return face
    except(ValueError,TypeError,KeyError)as exc:raise UnsupportedDefinitionError('Unsupported Potion recipe: '+str(exc))from exc


def public_recipe(cid):
    if not cid.startswith(PREFIX):return None
    recipe=recipe_from_id(cid)
    return dict(template_card_id=recipe.template_card_id,parts=list(recipe.parts))


@dataclass(frozen=True)
class CreateRandomComposedSpell(Effect):
    player_id:int
    template_card_id:str
    source_id:int|None=None

    def __post_init__(self):
        _player(self.player_id);_name(self.template_card_id,'Potion template');_source(self.source_id)


@dataclass(frozen=True)
class ResolveComposedSpell(Effect):
    cast_id:int
    index:int=0

    def __post_init__(self):
        _integer(self.cast_id,'Potion CAST',1);_integer(self.index,'Potion component cursor',0)
        if self.index>2:raise ValueError('Potion has exactly two components')


def pack(v):return json.dumps(v,sort_keys=True,separators=(',',':'))


def create(r,e):
    from .effects import AddToHand
    from .opening import create_hand_card,announce_hand_card
    p=r.registry._composed_spell_profiles[e.template_card_id];r.player(e.player_id)
    before=r.game._rng.getstate();drawn=r.game._rng.sample(p.ingredient_card_ids,2);after=r.game._rng.getstate()
    parts=sorted(drawn,key=p.ingredient_card_ids.index);recipe=ComposedSpellRecipe(p.template_card_id,*parts)
    request=AddToHand(e.player_id,recipe.card_id,source_id=e.source_id)
    entity=create_hand_card(r,request,defer_publication=True)
    proof=dict(template=p.template_card_id,candidates=list(p.ingredient_card_ids),drawn=drawn,
        recipe_id=recipe.card_id,rng_before=before,rng_after=after,entity_id=entity.id)
    r.emit(CREATED,source_id=e.source_id,target_id=entity.id,player_id=e.player_id,proof=pack(proof),_capture=False)
    announce_hand_card(r,request,entity)


def records(game,kind):
    from .hero_health_history import effective_events
    return tuple(e for e in effective_events(game._events)if e.kind==kind)


def steps(game,cid):return tuple(e for e in records(game,STEP)if dict(e.data)['cast_id']==cid)


def resolve(r,e):
    from .spell_casts import cast_record
    record=cast_record(r.state,e.cast_id);recipe,p=checked_recipe(r.registry,record.card_id)
    if e.index!=len(steps(r.game,record.id))or any(dict(x.data)['cast_id']==record.id for x in records(r.game,END)):
        raise ValueError('Potion lost its original component progress')
    if e.index==2:
        r.emit(END,source_id=record.source_id,player_id=record.player_id,cast_id=record.id,_capture=False);return ()
    cid=recipe.parts[e.index]
    r.emit(STEP,source_id=record.source_id,player_id=record.player_id,cast_id=record.id,index=e.index,
        ingredient_card_id=cid,_capture=False)
    component=p.ingredients[p.ingredient_card_ids.index(cid)]
    return(r.call(component.behavior_id,record.source_id,record.player_id,record.target_id,cast=record),
        ResolveComposedSpell(record.id,e.index+1))


def tuple_state(value):return(value[0],tuple(value[1]),value[2])


def validate_game(game):
    from .spell_casts import cast_record
    if not game.registry._composed_spell_profiles:return
    seen=set()
    for event in records(game,CREATED):
        proof=json.loads(dict(event.data)['proof']);recipe,p=checked_recipe(game.registry,proof['recipe_id'])
        rng=random.Random();rng.setstate(tuple_state(proof['rng_before']));drawn=rng.sample(p.ingredient_card_ids,2)
        expected=ComposedSpellRecipe(p.template_card_id,*sorted(drawn,key=p.ingredient_card_ids.index))
        if (set(proof)!={'template','candidates','drawn','recipe_id','rng_before','rng_after','entity_id'}or
                proof['template']!=p.template_card_id or proof['candidates']!=list(p.ingredient_card_ids)or
                proof['drawn']!=drawn or proof['recipe_id']!=expected.card_id or
                tuple_state(proof['rng_after'])!=rng.getstate()or proof['entity_id']!=event.target_id or
                event.target_id in seen or event.target_id not in game._state.entities or event.player_id not in(1,2)):
            raise ValueError('Potion generation lost its complete original recipe/random proof')
        seen.add(event.target_id)
    queue=()if game._frame is None else(*game._frame.prefix,*game._frame.continuation)
    pending=[x for x in queue if type(x)is ResolveComposedSpell]
    for event in(*records(game,STEP),*records(game,END)):
        record=cast_record(game._state,dict(event.data)['cast_id']);checked_recipe(game.registry,record.card_id)
    for item in pending:
        record=cast_record(game._state,item.cast_id);checked_recipe(game.registry,record.card_id)
        if not record.payload_started or record.completed or record.interrupted:
            raise ValueError('Potion continuation borrowed an inactive or unaccepted CAST')
    for record in game._state.cast_history:
        if not record.card_id.startswith(PREFIX):continue
        recipe,p=checked_recipe(game.registry,record.card_id);history=steps(game,record.id)
        ends=[x for x in records(game,END)if dict(x.data)['cast_id']==record.id]
        if len(history)>2 or len(ends)>1:raise ValueError('Potion duplicated a component or finish')
        for index,event in enumerate(history):
            if (dict(event.data)!={'cast_id':record.id,'index':index,'ingredient_card_id':recipe.parts[index]}or
                    (event.source_id,event.player_id)!=(record.source_id,record.player_id)):
                raise ValueError('Potion changed its original ordered component')
        own=[x for x in pending if x.cast_id==record.id]
        if ends:
            finish=ends[0]
            if (len(history)!=2 or own or dict(finish.data)!={'cast_id':record.id}or
                    (finish.source_id,finish.player_id)!=(record.source_id,record.player_id)or
                    finish.sequence<=history[-1].sequence):
                raise ValueError('Potion finish lost its complete original two-component body')
        elif record.completed and record.payload_started:
            raise ValueError('Completed Potion lost its complete component/finish proof')
        elif (own or history and not record.interrupted)and own!=[ResolveComposedSpell(record.id,len(history))]:
            raise ValueError('Waiting Potion lost its unique next component')
