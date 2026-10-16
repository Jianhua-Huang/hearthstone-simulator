"""Native persistent HAND mirrors over actual publicly committed minion faces."""
from dataclasses import replace
from .errors import ResolutionError
from .lifecycle import attachment_id,apply_summon_stats
from .model import AbilityInstance,CardType,HandMirrorBinding,HandMirrorSpec,SummonStats,Zone

PUBLICATIONS=frozenset(('card_committed','card_played','card_created','card_added_to_hand',
    'card_moved_to_hand','card_drawn','card_returned','stored_card_transformed'))


def source(entity):
    rows=[a for a in entity.abilities if a.kind=='hand_mirror']
    if len(rows)>1:raise ValueError('A physical hand mirror has only one original native source')
    return rows[0]if rows else None


def declaration(registry,ability):
    ability.__post_init__()
    card=registry.card(ability.hand_mirror.declaring_card_id)
    if type(card.hand_mirror)is not HandMirrorSpec or card.kind!=CardType.MINION:
        raise ValueError('Hand mirror borrowed another original printed declaration')
    card.hand_mirror.__post_init__();return card


def latest(game,player_id):
    # A prepared payment/choice is not public commitment. Completion is not
    # required: the original minion face exists before Battlecry/counter work.
    committed={dict(e.data)['play_id']for e in game._events if e.kind=='card_committed'}
    return next((p for p in reversed(game._state.play_history)if p.player_id==3-player_id
        and p.kind==CardType.MINION and p.id in committed),None)


def ensure(r,entity):
    ability=source(entity)
    if ability is not None:return ability
    if entity.card_id not in r.registry.hand_mirror_ids:return None
    card=r.registry.card(entity.card_id)
    if card.hand_mirror is None or entity.silenced:return None
    ability=AbilityInstance(attachment_id(r.state),'hand_mirror',source_id=entity.id,
        origin='printed',hand_mirror=HandMirrorBinding(card.id,entity.controller))
    entity.abilities.append(ability);return ability


def synchronize(r,event):
    if not r.registry.hand_mirror_ids or event.kind not in PUBLICATIONS or getattr(r,'_synchronizing_hand_mirrors',False):return
    target=r.state.entities.get(event.target_id)
    if target is not None and target.zone==Zone.HAND and target.kind==CardType.MINION:ensure(r,target)
    carriers=[]
    for player in r.state.players.values():
        for entity_id in tuple(player.hand):
            entity=r.state.entities[entity_id]
            if entity.kind!=CardType.MINION:continue
            ability=source(entity)
            if ability is not None:carriers.append((entity,ability))
    if not carriers:return
    from .cross_zone import reset_stored_entity,announce_stored_transform
    matches={p:latest(r.game,p)for p in {e.controller for e,_ in carriers}}
    r._synchronizing_hand_mirrors=True
    try:
        changed=[]
        for entity,ability in carriers:
            original=declaration(r.registry,ability);binding=ability.hand_mirror;play=matches[entity.controller]
            face=play.card_id if play is not None else binding.declaring_card_id
            number=play.id if play is not None else None
            if (binding.player_id,binding.play_id,entity.card_id)==(entity.controller,number,face):continue
            definition=r.registry.card(face)
            if definition.kind!=CardType.MINION or not definition.hand_playable:
                raise ResolutionError('Hand mirror requires the complete original played minion face')
            old=entity.card_id;reset_stored_entity(r,entity,definition)
            entity.abilities=[a for a in entity.abilities if a.kind!='hand_mirror']
            entity.abilities.append(replace(ability,source_id=entity.id,
                hand_mirror=HandMirrorBinding(binding.declaring_card_id,entity.controller,number)))
            apply_summon_stats(r.state,entity,SummonStats(original.hand_mirror.attack,original.hand_mirror.health))
            changed.append((entity,old))
        # Every physical mirror is fully installed before any observer captures
        # the first private transformation; no frozen context sees half a batch.
        for entity,old in changed:
            announce_stored_transform(r,entity,old,source_id=entity.id)
    finally:r._synchronizing_hand_mirrors=False


def validate_entity(state,registry,entity):
    ability=source(entity)
    if ability is None:return
    declaration(registry,ability);binding=ability.hand_mirror
    if (entity.kind!=CardType.MINION or entity.zone!=Zone.HAND or entity.silenced or
            ability.source_id!=entity.id or binding.player_id!=entity.controller):
        raise ValueError('Hand mirror lost its original physical hand source/controller')
    if binding.play_id is None:
        if entity.card_id!=binding.declaring_card_id:raise ValueError('An unbound hand mirror borrowed another face')
    else:
        if binding.play_id>len(state.play_history):raise ValueError('Hand mirror borrowed a future played face')
        play=state.play_history[binding.play_id-1]
        if play.player_id!=3-entity.controller or play.kind!=CardType.MINION or play.card_id!=entity.card_id:
            raise ValueError('Hand mirror differs from its frozen opponent minion face')


def validate_game(game):
    if not game.registry.hand_mirror_ids:return
    matches={}
    for player in game._state.players.values():
        for entity_id in player.hand:
            entity=game._state.entities[entity_id];ability=source(entity)
            if ability is None:
                if entity.card_id in game.registry.hand_mirror_ids and not entity.silenced:
                    raise ValueError('Printed hand mirror lost its conditional native source')
                continue
            if player.id not in matches:matches[player.id]=latest(game,player.id)
            play=matches[player.id];number=play.id if play is not None else None
            if ability.hand_mirror.play_id!=number:
                raise ValueError('Hand mirror is not bound to the latest actual public opponent minion play')
