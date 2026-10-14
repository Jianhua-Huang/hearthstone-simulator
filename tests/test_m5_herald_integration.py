"""Cross-family Herald release gates; fixtures exercise public effects only."""
import json
import unittest

from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType, CostSpec,
    EndTurn, Game, GenerationContext, Herald, Keyword, PaymentType, PlayCard, PlayerSetup,
    ResolutionError, Scenario, SelectChoice, Zone, LoseHealth)
from hs_sim.engine.effects import (AddCostModifier, ChoiceOption, Damage, DamageBatch, Destroy,
    InvokeBehavior, ReplaceHero, RequestChoice, Silence, Summon)
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.secrets import SetSecret


class HeraldIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.r=build_registry()
        self.r.register_card(CardDefinition('plain','Plain',CardType.MINION,attack=2,health=8))
        for cls in (CardClass.WARRIOR,CardClass.DEMON_HUNTER,CardClass.SHAMAN,
                    CardClass.ROGUE,CardClass.DEATH_KNIGHT,CardClass.WARLOCK):
            self.r.register_card(CardDefinition(cls.value,cls.value,CardType.HERO,health=30,
                metadata=CardMetadata(False,(cls,),None)))
        self.spell('convert',lambda c:[AddCostModifier(1,CostSpec(payment=PaymentType.HEALTH),1)])
        self.r.register_behavior('clear',lambda c:[Destroy(i) for i in c.state.players[1].board])
        self.spell('prepare',lambda c:[*[Herald(1,c.source_id) for _ in range(4)],InvokeBehavior('clear',c.source_id,1)])

    def spell(self,name,fn,cls=CardClass.WARRIOR,**kw):
        self.r.register_behavior(name,fn)
        self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,
            metadata=CardMetadata(False,(cls,),None),**kw))

    def game(self,hand=(),board=(),hero='HERO_01',enemy=(),weapon=None):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero,hand=hand,board=board,deck=('plain',)*12,mana=10,max_mana=10,weapon_card_id=weapon),
            PlayerSetup('HERO_08',board=enemy,deck=('plain',)*12,mana=10,max_mana=10)),seed=173,
            generation_context=GenerationContext('local-2026-09-23','experimental')),self.r)

    def play(self,g,name,target=None):
        p=g.state.active_player
        i=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==name)
        g.apply(PlayCard(p,i,target));return i

    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def events(self,g,kind):return [e for e in g.events if e.kind==kind]
    def choose(self,g,option='a'):
        choice=g.state.pending_choice;g.apply(SelectChoice(choice.player_id,choice.id,(option,)))
    def check(self,g):
        s=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(s,self.r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),s)

    def test_all_six_colossal_bodies_capture_rank_for_both_limbs(self):
        for body in ('CATA_150','CATA_151','CATA_153','CATA_154','CATA_155','CATA_726'):
            with self.subTest(body=body):
                g=self.game(hand=('prepare',body),board=('plain',)*7)
                self.play(g,'prepare');self.play(g,body)
                record=g.state.colossal_history[-1]
                self.assertTrue(record.completed);self.assertFalse(record.canceled)
                self.assertEqual(len(g.state.herald_history),4)
                self.assertEqual([g.state.entities[i].herald_rank for i in record.limbs],[2,2])
                self.assertTrue(all(g.state.entities[i].attack>=4 for i in record.limbs))
                self.check(g)

    def test_class_changes_keep_player_count_and_select_current_soldier(self):
        classes=(CardClass.WARRIOR,CardClass.DEMON_HUNTER,CardClass.SHAMAN,
                 CardClass.ROGUE,CardClass.DEATH_KNIGHT,CardClass.WARLOCK)
        for n,cls in enumerate(classes):
            self.spell('step'+str(n),lambda c,cls=cls:[ReplaceHero(1,cls.value),Herald(1,c.source_id)])
        g=self.game(hand=tuple('step'+str(n) for n in range(6)))
        for n in range(6):self.play(g,'step'+str(n))
        records=g.state.herald_history
        self.assertEqual([r.hero_class for r in records],list(classes))
        self.assertEqual([r.rank for r in records],[0,0,1,1,2,2]);self.check(g)

    def test_sinestra_repeats_real_herald_spell_and_advances_each_payload(self):
        g=self.game(hero='rogue',board=('CATA_154',),hand=('CATA_530','CATA_530'))
        self.play(g,'CATA_530');self.play(g,'CATA_530')
        self.assertEqual([r.rank for r in g.state.herald_history],[0,0,1,1])
        self.assertEqual(len(g.state.play_history),2)
        self.assertEqual(len(self.events(g,'card_played')),2)
        self.assertEqual([r.completed for r in g.state.spell_repeats],[2,2])
        self.assertEqual(len([e for e in self.events(g,'card_added_to_hand')]),4)
        self.assertIn(Keyword.LIFESTEAL,self.hero(g).keywords);self.check(g)

    def test_full_field_repeated_herald_counts_without_soldier_or_generation(self):
        g=self.game(hero='rogue',board=('CATA_154',)+('plain',)*6,hand=('CATA_530',))
        self.play(g,'CATA_530')
        self.assertEqual(len(g.state.herald_history),2)
        self.assertTrue(all(r.soldier_id is None for r in g.state.herald_history))
        self.assertFalse(self.events(g,'card_added_to_hand'));self.check(g)

    def test_health_payment_and_repeated_self_damage_replace_at_distinct_steps(self):
        g=self.game(board=('CATA_155','CATA_154'),hand=('convert','CS2_029'))
        self.play(g,'convert');self.play(g,'CS2_029',self.hero(g).id)
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(46,46))
        self.assertEqual([e.amount for e in self.events(g,'health_spent')],[4])
        self.assertEqual([e.amount for e in self.events(g,'health_loss_replaced')],[4,6,6])
        self.assertEqual(len(g.state.spell_repeats),1);self.check(g)

    def test_counterspell_keeps_replaced_payment_but_prevents_repetitions(self):
        self.spell('setup',lambda c:[SetSecret(2,'EX1_287'),AddCostModifier(1,CostSpec(payment=PaymentType.HEALTH),1)])
        g=self.game(board=('CATA_155','CATA_154'),hand=('setup','CS2_029'))
        self.play(g,'setup');self.play(g,'CS2_029',self.hero(g).id)
        self.assertEqual(self.hero(g).health,34);self.assertFalse(g.state.spell_repeats)
        self.assertEqual(len(self.events(g,'spell_countered')),1);self.assertFalse(self.events(g,'damage_dealt'))
        self.check(g)

    def test_dying_onyxia_is_not_eligible_for_next_repeated_batch(self):
        self.spell('sweep',lambda c:[DamageBatch((Damage(c.state.players[1].board[0],6,c.source_id),
            Damage(c.state.players[1].hero_id,3,c.source_id)))],cls=CardClass.MAGE)
        g=self.game(board=('CATA_155','CATA_154'),hand=('sweep',));self.play(g,'sweep')
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(30,33))
        self.assertEqual(len(self.events(g,'health_loss_replaced')),1)
        self.assertEqual(len(g.state.death_history),1);self.check(g)

    def test_repeated_choice_loss_restores_between_iterations(self):
        self.spell('ask',lambda c:[RequestChoice(1,(ChoiceOption('a','Pay life',
            (LoseHealth(c.state.players[1].hero_id,5,c.source_id),)),),c.source_id)],cls=CardClass.MAGE)
        g=self.game(board=('CATA_155','CATA_154'),hand=('ask',));self.play(g,'ask');self.choose(g)
        self.assertEqual(self.hero(g).health,35);self.assertIsNotNone(g.state.pending_choice);self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.hero(g).health,40);self.check(g)

    def test_windfury_hero_combat_and_onyxia_growth_share_weapon_lifecycle(self):
        g=self.game(board=('CATA_151','CATA_155'),enemy=('plain',),weapon='CS2_106')
        target=g.state.players[2].board[0]
        for _ in range(2):g.apply(Attack(1,self.hero(g).id,target))
        self.assertEqual(self.hero(g).health,34);self.assertIsNone(g.state.players[1].weapon_id)
        self.assertEqual(self.hero(g).attacks_this_turn,2);self.check(g)

    def test_deathwing_hero_card_preserves_max_health_gain_before_choice(self):
        g=self.game(board=('CATA_155',),hand=('convert','CATA_190h'))
        self.play(g,'convert');self.play(g,'CATA_190h');self.check(g)
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(40,40))
        self.assertEqual(self.hero(g).armor,12)
        self.choose(g,'CATA_190t10');self.assertEqual(self.hero(g).max_health,40);self.check(g)

    def test_second_repeat_failure_rolls_back_payment_growth_and_rng(self):
        self.spell('bad',lambda c:[Herald(1,c.source_id),
            *([LoseHealth(c.state.players[1].hero_id,1,999999)] if c.state.herald_history else [])],
            cls=CardClass.MAGE,cost=4)
        g=self.game(hero='rogue',board=('CATA_155','CATA_154'),hand=('convert','bad'))
        # Conversion is a Warrior spell and repeats; the same final cost quote still pays once.
        self.play(g,'convert');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)

    def test_deck_sacrifice_replacement_does_not_build_friendly_starship(self):
        from hs_sim.engine.starships import construction
        g=self.game(board=('CATA_725t','GDB_100','CATA_726'))
        piece=g.state.players[1].board[1];g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[piece].zone,Zone.BOARD)
        self.assertIsNone(construction(g.state,1));self.assertEqual(len(self.events(g,'card_destroyed_in_deck')),1)
        self.assertFalse(g.state.death_history);self.check(g)


if __name__=='__main__':unittest.main()
