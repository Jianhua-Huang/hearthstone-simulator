"""Permanent named-minion boons use ordinary independent player programs."""
from dataclasses import asdict,dataclass
import json

from .lifecycle import attachment_id,refresh_entity
from .model import AbilityInstance,CardType,Keyword,PlayerEffectSpec,Zone

ACCEPTED='named_minion_boon_accepted'
LIVE=(Zone.HAND,Zone.DECK,Zone.PLAY,Zone.BOARD)
ORDER=(Keyword.TAUNT,Keyword.LIFESTEAL,Keyword.RUSH)


@dataclass(frozen=True)
class NamedBoon:
    program_id:str
    card_id:str
    keyword:Keyword


@dataclass(frozen=True)
class NamedMinionBoonsProfile:
    recipient_card_id:str
    battlecry_card_id:str
    spell_card_id:str
    boons:tuple[NamedBoon,...]
    initial_cost:int=4
    cost_increment:int=2


def validate_profile(registry,profile):
    if type(profile)is not NamedMinionBoonsProfile:raise ValueError('Typed named-minion boon declaration required')
    if (type(profile.boons)is not tuple or len(profile.boons)!=3 or
            any(type(x)is not NamedBoon for x in profile.boons)or tuple(x.keyword for x in profile.boons)!=ORDER or
            len({x.program_id for x in profile.boons})!=3 or len({x.card_id for x in profile.boons})!=3 or
            type(profile.initial_cost)is not int or profile.initial_cost<0 or type(profile.cost_increment)is not int or profile.cost_increment<1):
        raise ValueError('Named boons require their three independent keywords and positive cost progression')
    recipient=registry.card(profile.recipient_card_id);root=registry.card(profile.battlecry_card_id);spell=registry.card(profile.spell_card_id)
    if (recipient.kind!=CardType.MINION or recipient.deathrattle is None or root.kind!=CardType.MINION or root.battlecry is None or
            spell.kind!=CardType.SPELL or spell.on_play is None):raise ValueError('Named boons require their actual recipient, Battlecry and spell')
    for boon in profile.boons:
        card=registry.card(boon.card_id)
        if (not card.choice_only or card.kind!=CardType.SPELL or
                registry.player_effect(boon.program_id)!=PlayerEffectSpec(boon.program_id,profile.recipient_card_id)):
            raise ValueError('Named boon requires its exact choice face and independent permanent program')


def is_program(registry,spec_id):return spec_id in registry.named_minion_boon_programs


def material(state,registry,player_id,recipient_card_id):
    profile=registry.named_minion_boon_profiles[recipient_card_id]
    rows=[(e,registry.named_minion_boon_programs[e.spec_id][1])for e in state.players[player_id].player_effects
        if e.spec_id in registry.named_minion_boon_programs and
        registry.named_minion_boon_programs[e.spec_id][0].recipient_card_id==recipient_card_id]
    keywords=tuple(k for k in ORDER if any(b.keyword==k for _,b in rows))
    return profile.initial_cost+profile.cost_increment*len(rows),keywords,rows


def apply_to_entity(state,registry,entity):
    if (entity.card_id not in registry.named_minion_boon_profiles or entity.kind!=CardType.MINION or
            entity.zone not in LIVE or entity.starship_building):return
    _,keywords,rows=material(state,registry,entity.controller,entity.card_id)
    for keyword in keywords:
        # The keyword is permanent on Bwonsamdi; a current copy or stolen body
        # keeps its physical material. Its death producer reads its controller.
        if any(a.kind=='keyword'and a.keyword==keyword and not a.remove_on_silence for a in entity.abilities):continue
        instance=next(e for e,b in rows if b.keyword==keyword)
        entity.abilities.append(AbilityInstance(attachment_id(state),'keyword',keyword=keyword,
            source_id=instance.source_id,remove_on_silence=False))
    refresh_entity(entity)


def synchronize(state,registry):
    if not registry.named_minion_boon_profiles or not any(
            is_program(registry,e.spec_id)for p in state.players.values()for e in p.player_effects):return
    for entity in state.entities.values():apply_to_entity(state,registry,entity)


def install(r,player_id,instance):
    binding=r.registry.named_minion_boon_programs.get(instance.spec_id)
    if binding is None:return
    profile,boon=binding
    from .battlecries import active_battlecry
    from .spell_casts import active_cast
    battlecry=active_battlecry(r.state,instance.source_id,player_id)
    cast=active_cast(r.state,instance.source_id,player_id)
    if battlecry is not None and battlecry.payload.card_id==profile.battlecry_card_id and battlecry.payload_started:
        kind,identity='battlecry',battlecry.id
    elif cast is not None and cast.card_id==profile.spell_card_id and cast.payload_started:
        kind,identity='cast',cast.id
    else:raise ValueError('Named boon requires its actual original Battlecry or spell window')
    previous={e.id:{a.id for a in e.abilities}for e in r.state.entities.values()
        if e.controller==player_id and e.card_id==profile.recipient_card_id and e.zone in LIVE}
    synchronize(r.state,r.registry)
    r.emit(ACCEPTED,source_id=instance.source_id,player_id=player_id,recipient=profile.recipient_card_id,
        origin_kind=kind,origin_id=identity,keyword=boon.keyword.value,
        instance_json=json.dumps(asdict(instance),sort_keys=True,separators=(',',':')),_capture=False)
    for eid,old in previous.items():
        entity=r.state.entities[eid]
        for ability in entity.abilities:
            if ability.id not in old and ability.kind=='keyword':
                r.emit('keyword_granted',source_id=instance.source_id,target_id=eid,player_id=player_id,
                    keyword=ability.keyword.value,attachment_id=ability.id)


def public_cost(state,registry,entity):
    if entity.card_id not in registry.named_minion_boon_profiles:return None
    return material(state,registry,entity.controller,entity.card_id)[0]


def validate_game(game):
    registry=game.registry
    if not registry.named_minion_boon_profiles:return
    from .hero_health_history import effective_events
    accepted={}
    for event in effective_events(game._events):
        if event.kind!=ACCEPTED:continue
        d=dict(event.data)
        if set(d)!={'recipient','origin_kind','origin_id','keyword','instance_json'}:raise ValueError('Named boon lost its complete acceptance')
        raw=json.loads(d['instance_json']);binding=registry.named_minion_boon_programs.get(raw.get('spec_id'))
        if binding is None:raise ValueError('Named boon borrowed an undeclared program')
        profile,boon=binding
        if (d['recipient']!=profile.recipient_card_id or d['keyword']!=boon.keyword.value or
                raw.get('source_id')!=event.source_id or type(raw.get('id'))is not int or raw['id']in accepted or
                type(d['origin_id'])is not int or d['origin_id']<1):raise ValueError('Named boon changed its original allocation')
        if d['origin_kind']=='battlecry':
            from .battlecries import battlecry_record
            record=battlecry_record(game._state,d['origin_id']);card=record.payload.card_id
            started=record.payload_started;expected=profile.battlecry_card_id
        elif d['origin_kind']=='cast':
            from .spell_casts import cast_record
            record=cast_record(game._state,d['origin_id']);card=record.card_id
            started=record.payload_started;expected=profile.spell_card_id
        else:raise ValueError('Unknown named-boon original window')
        if (not started or record.source_id!=event.source_id or record.player_id!=event.player_id or card!=expected or
                raw.get('created_turn')!=record.turn):raise ValueError('Named boon lost its genuine original actor/window')
        accepted[raw['id']]=(event.player_id,raw)
    active={}
    for player in game._state.players.values():
        for instance in player.player_effects:
            if not is_program(registry,instance.spec_id):continue
            raw=json.loads(json.dumps(asdict(instance)))
            if accepted.get(instance.id)!=(player.id,raw):raise ValueError('Named boon lost its complete installed program')
            active[instance.id]=(player.id,raw)
    if active!=accepted:raise ValueError('Permanent named boon program was cropped or retired')
    for entity in game._state.entities.values():
        if (entity.card_id not in registry.named_minion_boon_profiles or entity.kind!=CardType.MINION or
                entity.zone not in LIVE or entity.starship_building):continue
        _,keywords,_=material(game._state,registry,entity.controller,entity.card_id)
        if any(not any(a.kind=='keyword'and a.keyword==keyword and not a.remove_on_silence and not a.consumed
                for a in entity.abilities)for keyword in keywords):
            raise ValueError('Named minion lost its original permanent boon material')
