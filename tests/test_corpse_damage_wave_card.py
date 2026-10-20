import json
import unittest
from functools import lru_cache

from hs_sim.cards import build_registry
from hs_sim.cards.corpse_damage_wave_card import CARD, load_batch
from hs_sim.engine import (CardDefinition, CardType, Game, IllegalAction, Keyword, PlayCard,
    PlayerSetup, ResolutionError, Scenario, SelectChoice, Zone)
from hs_sim.engine.effects import ChoiceOption, Destroy, GainResource, InvokeBehavior, RequestChoice
from hs_sim.engine.model import CardClass, CardMetadata, Resource
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from tools.card_batch import check_face

P='fixture.corpse_waves.'
PLAIN, SHIELD, SD, SLEEP, LOCATION, SPAWN, CHILD, GAIN, KILLER=tuple(P+x for x in (
    'plain','shield','sd','sleep','location','spawn','child','gain','killer'))
COIN='GAME_005'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


@lru_cache(maxsize=None)
def fixture(role='writer'):
    if role not in ('writer','reader'):raise ValueError('Independent fixture registries required')
    r=build_registry()
    r.register_behavior(P+'noop',lambda c:())
    r.register_behavior(P+'spawn',lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(CHILD),),SummonCause.capture(c)),))
    def fail(c):raise ResolutionError('Explicit late corpse-wave choice failure')
    r.register_behavior(P+'fail',fail)
    def gain(c):
        return(GainResource(c.player_id,Resource.CORPSES,5),RequestChoice(c.player_id,(
            ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',
                (InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id))
    r.register_behavior(P+'gain',gain)
    def killer(c):
        target=next(i for player in(1,2)for i in c.state.players[player].board if c.state.entities[i].card_id==CARD)
        return(Destroy(target,c.source_id),)
    r.register_behavior(P+'killer',killer)
    for cid,hp,extra in ((PLAIN,10,{}),(SHIELD,10,{'keywords':(Keyword.DIVINE_SHIELD,)}),
            (SD,10,{'spell_damage':3}),(SLEEP,10,{'dormant_turns':2}),
            (SPAWN,1,{'deathrattle':P+'spawn'}),(CHILD,3,{}),(GAIN,1,{'deathrattle':P+'gain'}),
            (KILLER,1,{'deathrattle':P+'killer'})):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=hp,metadata=META,**extra))
    r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,durability=2,on_use=P+'noop',metadata=META))
    return r


class CorpseDamageWaveTests(unittest.TestCase):
    def game(self,corpses=4,board=(),enemy=(PLAIN,),mana=10):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_11',hand=(CARD,),board=board,deck=(COIN,)*8,
            mana=mana,max_mana=10,corpses=corpses),PlayerSetup('HERO_08',board=enemy,deck=(COIN,)*8,
                mana=10,max_mana=10,corpses=3)),seed=0),fixture())

    def play(self,g):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==CARD)
        g.apply(PlayCard(1,eid));return eid

    def corpses(self,g):return g.state.players[1].resources[Resource.CORPSES]

    def portable(self,g):
        saved=g.snapshot();r=fixture('reader')
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(saved)),r).snapshot(),saved)
        self.assertEqual(replay(build_replay(g),r).snapshot(),saved)
        for p in(1,2):
            visible=json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for key in ('"rng_state"','"resource_operations"','"resolution_frame"','"hand_cost_rank"'):
                self.assertNotIn(key,visible)

    def test_complete_original_face_and_two_primary_observations_keep_three_blood(self):
        d=load_batch();raw=d['cards'][0]['record'];card=fixture().card(CARD)
        self.assertEqual(len(d['official_observations']),2)
        for o in d['official_observations']:check_face(raw,o['face'],o['locale'])
        self.assertEqual((card.cost,card.attack,card.health),(4,4,4))
        self.assertEqual(card.metadata.runes.blood,3)

    def test_original_capped_spend_controls_number_of_one_point_waves(self):
        for balance in(0,1,3,4,9):
            with self.subTest(balance=balance):
                g=self.game(balance);target=g.state.players[2].board[0];source=self.play(g)
                self.assertEqual(g.state.entities[target].health,10-min(4,balance))
                self.assertEqual(self.corpses(g),max(0,balance-4))
                hits=[e for e in g.events if e.kind=='damage_dealt' and e.source_id==source]
                self.assertEqual([e.amount for e in hits],[1]*min(4,balance))
                self.assertEqual(g.state.players[1].mana,6)
        self.portable(g)

    def test_each_wave_hits_both_sides_other_minions_but_not_caster_heroes_or_inactive_objects(self):
        g=self.game(board=(PLAIN,SLEEP,LOCATION),enemy=(PLAIN,))
        own=tuple(g.state.players[1].board);enemy=g.state.players[2].board[0];source=self.play(g)
        self.assertEqual(g.state.entities[own[0]].health,6)
        self.assertEqual(g.state.entities[enemy].health,6)
        self.assertEqual(g.state.entities[own[1]].health,10)
        self.assertEqual(g.state.entities[own[2]].durability,2)
        self.assertEqual(g.state.entities[source].health,4)
        self.assertEqual([g.state.entities[g.state.players[p].hero_id].health for p in(1,2)],[30,30])

    def test_shield_absorbs_only_one_wave_and_minion_ability_ignores_spell_damage(self):
        g=self.game(board=(SD,SHIELD),enemy=(SHIELD,));own=tuple(g.state.players[1].board)
        enemy=g.state.players[2].board[0];self.play(g)
        self.assertEqual(g.state.entities[own[0]].health,6)
        self.assertEqual((g.state.entities[own[1]].health,g.state.entities[enemy].health),(7,7))
        self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[enemy].keywords)

    def test_first_wave_death_summons_new_body_that_later_waves_can_kill(self):
        g=self.game(enemy=(SPAWN,));self.play(g)
        children=[e for e in g.state.entities.values() if e.card_id==CHILD]
        self.assertEqual(len(children),1);self.assertEqual(children[0].zone,Zone.GRAVEYARD)
        self.assertFalse(g.state.players[2].board);self.portable(g)

    def test_new_corpses_and_choice_after_first_wave_do_not_enlarge_original_plan(self):
        g=self.game(board=(GAIN,));target=g.state.players[2].board[0];self.play(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertGreaterEqual(self.corpses(g),5)
        self.assertEqual(g.state.entities[target].health,9);self.portable(g)
        c=g.state.pending_choice;g.apply(SelectChoice(1,c.id,('continue',)))
        self.assertEqual(g.state.entities[target].health,6)
        self.assertGreaterEqual(self.corpses(g),5);self.portable(g)

    def test_late_choice_failure_keeps_original_waiting_payment_and_wave_position(self):
        g=self.game(board=(GAIN,));target=g.state.players[2].board[0];self.play(g);saved=g.snapshot()
        c=g.state.pending_choice
        with self.assertRaisesRegex(ResolutionError,'Explicit late corpse-wave'):
            g.apply(SelectChoice(1,c.id,('fail',)))
        self.assertEqual(g.snapshot(),saved)
        g.apply(SelectChoice(1,c.id,('continue',)));self.assertEqual(g.state.entities[target].health,6)

    def test_original_accepted_waves_continue_after_caster_dies_in_first_death_reaction(self):
        g=self.game(enemy=(KILLER,PLAIN));target=g.state.players[2].board[-1];source=self.play(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[target].health,6);self.portable(g)

    def test_no_other_minions_still_spends_original_cap_and_zero_has_no_randomness(self):
        g=self.game(9,enemy=());self.play(g);self.assertEqual(self.corpses(g),5)
        g=self.game(0);rng=g.snapshot()['rng_state'];self.play(g)
        self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_illegal_hand_payment_does_not_spend_corpses_or_damage_anything(self):
        g=self.game(4,mana=3);saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g)
        self.assertEqual(g.snapshot(),saved)
