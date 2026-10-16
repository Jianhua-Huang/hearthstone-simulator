"""Four real random damage consumers, native timing and dynamic targets."""
import json,unittest
from hs_sim.cards.native_random_damage_cards import load_batch
from hs_sim.engine import (CardDefinition,CardType,Keyword,SelectChoice,TriggerSpec,Zone)
from hs_sim.engine.effects import (ChoiceOption,Destroy,GainArmor,InvokeBehavior,RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import canonical_digest
import test_history_recovery_cards as base

BOMBER='CORE_EX1_082';PRIESTESS='CORE_BT_493';BLACKWING='CORE_YOP_034';THASS='RLK_223'


def registry():
    r=base.registry()
    def token(c):return(SummonByCard(c.player_id,(SummonEntryMaterial('k32.token'),),SummonCause.capture(c)),)
    r.register_behavior('k32.token',token)
    r.register_card(CardDefinition('k32.token','New random target',CardType.MINION,attack=1,health=5))
    r.register_card(CardDefinition('k32.replace','Dying target producer',CardType.MINION,health=1,deathrattle='k32.token'))
    r.register_card(CardDefinition('k32.shield','Shield target',CardType.MINION,health=5,keywords=(Keyword.DIVINE_SHIELD,)))
    r.register_card(CardDefinition('k32.stealth','Random stealth target',CardType.MINION,health=5,keywords=(Keyword.STEALTH,)))
    r.register_card(CardDefinition('k32.sleep','Sleeping target',CardType.MINION,health=5,dormant_turns=2))
    r.register_card(CardDefinition('k32.spellpower','Spell damage observer',CardType.MINION,health=5,spell_damage=5))
    def watch(c):
        if c.state.entities[c.state.players[c.player_id].hero_id].armor:return()
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id not in(BOMBER,PRIESTESS,BLACKWING,THASS):return()
        gain=GainArmor(c.state.players[c.player_id].hero_id,1)
        summon=SummonByCard(2,(SummonEntryMaterial('k32.token'),),SummonCause.capture(c))
        return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(gain,)),
            ChoiceOption('kill','Remove accepted source',(gain,Destroy(source.id,c.source_id))),
            ChoiceOption('spawn','Add a new target',(gain,summon)),
            ChoiceOption('fail','Fail',(InvokeBehavior('k31.fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior('k32.watch',watch)
    r.register_card(CardDefinition('k32.watch','Random notification observer',CardType.MINION,health=20,
        triggers=(TriggerSpec('random_choice','k32.watch'),)))
    return r


class NativeRandomDamageCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    game=base.HistoryRecoveryCardTests.game;play=base.HistoryRecoveryCardTests.play
    end=base.HistoryRecoveryCardTests.end;round=base.HistoryRecoveryCardTests.round
    choose=base.HistoryRecoveryCardTests.choose;entity=base.HistoryRecoveryCardTests.entity
    def hero(self,g,p=2):return g.state.entities[g.state.players[p].hero_id]
    def randoms(self,g,source):return[e for e in g.events if e.kind=='random_choice'and e.source_id==source]
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(base.Game.from_snapshot(saved,registry()).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for p in(1,2):
            visible=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for key in('resolution_frame','owner_turn_history','resurrection_history','rng_before','rng_after','random_split_roots'):
                self.assertNotIn('"'+key+'"',visible)

    def test_complete_pins_identities_and_native_entries(self):
        data=load_batch()
        for row in data['cards']+data['historical_identity_evidence']:
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        for row in data['cards']:
            raw=row['record'];card=self.r.card(raw['id']);self.assertEqual((card.cost,card.attack,card.health),(raw['cost'],raw['attack'],raw['health']))
        self.assertEqual(self.r.card(BOMBER).metadata.deck_identity,'EX1_082')
        self.assertEqual(self.r.card(PRIESTESS).metadata.deck_identity,'BT_493')
        self.assertEqual(self.r.card(BLACKWING).metadata.deck_identity,'YOP_034')
        self.assertEqual(self.r.card(THASS).battlecry,self.r.card(THASS).deathrattle)
        self.assertIn(Keyword.REBORN,self.r.card(THASS).keywords)

    def test_all_four_paid_roots_enter_once(self):
        for cid in(BOMBER,PRIESTESS,BLACKWING,THASS):
            g=self.game((cid,));eid=self.play(g,cid)
            self.assertEqual(g.state.players[1].mana,40-self.r.card(cid).cost)
            self.assertIn(eid,g.state.players[1].board)
            self.assertEqual(sum(e.kind=='card_played'and e.source_id==eid for e in g.events),1)

    def test_bomber_splits_three_points_across_other_characters_excluding_itself(self):
        g=self.game((BOMBER,));source=self.play(g,BOMBER);events=self.randoms(g,source)
        self.assertEqual(len(events),3);self.assertEqual(self.hero(g,1).health+self.hero(g,2).health,57)
        self.assertEqual(g.state.entities[source].health,2)
        for e in events:self.assertEqual(set(dict(e.data)['candidates']),{self.hero(g,1).id,self.hero(g,2).id})
        self.portable(g)

    def test_bomber_requeries_candidates_after_reaction_creates_new_minion(self):
        g=self.game((BOMBER,),('k32.watch',));source=self.play(g,BOMBER)
        first=self.randoms(g,source)[0];self.assertIsNotNone(g.state.pending_choice);self.portable(g)
        self.choose(g,'spawn');new=self.entity(g,'k32.token',2);events=self.randoms(g,source)
        self.assertEqual(len(events),3);self.assertNotIn(new,dict(first.data)['candidates'])
        self.assertTrue(all(new in dict(e.data)['candidates']for e in events[1:]));self.portable(g)

    def test_bomber_remaining_hits_survive_source_death(self):
        g=self.game((BOMBER,),('k32.watch',));source=self.play(g,BOMBER);self.choose(g,'kill')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(len(self.randoms(g,source)),3);self.portable(g)

    def test_priestess_six_unit_hits_only_at_own_end(self):
        g=self.game(board=(PRIESTESS,));source=self.entity(g,PRIESTESS);self.end(g)
        self.assertEqual(self.hero(g).health,24);self.assertEqual(self.hero(g,1).health,30)
        self.assertEqual(len(self.randoms(g,source)),6);self.end(g)
        self.assertEqual(self.hero(g).health,24);self.end(g);self.assertEqual(self.hero(g).health,18)

    def test_priestess_silence_removes_end_trigger(self):
        g=self.game(('k31.buff',),board=(PRIESTESS,));self.play(g,'k31.buff',self.entity(g,PRIESTESS));self.end(g)
        self.assertEqual(self.hero(g).health,30);self.assertFalse(self.randoms(g,self.entity(g,PRIESTESS)))

    def test_priestess_accepted_split_survives_source_death_and_wait(self):
        g=self.game(board=(PRIESTESS,'k32.watch'));source=self.entity(g,PRIESTESS);self.end(g)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.choose(g,'kill')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(self.hero(g).health,24);self.assertEqual(len(self.randoms(g,source)),6);self.portable(g)

    def test_native_damage_does_not_gain_spell_damage(self):
        for cid,total in((BOMBER,3),(PRIESTESS,6),(THASS,2)):
            g=self.game((cid,),('k32.spellpower',));source=self.play(g,cid)
            if cid==PRIESTESS:self.end(g)
            dealt=sum(e.amount for e in g.events if e.kind=='damage_dealt'and e.source_id==source)
            self.assertEqual(dealt,total)

    def test_blackwing_empty_minion_pool_skips_without_rng_or_hero_damage(self):
        g=self.game(board=(BLACKWING,));source=self.entity(g,BLACKWING);rng=g.snapshot()['rng_state'];self.end(g)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(self.hero(g).health,30)
        self.assertFalse(self.randoms(g,source));self.assertTrue(any(e.kind=='random_choice_skipped'and e.source_id==source for e in g.events))

    def test_blackwing_single_ten_point_hit_can_select_stealth_but_not_own_minion(self):
        g=self.game(board=(BLACKWING,'k31.large'),enemy=('k32.stealth',));source=self.entity(g,BLACKWING)
        victim=self.entity(g,'k32.stealth',2);own=self.entity(g,'k31.large');self.end(g)
        self.assertEqual(g.state.entities[victim].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[own].health,5)
        self.assertEqual(len(self.randoms(g,source)),1);self.assertEqual(self.hero(g).health,30)

    def test_blackwing_does_not_target_dormant_enemy(self):
        g=self.game(board=(BLACKWING,),enemy=('k32.sleep',));rng=g.snapshot()['rng_state'];self.end(g)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(self.entity(g,'k32.sleep',2),g.state.players[2].board[0])

    def test_blackwing_shield_absorbs_one_whole_hit(self):
        g=self.game(board=(BLACKWING,),enemy=('k32.shield',));victim=self.entity(g,'k32.shield',2);self.end(g)
        self.assertEqual(g.state.entities[victim].health,5);self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[victim].keywords)
        self.end(g);self.end(g);self.assertEqual(g.state.entities[victim].zone,Zone.GRAVEYARD)

    def test_later_blackwing_queries_after_previous_deathrattle_replacement(self):
        g=self.game(board=(BLACKWING,BLACKWING),enemy=('k32.replace',));sources=g.state.players[1].board[:]
        first=self.entity(g,'k32.replace',2);self.end(g)
        second=next(d.entity_id for d in g.state.death_history if d.card_id=='k32.token')
        self.assertEqual(dict(self.randoms(g,sources[0])[0].data)['candidates'],(first,))
        self.assertEqual(dict(self.randoms(g,sources[1])[0].data)['candidates'],(second,))
        self.assertEqual(self.hero(g).health,30);self.portable(g)

    def test_thassarian_battlecry_deathrattle_and_reborn_are_separate(self):
        g=self.game((THASS,'k31.kill','k31.kill'));first=self.play(g,THASS);self.assertEqual(self.hero(g).health,28)
        self.play(g,'k31.kill',first);second=self.entity(g,THASS)
        self.assertNotEqual(second,first);self.assertEqual(g.state.entities[second].health,1);self.assertEqual(self.hero(g).health,26)
        self.assertNotIn(Keyword.REBORN,g.state.entities[second].keywords);self.play(g,'k31.kill',second)
        self.assertEqual(self.hero(g).health,24);self.assertEqual(sum(d.card_id==THASS for d in g.state.death_history),2)
        self.assertEqual(len(self.randoms(g,first)),2);self.assertEqual(len(self.randoms(g,second)),1);self.portable(g)

    def test_thassarian_silence_removes_both_future_deathrattle_and_reborn(self):
        g=self.game((THASS,'k31.buff','k31.kill'));first=self.play(g,THASS)
        self.play(g,'k31.buff',first);self.play(g,'k31.kill',first)
        self.assertEqual(self.hero(g).health,28);self.assertFalse(g.state.players[1].board)

    def test_thassarian_can_hit_enemy_minion_as_one_two_point_packet(self):
        g=self.game((THASS,),enemy=('k31.large',));source=self.play(g,THASS);events=self.randoms(g,source)
        self.assertEqual(len(events),1);self.assertEqual(set(dict(events[0].data)['candidates']),{self.hero(g).id,self.entity(g,'k31.large',2)})
        self.assertEqual(self.hero(g).health+g.state.entities[self.entity(g,'k31.large',2)].health,33)

    def test_failed_random_choice_restores_rng_payment_frame_and_tail(self):
        for cid in(BOMBER,PRIESTESS,BLACKWING,THASS):
            g=self.game((cid,),('k32.watch',),enemy=('k31.large',));self.play(g,cid)
            if cid in(PRIESTESS,BLACKWING):self.end(g)
            self.assertIsNotNone(g.state.pending_choice);saved=g.snapshot()
            with self.assertRaises(ResolutionError):self.choose(g,'fail')
            self.assertEqual(g.snapshot(),saved);self.choose(g);self.portable(g)


if __name__=='__main__':unittest.main()
