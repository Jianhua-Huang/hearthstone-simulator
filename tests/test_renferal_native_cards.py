"""Actual per-player played faces and private original-hand trap clocks."""
from dataclasses import replace
import json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.renferal_native_cards import load_batch,BODY
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,
    PlayCard,PlayerSetup,Scenario,SelectChoice,TriggerSpec)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import AddToHand,ChoiceOption,GainArmor,InvokeBehavior,RequestChoice,ReturnToHand
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.hand_play_locks import TrapRandomHandCards,play_error
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import canonical_digest

ROOT='EDR_526';PLAIN='CORE_CS2_182';WEB='EDR_523'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=(),factions=(),subtypes=())


def registry(mode=None):
    r=build_registry()
    scripts=dict(once=lambda c:(TrapRandomHandCards(3-c.player_id,1,c.source_id),),
        two=lambda c:(TrapRandomHandCards(3-c.player_id,2,c.source_id),),
        many=lambda c:(TrapRandomHandCards(3-c.player_id,20,c.source_id),),
        self=lambda c:(TrapRandomHandCards(c.player_id,1,c.source_id),),
        summon=lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(ROOT),),SummonCause.capture(c)),),
        invoke=lambda c:(InvokeBehavior(BODY,c.source_id,c.player_id),),
        fail=lambda c:(AddToHand(c.player_id,'missing.k55',c.source_id),))
    for name,body in scripts.items():
        r.register_behavior('k55.'+name,body)
        if name!='fail':r.register_card(CardDefinition('k55.'+name,name,CardType.SPELL,on_play='k55.'+name,metadata=META))
    if mode:
        def watch(c):
            if c.state.entities[c.event.source_id].card_id!=ROOT:return ()
            if mode=='fault':return(AddToHand(c.player_id,'missing.k55',c.source_id),)
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(GainArmor(c.player_id,0),)),
                ChoiceOption('bad','Rollback',(InvokeBehavior('k55.fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior('k55.watch',watch)
        r.register_card(CardDefinition('k55.watch','Original trap window observer',CardType.MINION,health=8,
            triggers=(TriggerSpec('minion_summoned'if mode=='before'else'card_played','k55.watch'),),metadata=META))
    return r


class RenferalNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),*,other=(PLAIN,)*4,board=(),deck=None,active=1,mode=None):
        return Game.from_scenario(Scenario((PlayerSetup('test.hero',hand=hand,board=board,deck=(PLAIN,)*8 if deck is None else deck,
            mana=60,max_mana=60,mana_cap=60),PlayerSetup('test.hero',hand=other,deck=(PLAIN,)*8,mana=60,max_mana=60,mana_cap=60)),
            active_player=active,seed=1055),registry(mode)if mode else self.r)
    def entity(self,g,cid,p=1,zone='hand'):
        s=g.state;return next(s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid)
    def play(self,g,cid,target=None,p=1):
        source=self.entity(g,cid,p).id;g.apply(PlayCard(p,source,target));return source
    def marks(self,g,p=2):
        s=g.state;return[(i,e)for i in s.players[p].hand for e in s.entities[i].enchantments if e.hand_play_lock is not None]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g,mode=None):
        saved=g.snapshot();other=Game.from_snapshot(saved,registry(mode));self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry(mode)).snapshot(),saved);return other
    def test_complete_printed_root_and_native_base_count(self):
        row=load_batch()['cards'][0];raw=row['record'];card=self.r.card(ROOT)
        self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual((card.cost,card.attack,card.health),(3,3,3))
        self.assertEqual(raw['tags']['TAG_SCRIPT_DATA_NUM_1'],1);self.assertEqual(card.metadata.tribes,('beast',))
    def test_first_native_play_pays_once_and_traps_one_physical_card(self):
        g=self.game((ROOT,));self.play(g,ROOT);self.assertEqual(g.state.players[1].mana,57);self.assertEqual(len(self.marks(g)),1);self.portable(g)
    def test_second_actual_play_traps_two_without_a_mutable_card_counter(self):
        g=self.game((ROOT,WEB));source=self.play(g,ROOT);self.play(g,WEB,source);self.play(g,ROOT)
        self.assertEqual(len(self.marks(g)),3);self.assertEqual(sum(p.card_id==ROOT for p in g.state.play_history),2);self.portable(g)
    def test_distinct_native_copies_share_the_players_actual_play_history(self):
        g=self.game((ROOT,ROOT));self.play(g,ROOT);self.play(g,ROOT);self.assertEqual(len(self.marks(g)),3)
    def test_repeated_battlecry_does_not_increment_play_count(self):
        g=self.game((ROOT,),board=('LOE_077',));self.play(g,ROOT)
        self.assertEqual(len(self.marks(g)),2);self.assertEqual(sum(p.card_id==ROOT for p in g.state.play_history),1);self.portable(g)
    def test_unrelated_minion_plays_do_not_improve_this_card(self):
        g=self.game((PLAIN,ROOT));self.play(g,PLAIN);self.play(g,ROOT);self.assertEqual(len(self.marks(g)),1)
    def test_direct_summon_has_no_battlecry_or_play_growth(self):
        g=self.game(('k55.summon',ROOT));self.play(g,'k55.summon');self.assertFalse(self.marks(g));self.play(g,ROOT);self.assertEqual(len(self.marks(g)),1)
    def test_other_players_prior_renferal_is_not_own_growth(self):
        g=self.game(other=(ROOT,PLAIN,PLAIN),deck=(ROOT,PLAIN),active=2);self.play(g,ROOT,p=2);g.apply(EndTurn(2));self.play(g,ROOT)
        self.assertEqual(len(self.marks(g)),1);self.portable(g)
    def test_effect_body_reads_completed_prior_plays_without_fabricating_another_play(self):
        g=self.game((ROOT,'k55.invoke'));self.play(g,ROOT);self.play(g,'k55.invoke')
        self.assertEqual(len(self.marks(g)),3);self.assertEqual(sum(p.card_id==ROOT for p in g.state.play_history),1)
    def test_distinct_selection_is_by_physical_card_not_card_name(self):
        g=self.game(('k55.two',),other=(PLAIN,)*3);self.play(g,'k55.two');self.assertEqual(len(self.marks(g)),2)
        self.assertEqual(len({i for i,_ in self.marks(g)}),2);self.portable(g)
    def test_selection_uses_rng_only_for_a_proper_subset(self):
        g=self.game(('k55.two',),other=(PLAIN,)*3);before=g.snapshot()['rng_state'];self.play(g,'k55.two');self.assertNotEqual(g.snapshot()['rng_state'],before)
        g=self.game(('k55.many',),other=(PLAIN,)*3);before=g.snapshot()['rng_state'];self.play(g,'k55.many');self.assertEqual(g.snapshot()['rng_state'],before)
    def test_empty_hand_is_a_valid_no_rng_no_trap_result(self):
        g=self.game((ROOT,),other=());before=g.snapshot()['rng_state'];self.play(g,ROOT);self.assertEqual(g.snapshot()['rng_state'],before);self.assertFalse(self.marks(g));self.portable(g)
    def test_large_count_caps_to_all_current_physical_cards(self):
        g=self.game(('k55.many',),other=(PLAIN,)*2);self.play(g,'k55.many');self.assertEqual(len(self.marks(g)),2)
    def test_already_trapped_cards_remain_candidates_for_later_batches(self):
        g=self.game(('k55.once','k55.once'),other=(PLAIN,));self.play(g,'k55.once');self.play(g,'k55.once')
        self.assertEqual(len(self.marks(g)),2);self.assertEqual(len({i for i,_ in self.marks(g)}),1);self.portable(g)
    def test_trap_blocks_the_next_opponent_turn_and_expires_at_the_following_start(self):
        g=self.game((ROOT,),other=(PLAIN,));self.play(g,ROOT);target=self.marks(g)[0][0];g.apply(EndTurn(1))
        self.assertIsNotNone(play_error(g.state,g.state.entities[target]));waiting=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(PlayCard(2,target))
        self.assertEqual(g.snapshot(),waiting);g.apply(EndTurn(2));g.apply(EndTurn(1))
        self.assertIsNone(play_error(g.state,g.state.entities[target]));g.apply(PlayCard(2,target));self.portable(g)
    def test_current_target_turn_trap_expires_at_its_next_actual_start(self):
        g=self.game(('k55.self',PLAIN));target=self.entity(g,PLAIN).id;self.play(g,'k55.self')
        self.assertIsNotNone(play_error(g.state,g.state.entities[target]));g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertIsNone(play_error(g.state,g.state.entities[target]));self.portable(g)
    def test_original_turn_clock_is_saved_in_existing_zero_stat_marks(self):
        g=self.game((ROOT,));self.play(g,ROOT);_,e=self.marks(g)[0]
        self.assertEqual((e.attack,e.health,e.set_attack,e.set_health),(0,0,None,None));self.assertEqual(e.hand_play_lock.owner_starts,2)
        self.assertEqual(e.hand_play_lock.deadline.player_id,2);self.portable(g)
    def test_wait_before_native_body_restores_the_same_rng_and_selected_cards(self):
        mode='before';g=self.game((ROOT,),board=('k55.watch',),mode=mode);self.play(g,ROOT);self.assertIsNotNone(g.state.pending_choice)
        other=self.portable(g,mode);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.marks(g)),1);self.portable(g,mode)
    def test_wait_after_traps_keeps_existing_marks_and_does_not_resample(self):
        mode='after';g=self.game((ROOT,),board=('k55.watch',),mode=mode);self.play(g,ROOT);before=g.snapshot();self.assertEqual(len(self.marks(g)),1)
        other=self.portable(g,mode);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.snapshot()['rng_state'],before['rng_state']);self.portable(g,mode)
    def test_bad_choice_rolls_back_to_original_wait_with_traps_intact(self):
        mode='after';g=self.game((ROOT,),board=('k55.watch',),mode=mode);self.play(g,ROOT);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(len(self.marks(g)),1)
    def test_failure_after_traps_rolls_back_payment_hand_rng_history_and_locks(self):
        mode='fault';g=self.game((ROOT,),board=('k55.watch',),mode=mode);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,ROOT)
        self.assertEqual(g.snapshot(),before)
    def test_codec_roundtrips_request_and_rejects_unknown_source_even_with_empty_hand(self):
        g=self.game(other=());source=g.state.players[1].hero_id;codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        effect=TrapRandomHandCards(2,1,source);self.assertEqual(codec.decode(codec.encode(effect)),effect)
        with self.assertRaises(ValueError):codec.encode(replace(effect,source_id=999999))
    def test_request_rejects_invalid_player_count_and_source_types(self):
        for args in((3,1,1),(2,0,1),(2,True,1),(2,1,0),(2,1,False)):
            with self.assertRaises(ValueError):TrapRandomHandCards(*args)
    def test_only_target_can_observe_locked_play_availability(self):
        g=self.game((ROOT,),other=(PLAIN,)*3);self.play(g,ROOT);g.apply(EndTurn(1));target=self.marks(g)[0][0]
        listing=g.for_player(2).legal_actions();own=next(p for p in listing['observation']['players']if p['id']==2)
        ref=own['hand'][next(i for i,e in enumerate(g.state.players[2].hand)if e==target)]['ref']
        self.assertFalse(any(a['type']=='play_card'and a['card']==ref for a in listing['actions']))
        text=json.dumps(g.for_player(1).observe());self.assertNotIn('hand_play_lock',text);self.assertNotIn('deadline',text)
        self.assertNotIn(PLAIN,text);self.portable(g)


if __name__=='__main__':unittest.main()
