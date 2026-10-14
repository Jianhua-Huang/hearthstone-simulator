"""Deterministic independent checks using upstream public game/card APIs."""
from audit import initialize, save
import random
import traceback

cards=initialize()
from hearthstone.enums import CardClass
from fireplace.player import Player
from fireplace.game import Game
from fireplace.utils import random_draft

def fresh():
    random.seed(71)
    players=[Player(str(i),random_draft(CardClass.DEATHKNIGHT),CardClass.DEATHKNIGHT.default_hero) for i in range(2)]
    game=Game(players=players)
    game.start()
    for player in players:
        player.choice.choose()
    player=game.current_player
    player.max_mana=10
    player.used_mana=0
    return game,player

results=[]
def check(name, fn):
    try:
        observed, expected=fn()
        results.append(dict(name=name,observed=observed,expected=expected,match=observed==expected))
    except Exception as exc:
        results.append(dict(name=name,error=repr(exc),traceback=traceback.format_exc()))

def blood(corpses):
    game,p=fresh()
    p.corpse=corpses
    hand=len(p.hand)
    p.give('RLK_051').play()
    return dict(health=p.hero.health,max_health=p.hero.max_health,corpses=p.corpse,hand_delta=len(p.hand)-hand),dict(health=40 if corpses>=3 else 35,max_health=40 if corpses>=3 else 35,corpses=max(0,corpses-3),hand_delta=1 if corpses>=3 else 0)

def explosion():
    game,p=fresh()
    p.corpse=3
    weak=p.opponent.summon('CORE_LOEA10_3') # Murloc Tinyfin, 1 health, no text
    strong=p.opponent.summon('CORE_CS2_182') # Chillwind Yeti, 5 health, no text
    assert weak.health == 1 and strong.health == 5
    p.give('RLK_035').play()
    return dict(weak_dead=weak.dead,strong_health=strong.health,corpses=p.corpse),dict(weak_dead=True,strong_health=2,corpses=0)

def fireball():
    game,p=fresh()
    p.give('CORE_CS2_029').play(target=p.opponent.hero)
    return p.opponent.hero.health,24

def invalid_deck():
    # Deliberately invalid constructed deck: 30 copies of the same legendary.
    players=[Player(str(i),['RLK_222']*30,CardClass.DEATHKNIGHT.default_hero) for i in range(2)]
    try:
        Game(players=players).start()
        observed='accepted'
    except Exception as exc:
        observed='rejected: '+type(exc).__name__
    return observed,'rejected by deck validation'

def cloned_resource():
    from fireplace.deepcopy import deepcopy_game
    game,p=fresh()
    p.corpse=7
    clone=deepcopy_game(game,p,0)
    return dict(original=p.corpse,clone=clone.current_player.corpse),dict(original=7,clone=7)

check('fireball_six_damage',fireball)
check('vampiric_blood_full_health_no_corpses',lambda:blood(0))
check('vampiric_blood_full_health_three_corpses',lambda:blood(3))
check('corpse_explosion_continues_after_first_death',explosion)
check('constructed_deck_validation',invalid_deck)
check('clone_preserves_deathknight_corpses',cloned_resource)
save('independent-probes.json',results)
for result in results:
    print(result)
