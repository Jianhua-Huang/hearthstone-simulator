"""Real fixed shuffles, original drawn bodies and shared next-turn prices."""
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.fixed_shuffle_followup_cards import load_batch,IMP,NINJA,PREFIX
from hs_sim.engine import CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,TriggerSpec,Zone
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import AddToHand,ChoiceOption,Draw,GainArmor,InvokeBehavior,RequestChoice,Summon
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest

HARSH='CAP_404';INTERROGATION='TLC_518';YETI='CORE_CS2_182'


def registry(wait=False,fault=False):
    r=build_registry()
    scripts=dict(draw=lambda c:(Draw(c.player_id,source_id=c.source_id),),
        full_draw=lambda c:(AddToHand(c.player_id,YETI,c.source_id),Draw(c.player_id,source_id=c.source_id)),
        draw_other=lambda c:(Draw(3-c.player_id,source_id=c.source_id),),
        generate=lambda c:(AddToHand(c.player_id,NINJA,c.source_id),),
        summon=lambda c:(Summon(c.player_id,NINJA),))
    for name,body in scripts.items():
        r.register_behavior('k66.'+name,body)
        r.register_card(CardDefinition('k66.'+name,name,CardType.SPELL,on_play='k66.'+name))
    def fail(c):raise ResolutionError('Intentional fixed shuffle continuation fault')
    r.register_behavior('k66.fail',fail)
    def watch(c):
        if c.event.kind=='card_added_to_deck':
            if fault and c.state.entities[c.event.target_id].card_id in(IMP,NINJA):
                return(InvokeBehavior('k66.fail',c.source_id,c.player_id),)
            return()
        if(not wait or c.state.entities[c.event.target_id].card_id!=NINJA or
                sum(x.card_id==NINJA for x in c.state.successful_summon_history)!=1):return()
        return(RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',(GainArmor(c.state.players[c.player_id].hero_id,1),)),
            ChoiceOption('bad','Fail',(InvokeBehavior('k66.fail',c.source_id,c.player_id),))),source_id=c.source_id),)
    r.register_behavior('k66.watch',watch)
    r.register_card(CardDefinition('k66.watch','Watcher',CardType.MINION,health=8,
        triggers=(TriggerSpec('minion_summoned','k66.watch'),TriggerSpec('card_added_to_deck','k66.watch'))))
    return r


class FixedShuffleFollowupCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),deck=(YETI,)*8,board=(),enemy_hand=(),enemy_deck=(YETI,)*8,enemy=(),r=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,deck=deck,board=board,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',hand=enemy_hand,deck=enemy_deck,board=enemy,mana=30,max_mana=30,mana_cap=30)),seed=1066),r or self.r)
    def ids(self,g,cid,p=1,zone='hand'):
        s=g.state;return[i for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid]
    def names(self,g,p=1,zone='hand'):
        s=g.state;return[s.entities[i].card_id for i in getattr(s.players[p],zone)]
    def play(self,g,cid,p=1):
        eid=self.ids(g,cid,p)[0];g.apply(PlayCard(p,eid));return eid
    def price(self,g,cid,p=1):return quote_cost(g.state,g.registry,g.state.entities[self.ids(g,cid,p)[0]]).amount
    def portable(self,g,wait=False,fault=False):
        saved=g.snapshot();self.assertEqual(Game.from_snapshot(saved,registry(wait,fault)).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry(wait,fault)).snapshot(),saved)
    def test_complete_fixed_faces_and_actual_child_identity(self):
        d=load_batch();self.assertEqual([x['record']['id']for x in d['cards']],[HARSH,INTERROGATION,NINJA])
        for row in d['cards']:
            raw=row['record'];card=self.r.card(raw['id'])
            self.assertEqual(canonical_digest(raw),row['record_sha256'])
            self.assertEqual((card.cost,card.attack,card.health),(raw['cost'],raw['attack']or 0,raw['health']or 0))
            self.assertIsNone(card.spell_school)
        self.assertEqual(d['gallery_links'][1]['child_ids'],[119563])
        self.assertEqual(self.r.card(NINJA).metadata.tribes,())
        self.assertIn(Keyword.STEALTH,self.r.card(NINJA).keywords)
        self.assertEqual(self.r.card(NINJA).hand_progress.on_complete,'cards.recruits.draw_drawer')
    def test_harsh_pays_two_and_inserts_two_exact_imps_into_opponent_deck(self):
        g=self.game((HARSH,));own=tuple(g.state.players[1].deck);old=set(g.state.players[2].deck)
        source=self.play(g,HARSH)
        self.assertEqual(g.state.players[1].mana,28);self.assertEqual(tuple(g.state.players[1].deck),own)
        added=set(g.state.players[2].deck)-old;self.assertEqual(len(added),2)
        self.assertTrue(all(g.state.entities[i].card_id==IMP for i in added))
        self.assertEqual(len(g.state.players[2].player_effects),1)
        pending=g.state.players[2].player_effects[0]
        self.assertEqual((pending.spec_id,pending.source_id,pending.source_card_id),(PREFIX+'pending_harsh',source,HARSH))
        self.portable(g)
    def test_two_imp_insertions_form_one_semantic_opponent_shuffle(self):
        g=self.game((HARSH,));source=self.play(g,HARSH);rows=g.state.deck_shuffle_history
        self.assertEqual(len(rows),1)
        self.assertEqual((rows[0].actor_id,rows[0].player_id,rows[0].declared_count,rows[0].source.entity_id),(1,2,2,source))
    def test_harsh_tax_waits_for_actual_opponent_start_and_expires_at_their_end(self):
        g=self.game((HARSH,),enemy_hand=(YETI,));self.play(g,HARSH)
        self.assertEqual(self.price(g,YETI,2),4)
        g.apply(EndTurn(1));self.assertEqual(self.price(g,YETI,2),6)
        self.assertFalse(g.state.players[2].player_effects)
        before=g.state.players[2].mana;self.play(g,YETI,2);self.assertEqual(g.state.players[2].mana,before-6)
        g.apply(EndTurn(2));self.assertFalse(g.state.players[2].cost_modifiers);self.portable(g)
    def test_harsh_only_taxes_minions_and_preserves_other_pending_tax_sources(self):
        g=self.game((HARSH,'TIME_716'),enemy_hand=(YETI,'WW_001t'))
        self.play(g,HARSH);self.play(g,'TIME_716');g.apply(EndTurn(1))
        self.assertEqual(self.price(g,YETI,2),7);self.assertEqual(self.price(g,'WW_001t',2),2)
        self.assertEqual(len(g.state.players[2].cost_modifiers),2);self.portable(g)
    def test_harsh_uses_original_source_after_spell_retires(self):
        g=self.game((HARSH,),enemy_hand=(YETI,));source=self.play(g,HARSH)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        g.apply(EndTurn(1));self.assertEqual(self.price(g,YETI,2),6)
        self.assertEqual(g.state.players[2].cost_modifiers[0].source_id,source)
    def test_repeated_harsh_casts_stack_prices_and_keep_two_shuffle_operations(self):
        g=self.game((HARSH,HARSH),enemy_hand=(YETI,));self.play(g,HARSH);self.play(g,HARSH)
        self.assertEqual(len(g.state.deck_shuffle_history),2)
        self.assertEqual(len(self.ids(g,IMP,2,'deck')),4)
        g.apply(EndTurn(1));self.assertEqual(self.price(g,YETI,2),8);self.portable(g)
    def test_opponent_drawn_imps_use_original_physical_bodies_and_replace_for_drawer(self):
        g=self.game((HARSH,),enemy_hand=(YETI,),enemy_deck=())
        self.play(g,HARSH);original=set(g.state.players[2].deck);g.apply(EndTurn(1))
        self.assertEqual(set(self.ids(g,IMP,1,'board')),original)
        self.assertTrue(all(Keyword.LIFESTEAL in g.state.entities[i].keywords for i in original))
        self.assertEqual(self.names(g,2),[YETI]);self.assertFalse(g.state.players[2].deck)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,29)
        self.assertEqual(len(g.state.draw_history),3);self.assertEqual(self.price(g,YETI,2),6);self.portable(g)
    def test_interrogation_pays_two_and_shuffles_three_exact_ninjas_once(self):
        g=self.game((INTERROGATION,));original=set(g.state.players[1].deck);source=self.play(g,INTERROGATION)
        added=set(g.state.players[1].deck)-original;self.assertEqual(len(added),3)
        self.assertTrue(all(g.state.entities[i].card_id==NINJA for i in added))
        self.assertEqual(g.state.players[1].mana,28)
        row=g.state.deck_shuffle_history[0]
        self.assertEqual((row.actor_id,row.player_id,row.declared_count,row.source.entity_id),(1,1,3,source));self.portable(g)
    def test_ninja_draw_chain_summons_originals_and_replaces_until_ordinary_card(self):
        g=self.game(('k66.draw',),deck=(NINJA,NINJA,YETI))
        originals=tuple(g.state.players[1].deck[:2]);self.play(g,'k66.draw')
        self.assertEqual(tuple(self.ids(g,NINJA,zone='board')),originals)
        self.assertEqual(self.names(g),[YETI]);self.assertFalse(g.state.players[1].deck)
        self.assertEqual(len(g.state.draw_history),3);self.assertEqual(len(g.state.play_history),1)
        self.assertFalse(g.state.cast_history[0].interrupted)
        for i in originals:
            self.assertIn(Keyword.STEALTH,g.state.entities[i].keywords)
            self.assertEqual((g.state.entities[i].attack,g.state.entities[i].health),(3,3))
        self.portable(g)
    def test_ninja_manual_hand_play_is_ordinary_three_mana_without_replacement_draw(self):
        g=self.game((NINJA,));original=tuple(g.state.players[1].deck);eid=self.play(g,NINJA)
        self.assertEqual(g.state.players[1].mana,27);self.assertEqual(tuple(g.state.players[1].deck),original)
        self.assertFalse(g.state.draw_history);self.assertIn(Keyword.STEALTH,g.state.entities[eid].keywords);self.portable(g)
    def test_generating_ninja_to_hand_does_not_fabricate_a_draw_or_summon(self):
        g=self.game(('k66.generate',));self.play(g,'k66.generate')
        self.assertEqual(self.names(g),[NINJA]);self.assertFalse(g.state.successful_summon_history)
        self.assertFalse(g.state.draw_history)
    def test_effect_summoned_ninja_does_not_replace_a_nonexistent_draw(self):
        g=self.game(('k66.summon',));deck=tuple(g.state.players[1].deck);self.play(g,'k66.summon')
        self.assertEqual(len(self.ids(g,NINJA,zone='board')),1);self.assertEqual(tuple(g.state.players[1].deck),deck)
        self.assertFalse(g.state.draw_history)
    def test_full_board_keeps_revealed_ninja_in_hand_and_draws_replacement(self):
        g=self.game(('k66.draw',),deck=(NINJA,YETI),board=(YETI,)*7);original=g.state.players[1].deck[0]
        self.play(g,'k66.draw');self.assertEqual(self.names(g),[NINJA,YETI])
        self.assertEqual(self.ids(g,NINJA),[original]);self.assertEqual(len(g.state.players[1].board),7)
        self.assertFalse(g.state.successful_summon_history);self.assertEqual(len(g.state.draw_history),2);self.portable(g)
    def test_full_hand_burns_ninja_without_successful_hand_draw_replacement(self):
        g=self.game(('k66.full_draw',)+(YETI,)*9,deck=(NINJA,YETI));original=g.state.players[1].deck[0]
        self.play(g,'k66.full_draw');self.assertEqual(g.state.entities[original].zone,Zone.GRAVEYARD)
        self.assertEqual(self.names(g,zone='deck'),[YETI]);self.assertFalse(g.state.successful_summon_history)
        self.assertEqual(len(g.state.draw_history),1);self.portable(g)
    def test_effect_draw_for_other_player_summons_for_actual_drawer(self):
        g=self.game(('k66.draw_other',),enemy_deck=(NINJA,YETI));original=g.state.players[2].deck[0]
        self.play(g,'k66.draw_other')
        self.assertEqual(self.ids(g,NINJA,2,'board'),[original]);self.assertFalse(g.state.players[1].board)
        self.assertEqual(self.names(g,2),[YETI]);self.portable(g)
    def test_last_ninja_summons_then_replacement_draw_reaches_fatigue(self):
        g=self.game(('k66.draw',),deck=(NINJA,));self.play(g,'k66.draw')
        self.assertEqual(len(self.ids(g,NINJA,zone='board')),1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,29)
        self.assertEqual(len(g.state.draw_history),2);self.portable(g)
    def test_actual_draw_summon_waiting_restores_without_redraw_or_duplicate_body(self):
        r=registry(wait=True);g=self.game(('k66.draw',),deck=(NINJA,YETI),board=('k66.watch',),r=r)
        original=g.state.players[1].deck[0];self.play(g,'k66.draw');self.assertIsNotNone(g.state.pending_choice)
        self.portable(g,wait=True);saved=g.snapshot();q=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(q.player_id,q.id,('bad',)))
        self.assertEqual(g.snapshot(),saved);g.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertEqual(self.ids(g,NINJA,zone='board'),[original]);self.assertEqual(self.names(g),[YETI])
        self.assertEqual(len(g.state.draw_history),2);self.portable(g,wait=True)
    def test_after_shuffle_fault_rolls_back_payment_pending_tax_deck_and_rng(self):
        for cid in(HARSH,INTERROGATION):
            with self.subTest(card=cid):
                g=self.game((cid,),board=('k66.watch',),r=registry(fault=True));saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,cid)
                self.assertEqual(g.snapshot(),saved);self.assertFalse(g.state.deck_shuffle_history)
    def test_same_seed_and_full_replay_reproduce_both_shuffles(self):
        games=[self.game((HARSH,INTERROGATION))for _ in range(2)]
        for g in games:self.play(g,HARSH);self.play(g,INTERROGATION)
        self.assertEqual(games[0].snapshot(),games[1].snapshot());self.portable(games[0])
    def test_real_shuffle_count_cost_uses_one_own_operation_not_three_insertions(self):
        g=self.game((HARSH,INTERROGATION,'TLC_520'))
        self.assertEqual(self.price(g,'TLC_520'),6);self.play(g,HARSH)
        self.assertEqual(self.price(g,'TLC_520'),6);self.play(g,INTERROGATION)
        self.assertEqual(self.price(g,'TLC_520'),5);self.portable(g)
    def test_player_queries_do_not_change_rng_price_or_pending_effect(self):
        g=self.game((HARSH,INTERROGATION),enemy_hand=(YETI,));self.play(g,HARSH);saved=g.snapshot()
        for _ in range(2):g.observe(1);g.observe(2);g.legal_actions();self.price(g,YETI,2)
        self.assertEqual(g.snapshot(),saved)
    def test_public_observation_does_not_publish_hidden_insertions_or_deck_order(self):
        g=self.game((HARSH,INTERROGATION));self.play(g,HARSH);self.play(g,INTERROGATION)
        for viewer in(1,2):
            view=g.observe(viewer)
            self.assertNotIn('deck_shuffle_history',view)
            for player in view['players']:
                self.assertNotIn('deck',player)
                self.assertNotIn('cost_modifiers',player)


if __name__=='__main__':unittest.main()
