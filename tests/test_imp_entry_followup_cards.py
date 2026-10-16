"""Actual top-deck Imp recipients and persistent original-entry rewards."""
from copy import deepcopy
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.imp_entry_followup_cards import load_batch,IMP,PREFIX
from hs_sim.engine import CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import AddToHand,ChangeControl,ChoiceOption,Destroy,Draw,GainArmor,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon,Transform
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.successful_summons import BuffSummonedMinion
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference,PutMatchingDeckMinionOnTop
from hs_sim.targets import canonical_digest

CONSTABLE='CAP_401';MASTERMIND='CAP_406';YETI='CORE_CS2_182';HARSH='CAP_404'


def registry(mode='normal'):
    r=build_registry()
    scripts=dict(kill=lambda c:(Destroy(c.target_id,c.source_id),),silence=lambda c:(Silence(c.target_id),),
        give=lambda c:(ChangeControl(c.target_id,3-c.player_id),),bounce=lambda c:(ReturnToHand(c.target_id),),
        draw=lambda c:(Draw(c.player_id,source_id=c.source_id),),summon=lambda c:(Summon(c.player_id,IMP),))
    for name,body in scripts.items():
        r.register_behavior('k67.'+name,body)
        r.register_card(CardDefinition('k67.'+name,name,CardType.SPELL,on_play='k67.'+name,
            requires_target=name in('kill','silence','give','bounce')))
    r.register_card(CardDefinition('k67.same_name','卧底小鬼',CardType.MINION,attack=1,health=1))
    def fail(c):raise ResolutionError('Intentional Imp entry/reorder continuation failure')
    r.register_behavior('k67.fail',fail)
    def resummon(c):
        return(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,
            cause=SummonCause.capture(c)),)
    r.register_behavior('k67.resummon',resummon)
    def watch(c):
        if c.event.kind=='deck_reordered':
            if c.event.player_id!=2 or mode not in('deck_wait','deck_fail'):return()
            if mode=='deck_fail':return(InvokeBehavior('k67.fail',c.source_id,c.player_id),)
        else:
            target=c.state.entities[c.event.target_id]
            if(target.card_id!=IMP or c.event.player_id!=1 or
                    sum(x.card_id==IMP for x in c.state.successful_summon_history)!=1):return()
            if mode=='transform':return(Transform(target.id,YETI),)
            if mode=='control':return(ChangeControl(target.id,2),)
            if mode=='death':return(Destroy(target.id,c.source_id),)
            if mode=='reentry':return(ReturnToHand(target.id),InvokeBehavior('k67.resummon',c.source_id,c.player_id,target.id))
            if mode not in('entry_wait','reward_wire'):return()
        if mode=='reward_wire':
            row=next(x for x in c.state.successful_summon_history if x.event_sequence==c.event.sequence)
            reward=(BuffSummonedMinion(c.player_id,row.id,c.source_id,2,2),)
        else:reward=(GainArmor(c.state.players[c.player_id].hero_id,1),)
        extra=(ChoiceOption('draw','Draw selected card',(Draw(2,source_id=c.source_id),)),)if mode=='deck_wait'else()
        return(RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',reward),
            ChoiceOption('bad','Fail',(InvokeBehavior('k67.fail',c.source_id,c.player_id),)),*extra),source_id=c.source_id),)
    r.register_behavior('k67.watch',watch)
    r.register_card(CardDefinition('k67.watch','Watcher',CardType.MINION,health=8,
        triggers=(TriggerSpec('minion_summoned','k67.watch'),TriggerSpec('deck_reordered','k67.watch'))))
    def buff_deck(c):
        e=next(c.state.entities[i]for i in c.state.players[2].deck if c.state.entities[i].card_id==IMP)
        return(BuffStoredCard(CardReference.capture(e),1,1,c.source_id),)
    r.register_behavior('k67.buff_deck',buff_deck)
    r.register_card(CardDefinition('k67.buff_deck','Prior growth',CardType.SPELL,on_play='k67.buff_deck'))
    return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
    return saved


def find_effect(value,name):
    if isinstance(value,dict):
        if value.get('type','').endswith('.'+name):return value
        for child in value.values():
            found=find_effect(child,name)
            if found is not None:return found
    elif isinstance(value,list):
        for child in value:
            found=find_effect(child,name)
            if found is not None:return found
    return None


class ImpEntryFollowupCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),deck=(YETI,)*8,enemy_hand=(),enemy=(),enemy_deck=(YETI,)*8,mode='normal'):
        r=self.r if mode=='normal'else registry(mode)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=enemy_deck,mana=40,max_mana=40,mana_cap=40)),seed=1067),r)
    def entities(self,g,cid,p=1,zone='board'):
        s=g.state;return[s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid]
    def play(self,g,cid,target=None,p=1):
        eid=self.entities(g,cid,p,'hand')[0].id;g.apply(PlayCard(p,eid,target));return eid
    def portable(self,g,mode='normal'):
        saved=g.snapshot();self.assertEqual(Game.from_snapshot(saved,registry(mode)).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry(mode)).snapshot(),saved)
    def master(self,extra=(),board=(),mode='normal'):
        g=self.game((MASTERMIND,IMP,*extra),board=board,mode=mode);source=self.play(g,MASTERMIND);return g,source
    def test_complete_two_root_faces_and_existing_imp_identity(self):
        d=load_batch();self.assertEqual([x['record']['id']for x in d['cards']],[CONSTABLE,MASTERMIND])
        for row in d['cards']+d['existing_dependencies']:
            raw=row['record'];card=self.r.card(raw['id'])
            self.assertEqual(canonical_digest(raw),row['record_sha256'])
            self.assertEqual((card.cost,card.attack,card.health),(raw['cost'],raw['attack'],raw['health']))
        self.assertIn(Keyword.TAUNT,self.r.card(MASTERMIND).keywords)
        self.assertTrue(all(x['child_ids']==[127024]for x in d['gallery_links']))
        self.assertNotIn('CAP_406e',self.r.cards)
    def test_constable_empty_pool_preserves_deck_and_rng_but_pays_and_enters(self):
        g=self.game((CONSTABLE,),enemy_deck=(YETI,)*3);before=g.snapshot();eid=self.play(g,CONSTABLE)
        self.assertEqual(g.snapshot()['rng_state'],before['rng_state'])
        self.assertEqual(g.state.players[2].deck,before['state']['players']['2']['deck'])
        self.assertEqual(g.state.players[1].mana,36);self.assertEqual(g.state.entities[eid].zone,Zone.BOARD)
    def test_constable_ignores_own_deck_and_enemy_hand_matches(self):
        g=self.game((CONSTABLE,),deck=(IMP,),enemy_hand=(IMP,),enemy_deck=(YETI,))
        self.play(g,CONSTABLE)
        self.assertEqual(self.entities(g,IMP,zone='deck')[0].attack,3)
        self.assertEqual(self.entities(g,IMP,2,'hand')[0].attack,3)
        self.assertFalse(g.state.deck_shuffle_history)
    def test_constable_selects_one_physical_copy_keeps_other_order_and_residence(self):
        g=self.game((CONSTABLE,),enemy_deck=(YETI,IMP,YETI,IMP))
        old=list(g.state.players[2].deck);materials={e.id:(e.zone_epoch,len(e.enchantments))for e in self.entities(g,IMP,2,'deck')}
        self.play(g,CONSTABLE);now=g.state.players[2].deck;selected=now[0]
        self.assertIn(selected,materials);self.assertEqual(now[1:],[i for i in old if i!=selected])
        for e in self.entities(g,IMP,2,'deck'):
            self.assertEqual(e.zone_epoch,materials[e.id][0])
            self.assertEqual((e.attack,e.health),(5,5)if e.id==selected else(3,3))
        self.portable(g)
    def test_singleton_random_selection_consumes_rng_and_retains_prior_growth(self):
        g=self.game(('k67.buff_deck',CONSTABLE),enemy_deck=(YETI,IMP,YETI))
        self.play(g,'k67.buff_deck');original=self.entities(g,IMP,2,'deck')[0];rng=g.snapshot()['rng_state']
        self.play(g,CONSTABLE);current=g.state.entities[original.id]
        self.assertNotEqual(g.snapshot()['rng_state'],rng)
        self.assertEqual(g.state.players[2].deck[0],original.id)
        self.assertEqual((current.attack,current.health,current.zone_epoch),(6,6,original.zone_epoch));self.portable(g)
    def test_top_placement_does_not_add_a_shuffle_operation(self):
        g=self.game((HARSH,CONSTABLE));self.play(g,HARSH);rows=deepcopy(g.state.deck_shuffle_history)
        self.play(g,CONSTABLE);self.assertEqual(g.state.deck_shuffle_history,rows)
    def test_real_repeated_constable_battlecry_reselects_same_singleton_and_stacks(self):
        g=self.game((CONSTABLE,),board=('TIME_064',),enemy_deck=(YETI,IMP))
        self.play(g,CONSTABLE);e=self.entities(g,IMP,2,'deck')[0]
        self.assertEqual((e.attack,e.health),(7,7));self.assertEqual(g.state.players[2].deck[0],e.id);self.portable(g)
    def test_actual_opponent_draw_summons_original_top_card_with_stored_growth(self):
        g=self.game((CONSTABLE,),enemy_deck=(YETI,IMP,YETI));original=self.entities(g,IMP,2,'deck')[0].id
        self.play(g,CONSTABLE);g.apply(EndTurn(1));e=g.state.entities[original]
        self.assertEqual((e.controller,e.zone,e.attack,e.health),(1,Zone.BOARD,5,5))
        self.assertEqual(len(g.state.draw_history),2);self.portable(g)
    def test_pending_top_placement_restores_original_selected_buff_without_resampling(self):
        g=self.game((CONSTABLE,),board=('k67.watch',),enemy_deck=(IMP,YETI,IMP),mode='deck_wait')
        self.play(g,CONSTABLE);self.assertIsNotNone(g.state.pending_choice);selected=g.state.players[2].deck[0]
        saved=g.snapshot();rng=saved['rng_state'];self.portable(g,'deck_wait');q=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,q.id,('bad',)))
        self.assertEqual(g.snapshot(),saved);g.apply(SelectChoice(1,q.id,('ok',)))
        self.assertEqual(g.state.players[2].deck[0],selected);self.assertEqual(g.state.entities[selected].attack,5)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g,'deck_wait')
    def test_after_reorder_error_rolls_back_original_payment_board_and_rng(self):
        g=self.game((CONSTABLE,),board=('k67.watch',),enemy_deck=(IMP,YETI,IMP),mode='deck_fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,CONSTABLE)
        self.assertEqual(g.snapshot(),saved)
    def test_selected_top_card_departure_cannot_redirect_old_stored_growth(self):
        g=self.game((CONSTABLE,),board=('k67.watch',),enemy_deck=(IMP,YETI),mode='deck_wait')
        self.play(g,CONSTABLE);eid=g.state.players[2].deck[0];self.assertEqual(g.state.entities[eid].attack,3)
        g.apply(SelectChoice(1,g.state.pending_choice.id,('draw',)))
        self.assertEqual((g.state.entities[eid].controller,g.state.entities[eid].zone,g.state.entities[eid].attack),(1,Zone.BOARD,3))
        self.portable(g,'deck_wait')
    def test_mastermind_installs_one_persistent_instance_and_ordinary_taunt(self):
        g,source=self.master();self.assertIn(Keyword.TAUNT,g.state.entities[source].keywords)
        self.assertEqual(g.state.players[1].mana,35);self.assertEqual(len(g.state.players[1].player_effects),1)
        effect=g.state.players[1].player_effects[0]
        self.assertEqual((effect.spec_id,effect.source_id,effect.remaining_turns),(PREFIX+'mastermind',source,None));self.portable(g)
    def test_existing_scenario_imp_is_not_retroactively_rewarded(self):
        g=self.game((MASTERMIND,),board=(IMP,));old=self.entities(g,IMP)[0].id;self.play(g,MASTERMIND)
        self.assertEqual((g.state.entities[old].attack,g.state.entities[old].health),(3,3))
    def test_ordinary_paid_imp_entry_receives_reward_once(self):
        g,source=self.master();eid=self.play(g,IMP);e=g.state.entities[eid]
        self.assertEqual((e.attack,e.health),(5,5));self.assertEqual(len(e.enchantments),1)
        self.assertEqual(e.enchantments[0].source_id,source);self.assertEqual(g.state.players[1].mana,32);self.portable(g)
    def test_effect_summon_receives_reward_without_fabricating_a_hand_play(self):
        g,source=self.master(('k67.summon',));self.play(g,'k67.summon');e=self.entities(g,IMP)[0]
        self.assertEqual((e.attack,e.health),(5,5));self.assertEqual(len(g.state.play_history),2)
    def test_opponent_entry_is_not_rewarded_by_our_instance(self):
        g=self.game((MASTERMIND,),enemy_hand=(IMP,));self.play(g,MASTERMIND);g.apply(EndTurn(1));eid=self.play(g,IMP,p=2)
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(3,3));self.portable(g)
    def test_other_definition_with_same_display_name_is_not_an_imp_formant(self):
        g,source=self.master(('k67.same_name',));eid=self.play(g,'k67.same_name')
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(1,1))
    def test_two_real_mastermind_sources_stack_independent_rewards(self):
        g,source=self.master((MASTERMIND,));self.play(g,MASTERMIND);eid=self.play(g,IMP)
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(7,7))
        self.assertEqual(len(g.state.players[1].player_effects),2);self.portable(g)
    def test_real_repeated_mastermind_battlecry_creates_two_independent_instances(self):
        g,source=self.master(board=('TIME_064',));eid=self.play(g,IMP)
        self.assertEqual(len(g.state.players[1].player_effects),2);self.assertEqual(g.state.entities[eid].attack,7);self.portable(g)
    def test_source_silence_does_not_remove_persistent_entry_reward(self):
        g,source=self.master(('k67.silence',));self.play(g,'k67.silence',source);eid=self.play(g,IMP)
        self.assertEqual(g.state.entities[eid].attack,5)
    def test_source_death_does_not_remove_persistent_entry_reward(self):
        g,source=self.master(('k67.kill',));self.play(g,'k67.kill',source);eid=self.play(g,IMP)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[eid].attack,5);self.portable(g)
    def test_source_control_change_does_not_move_original_player_instance(self):
        g,source=self.master(('k67.give',));self.play(g,'k67.give',source);eid=self.play(g,IMP)
        self.assertEqual(g.state.entities[source].controller,2);self.assertEqual(g.state.entities[eid].attack,5)
        self.assertFalse(g.state.players[2].player_effects);self.portable(g)
    def test_source_return_and_replay_retains_old_instance_and_adds_new_one(self):
        g,source=self.master(('k67.bounce',));self.play(g,'k67.bounce',source);self.play(g,MASTERMIND);eid=self.play(g,IMP)
        self.assertEqual(g.state.entities[eid].attack,7);self.assertEqual(len(g.state.players[1].player_effects),2);self.portable(g)
    def test_full_board_failed_summon_does_not_create_an_entry_or_reward(self):
        g=self.game((MASTERMIND,'k67.summon'),board=(YETI,)*6);self.play(g,MASTERMIND)
        old=deepcopy(g.state.successful_summon_history);self.play(g,'k67.summon')
        self.assertEqual(g.state.successful_summon_history,old);self.assertFalse(self.entities(g,IMP))
    def test_stored_constable_growth_and_actual_entry_reward_share_original_imp(self):
        g=self.game((MASTERMIND,CONSTABLE),enemy_deck=(YETI,IMP,YETI));original=self.entities(g,IMP,2,'deck')[0].id
        self.play(g,MASTERMIND);self.play(g,CONSTABLE);g.apply(EndTurn(1));e=g.state.entities[original]
        self.assertEqual((e.controller,e.zone,e.attack,e.health),(1,Zone.BOARD,7,7));self.portable(g)
    def test_accepted_summon_reward_follows_same_residence_transform(self):
        g,source=self.master(board=('k67.watch',),mode='transform');eid=self.play(g,IMP);e=g.state.entities[eid]
        self.assertEqual((e.card_id,e.attack,e.health),(YETI,6,7));self.portable(g,'transform')
    def test_accepted_summon_reward_follows_same_residence_control_change(self):
        g,source=self.master(board=('k67.watch',),mode='control');eid=self.play(g,IMP);e=g.state.entities[eid]
        self.assertEqual((e.controller,e.attack,e.health),(2,5,5));self.portable(g,'control')
    def test_old_entry_reward_cannot_rebind_after_return_and_actual_reentry(self):
        g,source=self.master(board=('k67.watch',),mode='reentry');eid=self.play(g,IMP);e=g.state.entities[eid]
        entries=[x for x in g.state.successful_summon_history if x.entity_id==eid]
        self.assertEqual(len(entries),2);self.assertNotEqual(entries[0].minion.entered_order,entries[1].minion.entered_order)
        self.assertEqual((e.attack,e.health),(5,5));self.portable(g,'reentry')
    def test_accepted_reward_does_not_resurrect_an_entry_killed_by_earlier_reaction(self):
        g,source=self.master(board=('k67.watch',),mode='death');eid=self.play(g,IMP)
        self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)
        self.assertFalse(g.state.entities[eid].enchantments);self.portable(g,'death')
    def test_original_entry_reward_waiting_restore_and_bad_choice_rollback(self):
        g,source=self.master(board=('k67.watch',),mode='entry_wait');eid=self.play(g,IMP)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g,'entry_wait');saved=g.snapshot();q=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,q.id,('bad',)))
        self.assertEqual(g.snapshot(),saved);g.apply(SelectChoice(1,q.id,('ok',)))
        self.assertEqual(g.state.entities[eid].attack,5);self.portable(g,'entry_wait')
    def test_rehashed_waiting_reward_rejects_unknown_entry_player_and_source(self):
        g=self.game((IMP,),board=('k67.watch',),mode='reward_wire');eid=self.play(g,IMP)
        self.portable(g,'reward_wire')
        for name,value in [('summon_id',999999),('player_id',2),('source_id',999999)]:
            with self.subTest(field=name):
                bad=g.snapshot();effect=find_effect(bad,'BuffSummonedMinion');self.assertIsNotNone(effect)
                effect['fields'][name]=value
                with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry('reward_wire'))
        g.apply(SelectChoice(1,g.state.pending_choice.id,('ok',)));self.assertEqual(g.state.entities[eid].attack,5)
    def test_current_codec_rejects_unknown_top_source_definition_and_non_minion(self):
        g=self.game((CONSTABLE,),enemy_deck=(IMP,));source=self.entities(g,CONSTABLE,zone='hand')[0].id
        codec=FrameCodec(default_mechanics(),g.registry,origin_state=g.state)
        valid=PutMatchingDeckMinionOnTop(2,(IMP,),source,2,2);self.assertEqual(codec.decode(codec.encode(valid)),valid)
        for request in(PutMatchingDeckMinionOnTop(2,(IMP,),999999,2,2),
                PutMatchingDeckMinionOnTop(2,('k67.unknown',),source,2,2),
                PutMatchingDeckMinionOnTop(2,(HARSH,),source,2,2)):
            with self.subTest(request=request),self.assertRaises(ValueError):codec.encode(request)
    def test_declaration_shapes_reject_unreviewed_players_ids_and_negative_growth(self):
        invalid=[lambda:PutMatchingDeckMinionOnTop(2,(),1),lambda:PutMatchingDeckMinionOnTop(2,(IMP,IMP),1),
            lambda:PutMatchingDeckMinionOnTop(2,[IMP],1),lambda:PutMatchingDeckMinionOnTop(2,(IMP,),True),
            lambda:PutMatchingDeckMinionOnTop(2,(IMP,),1,-1,2),lambda:BuffSummonedMinion(3,1,1,2,2),
            lambda:BuffSummonedMinion(1,True,1,2,2),lambda:BuffSummonedMinion(1,1,1,2,-1)]
        for factory in invalid:
            with self.subTest(factory=factory),self.assertRaises(ValueError):factory()
    def test_same_seed_reproduces_original_physical_top_recipient(self):
        games=[self.game((CONSTABLE,),enemy_deck=(IMP,YETI,IMP,YETI,IMP))for _ in range(2)]
        for g in games:self.play(g,CONSTABLE)
        self.assertEqual(games[0].snapshot(),games[1].snapshot());self.portable(games[0])
    def test_player_queries_are_pure_and_do_not_expose_private_top_candidate_material(self):
        g=self.game((CONSTABLE,MASTERMIND),enemy_deck=(IMP,YETI,IMP));self.play(g,MASTERMIND);saved=g.snapshot()
        for p in(1,2):
            view=g.observe(p);g.for_player(p).legal_actions()
            self.assertNotIn('successful_summon_history',view)
            for player in view['players']:
                self.assertNotIn('deck',player);self.assertNotIn('summon_id',player)
        self.assertEqual(g.snapshot(),saved)


if __name__=='__main__':unittest.main()
