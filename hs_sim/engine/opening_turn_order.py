"""Original-deck second-player declarations before any opening hand is dealt."""
import json
import random

EVENT='opening_turn_order_decided'


def qualifiers(setup,registry):
    return tuple(p for p,d in enumerate(setup.decks,1)if any(cid in registry.second_player_cards for cid in d.cards))


def fixed_first(setup,registry):
    qualified=qualifiers(setup,registry)
    return 3-qualified[0]if len(qualified)==1 else setup.first_player


def choose(game):
    setup=game._match_setup;qualified=qualifiers(setup,game.registry);before=game._rng.getstate()
    fixed=fixed_first(setup,game.registry)
    first=game._rng.choice((1,2))if fixed is None else fixed
    if not qualified:return first,None
    return first,dict(declared_cards=sorted(game.registry.second_player_cards),
        original_decks=[list(d.cards)for d in setup.decks],qualified_players=list(qualified),
        requested_first=setup.first_player,first_player=first,
        mode='forced'if len(qualified)==1 else'fixed'if fixed is not None else'random',
        rng_before=before,rng_after=game._rng.getstate())


def publish(r,proof):
    if proof is not None:r.emit(EVENT,player_id=r.state.opening.first_player,
        proof=json.dumps(proof,sort_keys=True,separators=(',',':')),_capture=False)


def validate_boundary(game):
    from .hero_health_history import effective_events
    events=[e for e in effective_events(game._events)if e.kind==EVENT]
    setup=game._match_setup
    if setup is None:
        if events:raise ValueError('Original-deck turn order requires a real match setup')
        return
    qualified=qualifiers(setup,game.registry)
    if not qualified:
        if events:raise ValueError('Undeclared turn-order decision')
        return
    if len(events)!=1 or game._state.opening is None:raise ValueError('Opening lost its unique original turn-order decision')
    event=events[0];data=dict(event.data)
    if set(data)!={'proof'}:raise ValueError('Opening decision lost its exact original proof')
    proof=json.loads(data['proof'])
    if (set(proof)!={'declared_cards','original_decks','qualified_players','requested_first','first_player','mode','rng_before','rng_after'}or
            proof['declared_cards']!=sorted(game.registry.second_player_cards)or
            proof['original_decks']!=[list(d.cards)for d in setup.decks]or proof['qualified_players']!=list(qualified)or
            proof['requested_first']!=setup.first_player or type(proof['first_player'])is not int or
            any(type(p)is not int for p in proof['qualified_players'])):
        raise ValueError('Opening decision changed its complete original deck qualification')
    rng=random.Random();before=proof['rng_before'];rng.setstate((before[0],tuple(before[1]),before[2]))
    fixed=fixed_first(setup,game.registry);first=rng.choice((1,2))if fixed is None else fixed
    after=proof['rng_after']
    if (proof['first_player']!=first or game._state.opening.first_player!=first or event.player_id!=first or
            proof['mode']!=('forced'if len(qualified)==1 else'fixed'if fixed is not None else'random')or
            (after[0],tuple(after[1]),after[2])!=rng.getstate()or event.action!=0):
        raise ValueError('Opening decision changed its actual first player or random transition')
    created=[e for e in effective_events(game._events)if e.kind=='game_created']
    if len(created)!=1 or created[0].sequence<=event.sequence or created[0].player_id!=first:
        raise ValueError('Turn-order decision must precede genuine opening creation and dealing')
