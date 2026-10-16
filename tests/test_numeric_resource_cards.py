"""Actual first-copy target requirements and original summon/Mana rewards."""
from copy import deepcopy
from dataclasses import replace
import json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.numeric_resource_cards import load_batch,BATCH_HASH,FOREST,URSOL,TRIUMPH,BRIBE,MOSS,GOLEM,COIN
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,Game,PlayCard,PlayerSetup,Scenario,
    EndTurn,SelectChoice,SnapshotError,SpellSchool,TargetMode,TriggerSpec,Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,Damage,GainArmor,GainTemporaryMana,InvokeBehavior,
    RequestChoice,ReturnToHand,SpendMana,Summon,Transform)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.interrupts import CounterSpell,RedirectSpellTarget
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.model import PlayerEffectSpec
from hs_sim.engine.replay import replay,build_replay
from hs_sim.engine.representative import build_registry as representative
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.automatic_targets import AutomaticTargetPreference
from hs_sim.engine.spell_target_conditions import UnplayedCopyTargetProfile
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

YETI='CORE_CS2_182';META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


def registry(mode=None):
    r=build_registry()
    r.register_player_effect(PlayerEffectSpec('k69.noheroes',card_id='k69.limit',kind='turn_rule',target_policy='spells_no_heroes'))
    bodies=dict(hit=lambda c:(Damage(c.target_id,2,c.source_id),),refund=lambda c:(GainTemporaryMana(c.player_id,6),),
        auto=lambda c:(CastSpell(c.player_id,TRIUMPH,c.source_id,target_preference=AutomaticTargetPreference.ANY),),
        auto_legacy=lambda c:(CastSpell(c.player_id,TRIUMPH,c.source_id),),
        auto_moss=lambda c:(CastSpell(c.player_id,MOSS,c.source_id),),
        whole=lambda c:(ReplayWholeCards(c.player_id,c.source_id,WholeCardHistoryQuery(c.player_id,len(c.state.play_history)+1),
            target_preference=AutomaticTargetPreference.ANY),),
        limit=lambda c:(AddPlayerEffect(c.player_id,'k69.noheroes',c.source_id),),
        fail=lambda c:(AddToHand(c.player_id,'k69.missing',c.source_id),),
        resummon=lambda c:(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id),))
    for key,body in bodies.items():
        r.register_behavior('k69.'+key,body)
        if key not in('fail','resummon'):
            r.register_card(CardDefinition('k69.'+key,key,CardType.SPELL,on_play='k69.'+key,requires_target=key=='hit',metadata=META))
    r.register_card(CardDefinition('k69.dormant','Dormant count fixture',CardType.MINION,attack=1,health=5,dormant_turns=3,metadata=META))
    r.register_card(CardDefinition('k69.power','Spell Damage fixture',CardType.MINION,health=5,spell_damage=1,metadata=META))
    if mode:
        def watch(c):
            event=c.event
            if mode=='counter':
                if c.play is None or c.play.card_id!=TRIUMPH or sum(p.card_id==TRIUMPH and p.player_id==c.play.player_id for p in c.state.play_history)!=1:return()
                return(CounterSpell(dict(event.data)['window_id']),)
            if mode=='redirect':
                if c.state.entities[event.source_id].card_id!=TRIUMPH:return()
                return(RedirectSpellTarget(dict(event.data)['window_id'],c.state.players[1].hero_id),)
            if mode.startswith('summon_'):
                if event.target_id is None or c.state.entities[event.target_id].card_id!=GOLEM:return()
                return(GainTemporaryMana(c.player_id,1),)if mode=='summon_refund'else(InvokeBehavior('k69.fail',c.source_id,c.player_id),)
            if c.mana_result is None or c.mana_result.source_card_id!=MOSS:return()
            if mode=='mana_fail':return(InvokeBehavior('k69.fail',c.source_id,c.player_id),)
            first=next(c.state.entities[i].id for i in c.state.players[1].board if c.state.entities[i].card_id==GOLEM)
            options=(ChoiceOption('ok','Continue',(GainArmor(c.state.players[1].hero_id,1),)),
                ChoiceOption('bad','Fail',(InvokeBehavior('k69.fail',c.source_id,c.player_id),)),
                ChoiceOption('bounce','Bounce original',(ReturnToHand(first),)),
                ChoiceOption('reenter','Bounce and resummon',(ReturnToHand(first),InvokeBehavior('k69.resummon',c.source_id,1,first))),
                ChoiceOption('transform','Transform original',(Transform(first,YETI),)),
                ChoiceOption('give','Transfer original',(ChangeControl(first,2),)),
                ChoiceOption('foreign','New same-name minion',(Summon(1,GOLEM),)),
                ChoiceOption('debit','Later independent debit',(GainTemporaryMana(1,1),SpendMana(1,None,c.source_id))))
            return(RequestChoice(1,options,source_id=c.source_id),)
        key='k69.watch.'+mode;r.register_behavior(key,watch)
        event='card_committed'if mode=='counter'else'spell_targeted'if mode=='redirect'else'minion_summoned'if mode.startswith('summon_')else'mana_consumption_resolved'
        r.register_card(CardDefinition(key,'Actual-window fixture',CardType.MINION,health=20,triggers=(TriggerSpec(event,key),),metadata=META))
    return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
    return saved


def wire(value,name):
    if isinstance(value,dict):
        if value.get('type','').endswith('.'+name):return value
        for x in value.values():
            found=wire(x,name)
            if found is not None:return found
    elif isinstance(value,list):
        for x in value:
            found=wire(x,name)
            if found is not None:return found


class NumericResourceCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),mana=10,mode=None,enemy_cap=None):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=mana,max_mana=mana,mana_cap=max(30,mana)),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8,mana=20,max_mana=20,mana_cap=30,hand_cap=enemy_cap)),seed=1069),self.r if mode is None else registry(mode))
    def entities(self,g,cid,p=1,zone='board'):
        s=g.state;return[s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid]
    def play(self,g,cid,target=None,p=1):
        eid=self.entities(g,cid,p,'hand')[0].id;g.apply(PlayCard(p,eid,target));return eid
    def hero(self,g,p=1):return g.state.players[p].hero_id
    def health(self,g,p=1):return g.state.entities[self.hero(g,p)].health
    def portable(self,g,mode=None):
        saved=g.snapshot();other=Game.from_snapshot(saved,registry(mode));self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry(mode)).snapshot(),saved);return other
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def waiting(self):
        g=self.game((MOSS,),board=('k69.watch.wait',),mode='wait');self.play(g,MOSS);self.assertIsNotNone(g.state.pending_choice);return g
    def test_five_complete_roots_fixed_golem_and_coin_dependency(self):
        d=load_batch();self.assertEqual(canonical_digest(d),BATCH_HASH);self.assertEqual(len(d['cards']),5)
        for row in d['cards']+d['dependencies']+d['reused_dependencies']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual((self.r.card(GOLEM).cost,self.r.card(GOLEM).attack,self.r.card(GOLEM).health),(1,1,2))
        self.assertFalse(self.r.card(GOLEM).metadata.collectible);self.assertIsNone(self.r.card(URSOL).spell_school)
        self.assertEqual(self.r.card(FOREST).spell_school,SpellSchool.NATURE);self.assertEqual(self.r.card(MOSS).spell_school,SpellSchool.NATURE)
    def test_default_representative_fingerprint_stays_exact(self):
        self.assertEqual(representative().fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')
    def test_forest_counts_dormant_minions_but_not_locations(self):
        g=self.game((FOREST,),board=(YETI,'k69.dormant','CORE_REV_990'));target=self.entities(g,YETI)[0].id;self.play(g,FOREST,target)
        e=g.state.entities[target];self.assertEqual((e.attack,e.health),(6,7));self.portable(g)
    def test_forest_rejects_enemy_hero_and_missing_target_without_payment(self):
        g=self.game((FOREST,),board=(YETI,),enemy=(YETI,));saved=g.snapshot()
        for target in(None,self.hero(g),self.entities(g,YETI,2)[0].id):
            with self.assertRaises(IllegalAction):self.play(g,FOREST,target)
            self.assertEqual(g.snapshot(),saved)
    def test_forest_growth_does_not_use_spell_damage(self):
        g=self.game((FOREST,),board=(YETI,'k69.power'));eid=self.entities(g,YETI)[0].id;self.play(g,FOREST,eid)
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(6,7))
    def test_ursol_friendly_sets_three_and_clears_damage(self):
        g=self.game(('k69.hit',URSOL),board=(YETI,));eid=self.entities(g,YETI)[0].id;self.play(g,'k69.hit',eid);self.play(g,URSOL,eid)
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health,g.state.entities[eid].damage),(3,3,0));self.portable(g)
    def test_ursol_enemy_sets_one_without_silencing_native_keywords(self):
        g=self.game((URSOL,),enemy=('CORE_EX1_008',));eid=self.entities(g,'CORE_EX1_008',2)[0].id;before=g.state.entities[eid].keywords;self.play(g,URSOL,eid)
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(1,1));self.assertEqual(g.state.entities[eid].keywords,before)
    def test_ursol_setter_keeps_ongoing_aura_layer(self):
        g=self.game((URSOL,),board=(YETI,'CORE_CS2_122'));eid=self.entities(g,YETI)[0].id;self.play(g,URSOL,eid)
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(4,3))
    def test_minion_only_spells_have_no_hero_or_empty_board_action(self):
        for cid in(FOREST,URSOL,BRIBE):
            g=self.game((cid,));before=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,cid,self.hero(g,2))
            with self.assertRaises(IllegalAction):self.play(g,cid)
            self.assertEqual(g.snapshot(),before)
    def test_triumph_first_copy_requires_a_target_and_single_damage(self):
        g=self.game((TRIUMPH,),enemy=(YETI,));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,TRIUMPH)
        self.assertEqual(g.snapshot(),before);self.play(g,TRIUMPH,self.hero(g,2));self.assertEqual(self.health(g,2),27)
        self.assertEqual(self.entities(g,YETI,2)[0].health,5);self.portable(g)
    def test_triumph_second_copy_has_no_target_and_hits_all_enemies(self):
        g=self.game((TRIUMPH,TRIUMPH),enemy=(YETI,));self.play(g,TRIUMPH,self.hero(g,2));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,TRIUMPH,self.hero(g,2))
        self.assertEqual(g.snapshot(),before);rng=g._rng.getstate();self.play(g,TRIUMPH)
        self.assertEqual((self.health(g,2),self.entities(g,YETI,2)[0].health),(24,2));self.assertEqual(g._rng.getstate(),rng);self.portable(g)
    def test_triumph_countered_play_still_qualifies_later_copy(self):
        g=self.game((TRIUMPH,TRIUMPH),board=('k69.watch.counter',),mode='counter');self.play(g,TRIUMPH,self.hero(g,2))
        self.assertTrue(g.state.play_history[-1].countered);self.assertEqual(self.health(g,2),30);self.play(g,TRIUMPH)
        self.assertEqual(self.health(g,2),27);self.portable(g,'counter')
    def test_opponent_copy_does_not_change_own_target_requirement(self):
        g=self.game((TRIUMPH,),enemy_hand=(TRIUMPH,));g.apply(EndTurn(1));self.play(g,TRIUMPH,self.hero(g),p=2);g.apply(EndTurn(2))
        with self.assertRaises(IllegalAction):self.play(g,TRIUMPH)
        self.play(g,TRIUMPH,self.hero(g,2));self.assertEqual(self.health(g,2),27)
    def test_automatic_first_copy_selects_normally_without_fabricated_play(self):
        g=self.game(('k69.auto',TRIUMPH));self.play(g,'k69.auto');cast=g.state.cast_history[-1]
        self.assertEqual(cast.origin,'effect');self.assertEqual(cast.target_selection.partition.mode,TargetMode.REQUIRED);self.assertIsNotNone(cast.target_id)
        self.assertFalse(any(p.card_id==TRIUMPH for p in g.state.play_history))
        with self.assertRaises(IllegalAction):self.play(g,TRIUMPH)
        self.portable(g)
    def test_automatic_copy_after_paid_copy_uses_empty_partition_without_rng(self):
        g=self.game((TRIUMPH,'k69.auto'));self.play(g,TRIUMPH,self.hero(g,2));rng=g._rng.getstate();self.play(g,'k69.auto')
        cast=g.state.cast_history[-1];self.assertIsNone(cast.target_selection.partition.mode);self.assertIsNone(cast.target_id)
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(self.health(g,2),24);self.portable(g)
    def test_legacy_automatic_selector_keeps_same_native_target_requirement(self):
        for prior in(False,True):
            with self.subTest(prior=prior):
                g=self.game((TRIUMPH,'k69.auto_legacy'))
                if prior:self.play(g,TRIUMPH,self.hero(g,2))
                self.play(g,'k69.auto_legacy');cast=g.state.cast_history[-1]
                self.assertIsNone(cast.target_selection);self.assertEqual(cast.target_id is None,prior)
                self.assertIsNone(cast.failure);self.portable(g)
    def test_whole_card_history_replay_obeys_native_target_profile(self):
        g=self.game((TRIUMPH,'k69.whole'));self.play(g,TRIUMPH,self.hero(g,2));self.play(g,'k69.whole')
        self.assertIsNone(g.state.cast_history[-1].target_id);self.assertEqual(self.health(g,2),24)
        self.assertEqual(g.state.whole_card_replay_ledger.stack,());self.assertEqual(sum(p.card_id==TRIUMPH for p in g.state.play_history),1);self.portable(g)
    def test_no_legal_first_target_is_illegal_and_automatic_cast_fizzles(self):
        g=self.game(('k69.limit',TRIUMPH,'k69.auto'));self.play(g,'k69.limit');before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,TRIUMPH)
        self.assertEqual(g.snapshot(),before);self.play(g,'k69.auto');self.assertEqual(g.state.cast_history[-1].failure,'no_target');self.portable(g)
    def test_redirected_first_copy_stays_single_target(self):
        g=self.game((TRIUMPH,),board=('k69.watch.redirect',),mode='redirect');self.play(g,TRIUMPH,self.hero(g,2))
        self.assertEqual((self.health(g),self.health(g,2)),(27,30));self.portable(g,'redirect')
    def test_player_action_listing_switches_to_targetless_second_copy(self):
        g=self.game((TRIUMPH,TRIUMPH));listing=g.for_player(1).legal_actions();ref=next(x['ref']for x in listing['observation']['players'][0]['hand']if x['card_id']==TRIUMPH)
        self.assertTrue(all(a.get('target')is not None for a in listing['actions']if a.get('card')==ref and a['type']=='play_card'))
        self.play(g,TRIUMPH,self.hero(g,2));listing=g.for_player(1).legal_actions();ref=next(x['ref']for x in listing['observation']['players'][0]['hand']if x['card_id']==TRIUMPH)
        actions=[a for a in listing['actions']if a.get('card')==ref and a['type']=='play_card'];self.assertEqual(len(actions),1);self.assertIsNone(actions[0].get('target'))
    def test_profile_rejects_nonspell_duplicate_and_mutation(self):
        r=build_registry()
        with self.assertRaises(ValueError):r.register_spell_target_profile(UnplayedCopyTargetProfile(YETI))
        with self.assertRaises(ValueError):r.register_spell_target_profile(UnplayedCopyTargetProfile(TRIUMPH))
        with self.assertRaises(TypeError):r.spell_target_profiles[TRIUMPH]=UnplayedCopyTargetProfile(TRIUMPH)
    def test_bribe_first_card_only_gives_opponent_coin(self):
        g=self.game((BRIBE,),enemy=(YETI,));self.play(g,BRIBE,self.entities(g,YETI,2)[0].id)
        self.assertFalse(g.state.players[2].board);self.assertEqual(len(self.entities(g,COIN,2,'hand')),1);self.assertFalse(self.entities(g,COIN,zone='hand'));self.portable(g)
    def test_bribe_combo_destroys_once_and_gives_each_player_one_coin(self):
        g=self.game(('k69.refund',BRIBE),enemy=(YETI,));self.play(g,'k69.refund');self.play(g,BRIBE,self.entities(g,YETI,2)[0].id)
        self.assertEqual(len(g.state.death_history),1);self.assertEqual(len(self.entities(g,COIN,2,'hand')),1);self.assertEqual(len(self.entities(g,COIN,zone='hand')),1);self.portable(g)
    def test_bribe_opponent_overflow_does_not_cancel_own_combo_coin(self):
        g=self.game(('k69.refund',BRIBE),enemy=(YETI,),enemy_hand=(YETI,)*2,enemy_cap=2);self.play(g,'k69.refund');self.play(g,BRIBE,self.entities(g,YETI,2)[0].id)
        self.assertFalse(self.entities(g,COIN,2,'hand'));self.assertEqual(len(self.entities(g,COIN,zone='hand')),1)
    def test_moss_summons_two_then_spends_remaining_mana_once(self):
        g=self.game((MOSS,));self.play(g,MOSS);self.assertEqual([(e.attack,e.health)for e in self.entities(g,GOLEM)],[(9,10),(9,10)])
        self.assertEqual(g.state.players[1].mana,0);self.assertEqual([x.actual for x in g.state.mana_consumption_history],[8]);self.assertEqual(g.state.play_history[-1].cost,2);self.portable(g)
    def test_moss_zero_remaining_mana_still_has_exact_zero_debit(self):
        g=self.game((MOSS,),mana=2);self.play(g,MOSS);self.assertEqual([(e.attack,e.health)for e in self.entities(g,GOLEM)],[(1,2),(1,2)])
        self.assertEqual([x.actual for x in g.state.mana_consumption_history],[0]);self.portable(g)
    def test_moss_full_board_spends_without_buffing_old_same_name(self):
        g=self.game((MOSS,),board=(GOLEM,)+(YETI,)*6);self.play(g,MOSS)
        self.assertEqual([(e.attack,e.health)for e in self.entities(g,GOLEM)],[(1,2)]);self.assertEqual(g.state.players[1].mana,0)
        self.assertEqual([x.status for x in g.state.card_summon_history],['skipped','skipped']);self.portable(g)
    def test_moss_one_slot_only_rewards_actual_entry(self):
        g=self.game((MOSS,),board=(GOLEM,)+(YETI,)*5);self.play(g,MOSS)
        self.assertEqual([(e.attack,e.health)for e in self.entities(g,GOLEM)],[(1,2),(9,10)]);self.assertEqual(len(g.state.successful_summon_history),1)
    def test_moss_real_khadgar_extra_deliveries_share_original_payment(self):
        g=self.game((MOSS,),board=('CORE_DAL_575',));self.play(g,MOSS)
        self.assertEqual([(e.attack,e.health)for e in self.entities(g,GOLEM)],[(9,10)]*4);self.assertEqual([r.plan.total for r in g.state.card_summon_history],[2,2]);self.portable(g)
    def test_moss_automatic_cast_spends_actual_mana_without_printed_cost_payment(self):
        g=self.game(('k69.auto_moss',));self.play(g,'k69.auto_moss');self.assertEqual(g.state.mana_consumption_history[-1].actual,10)
        self.assertEqual([(e.attack,e.health)for e in self.entities(g,GOLEM)],[(11,12),(11,12)]);self.assertEqual(g.state.cast_history[-1].origin,'effect');self.portable(g)
    def test_moss_uses_mana_after_real_summon_reactions(self):
        g=self.game((MOSS,),board=('k69.watch.summon_refund',),mode='summon_refund');self.play(g,MOSS)
        self.assertEqual(g.state.mana_consumption_history[-1].actual,10);self.assertEqual([(e.attack,e.health)for e in self.entities(g,GOLEM)],[(11,12),(11,12)]);self.portable(g,'summon_refund')
    def test_waiting_restore_clone_replay_retains_complete_pair(self):
        g=self.waiting();other=self.portable(g,'wait');self.assertEqual([(e.attack,e.health)for e in self.entities(g,GOLEM)],[(1,2),(1,2)])
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual([(e.attack,e.health)for e in self.entities(g,GOLEM)],[(9,10),(9,10)]);self.portable(g,'wait')
    def test_waiting_bad_choice_rolls_back_original_debit_and_queue(self):
        g=self.waiting();saved=g.snapshot();q=g.state.pending_choice
        with self.assertRaises(IllegalAction):g.apply(SelectChoice(1,q.id,('absent',)))
        self.assertEqual(g.snapshot(),saved)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g)
    def test_original_receiver_bounce_skips_only_that_reward(self):
        g=self.waiting();self.choose(g,'bounce');self.assertEqual([(e.attack,e.health)for e in self.entities(g,GOLEM)],[(9,10)])
        self.assertEqual([(e.attack,e.health)for e in self.entities(g,GOLEM,zone='hand')],[(1,2)]);self.portable(g,'wait')
    def test_original_receiver_reentry_does_not_rebind_old_reward(self):
        g=self.waiting();first=self.entities(g,GOLEM)[0].id;self.choose(g,'reenter')
        self.assertEqual((g.state.entities[first].attack,g.state.entities[first].health),(1,2));self.assertEqual(sorted((e.attack,e.health)for e in self.entities(g,GOLEM)),[(1,2),(9,10)]);self.portable(g,'wait')
    def test_original_receiver_same_residence_transform_and_control_keep_reward(self):
        for choice in('transform','give'):
            with self.subTest(choice=choice):
                g=self.waiting();first=self.entities(g,GOLEM)[0].id;self.choose(g,choice);e=g.state.entities[first]
                self.assertEqual((e.attack,e.health),(12,13)if choice=='transform'else(9,10));self.portable(g,'wait')
    def test_later_foreign_same_name_summon_does_not_join_pair(self):
        g=self.waiting();self.choose(g,'foreign');self.assertEqual(sorted((e.attack,e.health)for e in self.entities(g,GOLEM)),[(1,2),(9,10),(9,10)]);self.portable(g,'wait')
    def test_later_independent_debit_cannot_replace_original_reward_amount(self):
        g=self.waiting();self.choose(g,'debit');self.assertEqual([r.actual for r in g.state.mana_consumption_history],[8,1])
        self.assertEqual([(e.attack,e.health)for e in self.entities(g,GOLEM)],[(9,10),(9,10)]);self.portable(g,'wait')
    def test_two_actual_casts_do_not_reward_earlier_summons_again(self):
        g=self.game((MOSS,'k69.refund',MOSS));self.play(g,MOSS);self.play(g,'k69.refund');self.play(g,MOSS)
        self.assertEqual([(e.attack,e.health)for e in self.entities(g,GOLEM)],[(9,10),(9,10),(5,6),(5,6)]);self.portable(g)
    def test_summon_or_after_debit_failure_rolls_back_whole_root(self):
        for mode in('summon_fail','mana_fail'):
            with self.subTest(mode=mode):
                g=self.game((MOSS,),board=('k69.watch.'+mode,),mode=mode);before=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,MOSS)
                self.assertEqual(g.snapshot(),before)
    def test_rehashed_waiting_pair_cannot_drop_or_replace_original_receiver(self):
        g=self.waiting()
        for values in((1,),(99999,2)):
            saved=g.snapshot();item=wire(saved['resolution_frame'],'BuffManaSummonedPair');self.assertIsNotNone(item);item['fields']['summon_ids']['tuple']=list(values)
            with self.assertRaises(SnapshotError)as caught:Game.from_snapshot(rehash(saved),registry('wait'))
            self.assertIn('Summon/Mana',str(caught.exception))
    def test_queries_are_pure_and_internal_acceptance_is_not_player_data(self):
        g=self.waiting();saved=g.snapshot()
        for p in(1,2):
            text=json.dumps(g.for_player(p).observe(),ensure_ascii=False);g.for_player(p).legal_actions()
            for name in('BuffManaSummonedPair','original','accepted','summon_ids','card_summon_history','mana_consumption_history'):
                self.assertNotIn('"'+name+'"',text)
        self.assertEqual(g.snapshot(),saved)


if __name__=='__main__':unittest.main()
