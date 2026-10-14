"""Player-owned Imbue growth, physical power lifecycle and typed history (R-100)."""
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (CardDefinition, CardClass, CardMetadata, CardType, Game, Registry,
    PlayerSetup, Scenario, PlayCard, UseHeroPower, SelectChoice, EndTurn, Zone, Keyword,
    TriggerSpec, Imbue, ImbueClass, ImbueProfile, ImbueRecord, imbue_count, imbue_value,
    ResolutionError, ResolutionLimitExceeded, IllegalAction, SnapshotError, CostSpec,
    CastSpell, SpellRepeatSpec, RewindSpec, Ruleset)
from hs_sim.engine.imbue import PLAYABLE_CLASSES
from hs_sim.engine.effects import (GainArmor, Summon, Damage, Destroy, ReturnToHand,
    Transform, Silence, ChangeControl, CopyMinion, GrantDeathrattle, ReplaceHero,
    ReplaceHeroPower, RefreshHeroPower, SetHeroPowerUses, ModifyCost, AddCostModifier,
    RequestChoice, ChoiceOption, InvokeBehavior)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


class ImbueTests(unittest.TestCase):
    def setUp(self):
        self.r=Registry('imbue-tests-v1')
        for cls in PLAYABLE_CLASSES:
            self.r.register_card(CardDefinition(cls.value,cls.value,CardType.HERO,health=30,
                metadata=CardMetadata(False,(cls,),None)))
        self.r.register_card(CardDefinition('unknown','unknown',CardType.HERO,health=30))
        self.r.register_card(CardDefinition('plain','plain',CardType.MINION,attack=2,health=4))
        for cid,amount in (('base',1),('mage-power',None),('druid-power',None)):
            self.r.register_behavior(cid,lambda c,n=amount:[GainArmor(c.player_id,
                imbue_value(c.state,c.player_id) if n is None else n)])
            self.r.register_card(CardDefinition(cid,cid,CardType.HERO_POWER,cost=2,on_use=cid))
        self.mapping={CardClass.MAGE:'mage-power',CardClass.DRUID:'druid-power',CardClass.SHAMAN:'not-adapted'}
        self.profile=self.make_profile();self.r.register_imbue_profile(self.profile)
        self.script()

    def make_profile(self,id='imbue',mapping=None):
        mapping=self.mapping if mapping is None else mapping
        return ImbueProfile(id,'v1',tuple(ImbueClass(c,mapping.get(c)) for c in sorted(PLAYABLE_CLASSES)))
    def script(self,fn=None,cid='script',kind=CardType.SPELL,**kw):
        self.r.register_behavior(cid,fn or (lambda c:[Imbue(c.player_id,c.source_id)]))
        if kind==CardType.MINION:kw.setdefault('health',4)
        self.r.register_card(CardDefinition(cid,cid,kind,on_play=cid,**kw))
    def game(self,hand=('script',),hero='mage',board=(),enemy=(),power='base',rules=None):
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=('plain',)*8,
            mana=10,max_mana=10,hero_power_card_id=power),
            PlayerSetup('druid',board=enemy,deck=('plain',)*8,mana=10,max_mana=10,hero_power_card_id='base')),seed=60),self.r,rules)
    def play(self,g,cid='script'):
        p=g.state.active_player
        eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,eid));return eid
    def power(self,g,p=1):return g.state.entities[g.state.players[p].hero_power_id]
    def use(self,g):
        p=g.state.active_player;g.apply(UseHeroPower(p,self.power(g,p).id))
    def armor(self,g,p=1):return g.state.entities[g.state.players[p].hero_id].armor
    def choose(self,g,id=None):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(id or c.options[0].id,)))
    def check(self,g):
        s=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(s,self.r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),s)
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as e:Game.from_snapshot(s,self.r)
        self.assertNotIn('digest mismatch',str(e.exception))
    def watch(self,fn,event='imbued'):
        self.r.register_behavior('watch',fn)
        self.r.register_card(CardDefinition('watch','watch',CardType.MINION,health=4,triggers=(TriggerSpec(event,'watch'),)))

    def test_first_imbue_replaces_power_and_starts_at_base_value(self):
        g=self.game();old=self.power(g).id;source=self.play(g)
        self.assertEqual(self.power(g).card_id,'mage-power')
        self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD)
        record=g.state.imbue_history[0]
        self.assertEqual((record.source_id,record.old_power_id,record.power_id),(source,old,self.power(g).id))
        self.use(g);self.assertEqual(self.armor(g),1);self.check(g)

    def test_subsequent_imbues_keep_entity_and_improve_values(self):
        g=self.game(hand=('script',)*3);self.play(g);power=self.power(g).id
        self.play(g);self.play(g);self.assertEqual(self.power(g).id,power)
        self.use(g);self.assertEqual(self.armor(g),3)
        self.assertEqual(len([e for e in g.events if e.kind=='hero_power_replaced']),1);self.check(g)

    def test_improvement_does_not_change_hero_power_cost(self):
        self.script(lambda c:[Imbue(1,c.source_id,count=8)],'eight')
        g=self.game(hand=('eight',));self.play(g,'eight')
        self.assertEqual(g.quote_cost(self.power(g).id).amount,2)
        self.use(g);self.assertEqual((self.armor(g),g.state.players[1].mana),(8,8))

    def test_both_players_have_independent_growth(self):
        self.script(lambda c:[Imbue(1,count=2),Imbue(2,count=4)],'both')
        g=self.game(hand=('both',));self.play(g,'both')
        self.assertEqual((imbue_value(g.state,1),imbue_value(g.state,2)),(2,4))
        self.assertEqual(self.power(g,2).card_id,'druid-power');self.check(g)

    def test_declared_non_imbue_class_records_no_growth(self):
        g=self.game(hero='warrior');old=self.power(g).id;self.play(g)
        self.assertEqual(self.power(g).id,old)
        self.assertEqual((imbue_count(g.state,1),imbue_count(g.state,1,applied_only=True)),(1,0))
        self.assertEqual(g.state.imbue_history[0].power_id,None)
        self.assertEqual(len([e for e in g.events if e.kind=='imbue_no_effect']),1);self.check(g)

    def test_unadapted_declared_class_errors_without_no_effect_fallback(self):
        g=self.game(hero='shaman');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'not-adapted'):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_unknown_hero_class_is_an_error(self):
        g=self.game(hero='unknown');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'known current hero class'):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_missing_initial_power_can_be_installed(self):
        g=self.game(power=None);self.play(g)
        self.assertEqual(self.power(g).card_id,'mage-power')
        self.assertIsNone(g.state.imbue_history[0].old_power_id);self.check(g)

    def test_initial_already_imbued_power_keeps_physical_identity(self):
        g=self.game(power='mage-power');old=self.power(g).id;self.use(g);self.play(g)
        self.assertEqual(self.power(g).id,old);self.assertEqual(self.power(g).uses_this_turn,1)
        self.assertEqual(imbue_value(g.state,1),1);self.check(g)

    def test_first_replacement_gives_fresh_usage_but_keeps_player_uses(self):
        g=self.game();self.use(g);self.play(g);self.use(g)
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn,2)
        self.assertEqual(self.power(g).uses_this_turn,1);self.check(g)

    def test_subsequent_growth_does_not_refresh_used_power(self):
        g=self.game(hand=('script','script'));self.play(g);self.use(g);self.play(g)
        self.assertEqual(self.power(g).uses_this_turn,1)
        with self.assertRaises(IllegalAction):self.use(g)
        self.assertEqual(imbue_value(g.state,1),2);self.check(g)

    def test_growth_preserves_instance_cost_and_limit_modifiers(self):
        self.script(lambda c:[ModifyCost(c.state.players[1].hero_power_id,CostSpec(delta=-1,
            card_types=(CardType.HERO_POWER,))),SetHeroPowerUses(1,2)],'modify')
        g=self.game(hand=('script','modify','script'));self.play(g);self.play(g,'modify');self.use(g);self.play(g)
        self.assertEqual((g.quote_cost(self.power(g).id).amount,self.power(g).use_limit),(1,2))
        self.use(g);self.assertEqual(self.armor(g),3);self.check(g)

    def test_external_power_replacement_does_not_erase_player_growth(self):
        self.script(lambda c:[ReplaceHeroPower(1,'base')],'replace')
        g=self.game(hand=('script','script','replace','script'));self.play(g);self.play(g)
        self.play(g,'replace');old=self.power(g).id;self.play(g)
        self.assertNotEqual(self.power(g).id,old);self.assertEqual(imbue_value(g.state,1),3);self.check(g)

    def test_restoring_imbued_definition_reads_existing_growth(self):
        self.script(lambda c:[ReplaceHeroPower(1,'base'),ReplaceHeroPower(1,'mage-power')],'restore')
        g=self.game(hand=('script','script','restore'));self.play(g);self.play(g);self.play(g,'restore')
        self.use(g);self.assertEqual(self.armor(g),2);self.check(g)

    def test_hero_change_uses_current_class_and_keeps_growth(self):
        self.script(lambda c:[ReplaceHero(1,'druid')],'replace')
        g=self.game(hand=('script','replace','script'));self.play(g);self.play(g,'replace');self.play(g)
        self.assertEqual(self.power(g).card_id,'druid-power');self.use(g)
        self.assertEqual(self.armor(g),2);self.assertEqual(g.state.imbue_history[-1].hero_class,CardClass.DRUID);self.check(g)

    def test_no_effect_attempts_do_not_increase_later_active_class_strength(self):
        self.script(lambda c:[ReplaceHero(1,'mage')],'replace')
        g=self.game(hero='warrior',hand=('script','replace','script'));self.play(g);self.play(g,'replace');self.play(g)
        self.assertEqual((imbue_count(g.state,1),imbue_value(g.state,1)),(2,1));self.check(g)

    def test_multiple_uses_requery_class_after_each_reaction(self):
        self.watch(lambda c:[ReplaceHero(1,'druid')] if imbue_count(c.state,1)==1 else [])
        self.script(lambda c:[Imbue(1,c.source_id,count=2)],'twice')
        g=self.game(hand=('twice',),board=('watch',));self.play(g,'twice')
        self.assertEqual([x.hero_class for x in g.state.imbue_history],[CardClass.MAGE,CardClass.DRUID])
        self.assertEqual(self.power(g).card_id,'druid-power');self.check(g)

    def test_replacement_observer_sees_committed_growth(self):
        self.watch(lambda c:[GainArmor(1,imbue_count(c.state,1))],event='hero_power_replaced')
        g=self.game(board=('watch',));self.play(g);self.assertEqual(self.armor(g),1);self.check(g)

    def test_progress_survives_source_death_silence_bounce_transform(self):
        for op in (Destroy,Silence,ReturnToHand,lambda i:Transform(i,'plain')):
            with self.subTest(op=op):
                self.setUp();self.script(cid='body',kind=CardType.MINION)
                self.script(lambda c:[op(c.state.players[1].board[0])],'change')
                g=self.game(hand=('body','change'));self.play(g,'body');self.play(g,'change')
                self.assertEqual(imbue_count(g.state,1),1);self.use(g);self.assertEqual(self.armor(g),1);self.check(g)

    def test_replayed_battlecry_is_another_imbue(self):
        self.script(cid='body',kind=CardType.MINION)
        self.script(lambda c:[ReturnToHand(c.state.players[1].board[0])],'bounce')
        g=self.game(hand=('body','bounce'));self.play(g,'body');self.play(g,'bounce');self.play(g,'body')
        self.assertEqual(imbue_count(g.state,1),2);self.check(g)

    def test_summon_and_copy_do_not_execute_imbue_battlecry(self):
        self.script(cid='body',kind=CardType.MINION)
        self.script(lambda c:[Summon(1,'body')],'summon')
        self.script(lambda c:[CopyMinion(c.state.players[1].board[0],1)],'copy')
        g=self.game(hand=('summon','copy'));self.play(g,'summon');self.play(g,'copy')
        self.assertEqual(imbue_count(g.state,1),0);self.check(g)

    def test_deathrattle_imbues_current_controller(self):
        self.r.register_behavior('rattle',lambda c:[Imbue(c.player_id,c.source_id)])
        self.r.register_card(CardDefinition('body','body',CardType.MINION,health=3,deathrattle='rattle'))
        self.script(lambda c:[ChangeControl(c.state.players[1].board[0],2)],'steal')
        self.script(lambda c:[Destroy(c.state.players[2].board[0])],'kill')
        g=self.game(hand=('steal','kill'),board=('body',));self.play(g,'steal');self.play(g,'kill')
        self.assertEqual((imbue_count(g.state,1),imbue_count(g.state,2)),(0,1));self.check(g)

    def test_silenced_deathrattle_does_not_imbue(self):
        self.r.register_behavior('rattle',lambda c:[Imbue(c.player_id,c.source_id)])
        self.r.register_card(CardDefinition('body','body',CardType.MINION,health=3,deathrattle='rattle'))
        self.script(lambda c:[Silence(c.state.players[1].board[0]),Destroy(c.state.players[1].board[0])],'kill')
        g=self.game(hand=('kill',),board=('body',));self.play(g,'kill')
        self.assertEqual(imbue_count(g.state,1),0);self.check(g)

    def test_source_death_after_first_imbue_does_not_cancel_remaining_uses(self):
        self.watch(lambda c:[Destroy(c.event.source_id)] if imbue_count(c.state,1)==1 else [])
        self.script(lambda c:[Imbue(1,c.source_id,count=2)],'body',kind=CardType.MINION)
        g=self.game(hand=('body',),board=('watch',));source=self.play(g,'body')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(imbue_count(g.state,1),2);self.check(g)

    def test_lethal_reaction_stops_remaining_imbues(self):
        self.watch(lambda c:[Damage(c.state.players[2].hero_id,99)])
        self.script(lambda c:[Imbue(1,c.source_id,count=3)],'many')
        g=self.game(hand=('many',),board=('watch',));self.play(g,'many')
        self.assertEqual((imbue_count(g.state,1),g.state.winner),(1,1));self.check(g)

    def test_bounded_repetition_rejects_excess_before_mutation(self):
        self.script(lambda c:[Imbue(1,count=1001)],'many')
        g=self.game(hand=('many',),rules=Ruleset(max_resolution_steps=1000));before=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g,'many')
        self.assertEqual(g.snapshot(),before)

    def test_zero_imbue_is_inert_without_profile_lookup(self):
        self.script(lambda c:[Imbue(1,c.source_id,count=0,profile_id='missing')],'zero')
        g=self.game(hand=('zero',));old=self.power(g).id;self.play(g,'zero')
        self.assertEqual((self.power(g).id,imbue_count(g.state,1)),(old,0));self.check(g)

    def test_zero_still_validates_source(self):
        self.script(lambda c:[Imbue(1,99999,count=0)],'bad');g=self.game(hand=('bad',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)

    def test_pending_effect_restores_before_imbue(self):
        self.script(lambda c:[RequestChoice(1,(ChoiceOption('ok','ok',(Imbue(1,c.source_id,2),)),))],'choose')
        g=self.game(hand=('choose',));self.play(g,'choose');self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(imbue_value(g.state,1),2);self.check(g)

    def test_mid_repetition_choice_restores_without_recounting(self):
        self.watch(lambda c:[RequestChoice(2,(ChoiceOption('ok','ok'),))])
        self.script(lambda c:[Imbue(1,c.source_id,2)],'twice')
        g=self.game(hand=('twice',),board=('watch',));self.play(g,'twice')
        self.assertEqual(imbue_count(g.state,1),1);self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):
            while match.state.pending_choice:self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(imbue_count(g.state,1),2);self.check(g)

    def test_action_error_rolls_back_progress_and_replacement(self):
        self.script(lambda c:[Imbue(1),Summon(1,'missing')],'bad')
        g=self.game(hand=('bad',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)

    def test_choice_error_rolls_back_only_choice_submission(self):
        self.r.register_behavior('late.fail',lambda c:[Summon(1,'missing')])
        self.script(lambda c:[RequestChoice(1,(ChoiceOption('ok','ok',(
            Imbue(1,c.source_id),InvokeBehavior('late.fail',c.source_id,1))),))],'choose')
        g=self.game(hand=('choose',));self.play(g,'choose');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_automatic_spell_imbues_without_extra_hand_play(self):
        self.script(lambda c:[CastSpell(1,'script',c.source_id)],'auto')
        g=self.game(hand=('auto',));self.play(g,'auto')
        self.assertEqual((imbue_count(g.state,1),len(g.state.play_history)),(1,1));self.check(g)

    def test_spell_repeat_counts_effect_uses_not_plays(self):
        self.r.register_card(CardDefinition('repeat','repeat',CardType.MINION,health=4,
            spell_repeats=(SpellRepeatSpec(class_mode='any'),)))
        g=self.game(board=('repeat',));self.play(g)
        self.assertEqual((imbue_count(g.state,1),len(g.state.play_history)),(2,1));self.check(g)

    def test_rewind_reverts_progress_and_power_identity_before_retry(self):
        self.script(cid='retry',keywords=(Keyword.REWIND,),rewind=RewindSpec())
        g=self.game(hand=('retry',));self.play(g,'retry');first=self.power(g).id;self.check(g)
        self.choose(g,'retry');self.assertEqual(imbue_count(g.state,1),1)
        self.assertNotEqual(self.power(g).id,first);self.assertNotIn(first,g.state.entities);self.check(g)

    def test_kept_rewind_preserves_growth_once(self):
        self.script(cid='retry',keywords=(Keyword.REWIND,),rewind=RewindSpec())
        g=self.game(hand=('retry',));self.play(g,'retry');self.choose(g,'keep')
        self.assertEqual(imbue_count(g.state,1),1);self.check(g)

    def test_power_effect_captures_level_before_nested_growth(self):
        self.watch(lambda c:[Imbue(1)] if c.event.kind=='hero_power_started' else [],event='hero_power_started')
        g=self.game(board=('watch',));self.play(g);self.use(g)
        self.assertEqual(imbue_count(g.state,1),2)
        self.assertEqual(self.armor(g),1);self.check(g)

    def test_corrupt_history_fields_and_identity_rejected(self):
        g=self.game();self.play(g)
        for key,value in (('count_before',1),('applied_before',1),('profile_version','bad'),('hero_class','druid'),
                          ('source_id',99999),('power_id',g.state.players[1].hero_id),('old_power_id',99999),
                          ('power_card_id',None),('turn',99),('action',99),('id',2)):
            with self.subTest(key=key):
                s=g.snapshot();s['state']['imbue_history'][0][key]=value;self.reject(s)

    def test_missing_or_malformed_history_rejected(self):
        g=self.game();self.play(g)
        for value in ({},[{}],None):
            with self.subTest(value=value):
                s=g.snapshot();s['state']['imbue_history']=value;self.reject(s)
        s=g.snapshot();del s['state']['imbue_history'];self.reject(s)

    def test_pending_unknown_profile_rejected(self):
        self.script(lambda c:[RequestChoice(1,(ChoiceOption('ok','ok',(Imbue(1),)),))],'choose')
        g=self.game(hand=('choose',));self.play(g,'choose');s=g.snapshot()
        def corrupt(v):
            if isinstance(v,dict):
                if v.get('type','').endswith('.Imbue'):v['fields']['profile_id']='missing'
                for child in v.values():corrupt(child)
            elif isinstance(v,list):
                for child in v:corrupt(child)
        corrupt(s);self.reject(s)

    def test_profile_switch_with_existing_progress_is_rejected(self):
        self.r.register_imbue_profile(self.make_profile('other'))
        self.script(lambda c:[Imbue(1,profile_id='other')],'other')
        g=self.game(hand=('script','other'));self.play(g);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'switch Imbue profiles'):self.play(g,'other')
        self.assertEqual(g.snapshot(),before)

    def test_profile_version_and_mappings_enter_fingerprint(self):
        base=self.r.fingerprint();self.r.register_imbue_profile(self.make_profile('second'))
        self.assertNotEqual(self.r.fingerprint(),base)
        g=self.game();self.play(g)
        with self.assertRaises(ValueError):self.r.register_imbue_profile(self.make_profile('third'))

    def test_invalid_profiles_and_effect_arguments_rejected(self):
        for fn in (lambda:Imbue(True),lambda:Imbue(1,count=True),lambda:Imbue(1,count=-1),
                   lambda:Imbue(1,profile_id=''),lambda:ImbueClass(CardClass.NEUTRAL,None),
                   lambda:ImbueProfile('x','v',()),lambda:replace(self.profile,classes=list(self.profile.classes)),
                   lambda:replace(self.profile,classes=self.profile.classes[:-1]+self.profile.classes[:1])):
            with self.subTest(fn=fn),self.assertRaises(ValueError):fn()
        with self.assertRaises(ValueError):self.r.register_imbue_profile(self.profile)

    def test_profile_non_power_definition_rejected_at_freeze(self):
        self.r.register_imbue_profile(self.make_profile('bad',{CardClass.MAGE:'plain'}))
        with self.assertRaisesRegex(ValueError,'hero power definitions'):self.r.freeze()

    def test_public_progress_and_logs_exclude_internal_history(self):
        g=self.game();port=g.for_player(1);listing=port.legal_actions()
        action=next(a for a in listing['actions'] if a['type']=='play_card')
        self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted'])
        for viewer in (1,2):
            view=g.observe(viewer);own=next(p for p in view['players'] if p['id']==1)
            self.assertEqual(own['imbue'],{'count':1,'level':1})
            events=g.player_events(viewer);event=next(e for e in events if e['kind']=='imbued')
            self.assertEqual((event['amount'],event['imbue']),(1,{'level':1}))
            text=json.dumps((view,events))
            for key in ('imbue_history','profile_version','old_power_id','applied_before'):self.assertNotIn(key,text)
        self.check(g)

    def test_explicit_base_and_step_do_not_mutate_shared_count(self):
        g=self.game(hand=('script',)*3)
        for _ in range(3):self.play(g)
        self.assertEqual(imbue_value(g.state,1,base=3,step=2),7)
        self.assertEqual(imbue_count(g.state,1),3)
        for fn in (lambda:imbue_value(g.state,1,base=True),lambda:imbue_count(g.state,1,applied_only=1)):
            with self.assertRaises(ValueError):fn()


class ImbueRepresentativeTests(unittest.TestCase):
    def setUp(self):
        from hs_sim.engine.representative import build_registry
        self.r=build_registry()
    def game(self,hand=('EDR_852',),hero='HERO_08',board=(),power='HERO_08bp'):
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,
            deck=('CS2_182',)*4,hero_power_card_id=power,mana=10,max_mana=10),
            PlayerSetup('HERO_01',deck=('CS2_182',)*4)),seed=60),self.r)
    def play(self,g,cid='EDR_852',target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target));return eid
    def use(self,g):g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
    def check(self,g):
        s=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(s,self.r).snapshot(),s)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),s)
    def tokens(self,g,cid):return [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id==cid]

    def test_frozen_sources_and_basic_druid_power(self):
        knight=self.r.card('EDR_852');drake=self.r.card('EDR_451')
        self.assertEqual((knight.cost,knight.attack,knight.health),(2,2,3))
        self.assertEqual((drake.cost,drake.attack,drake.health),(3,3,4))
        self.assertEqual(self.r.card('HERO_06').initial_hero_power,'HERO_06bp')
        g=self.game(hand=(),hero='HERO_06',power='HERO_06bp');self.use(g)
        hero=g.state.entities[g.state.players[1].hero_id]
        self.assertEqual((hero.attack,hero.armor),(1,1));self.check(g)

    def test_druid_growth_keeps_old_token_and_power_instance(self):
        g=self.game(hand=('EDR_852',)*2,hero='HERO_06',power='HERO_06bp')
        self.play(g);self.use(g);power=g.state.players[1].hero_power_id
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g);self.use(g)
        self.assertEqual([(e.attack,e.max_health) for e in self.tokens(g,'EDR_847pt2')],[(1,1),(2,2)])
        self.assertEqual(g.state.players[1].hero_power_id,power);self.check(g)

    def test_mage_grows_summon_and_damage_without_spell_power(self):
        g=self.game(hand=('EDR_852',)*3,board=('EX1_012',))
        for _ in range(3):self.play(g)
        self.use(g)
        self.assertEqual(len(self.tokens(g,'EDR_851t')),3)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,27)
        hits=[e for e in g.events if e.kind=='damage_dealt']
        self.assertEqual(len(hits),3)
        self.assertTrue(all(dict(e.data)['damage_kind']=='hero_power' for e in hits));self.check(g)

    def test_mage_full_board_still_deals_damage(self):
        g=self.game(board=('CS2_182',)*6);self.play(g);self.use(g)
        self.assertFalse(self.tokens(g,'EDR_851t'))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,29);self.check(g)

    def test_druid_full_board_disallows_use_without_payment(self):
        g=self.game(hero='HERO_06',power='HERO_06bp',board=('CS2_182',)*6);self.play(g)
        before=g.snapshot()
        with self.assertRaises(IllegalAction):self.use(g)
        self.assertEqual(g.snapshot(),before)
        self.assertFalse(any(a['type']=='use_hero_power' for a in g.for_player(1).legal_actions()['actions']))

    def test_goldpetal_battlecry_and_deathrattle_use_current_player_class(self):
        g=self.game(hand=('EDR_451','CS2_029'));drake=self.play(g,'EDR_451')
        self.play(g,'CS2_029',drake)
        self.assertEqual(imbue_count(g.state,1),2)
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,'EDR_851p')
        self.assertEqual([r.source_id for r in g.state.imbue_history],[drake,drake]);self.check(g)

    def test_goldpetal_summoning_triggers_only_later_deathrattle(self):
        g=self.game(hand=('CS2_029',),board=('EDR_451',));drake=g.state.players[1].board[0]
        self.assertEqual(imbue_count(g.state,1),0);self.play(g,'CS2_029',drake)
        self.assertEqual(imbue_count(g.state,1),1);self.check(g)

    def test_all_eight_named_imbue_powers_are_explicit_adapters(self):
        from hs_sim.engine.representative import IMBUE_CLASS_POWERS
        self.assertEqual(len(IMBUE_CLASS_POWERS),8)
        for cid in IMBUE_CLASS_POWERS.values():self.assertEqual(self.r.card(cid).kind,CardType.HERO_POWER)

    def test_three_declared_classes_have_no_power_or_growth(self):
        classes=(CardClass.DEMON_HUNTER,CardClass.WARLOCK,CardClass.WARRIOR)
        for cls in classes:
            self.r.register_card(CardDefinition(cls.value,cls.value,CardType.HERO,health=30,
                metadata=CardMetadata(False,(cls,),None)))
        for cls in classes:
            with self.subTest(cls=cls):
                g=self.game(hero=cls.value);old=g.state.players[1].hero_power_id;self.play(g)
                self.assertEqual((g.state.players[1].hero_power_id,imbue_count(g.state,1,applied_only=True)),(old,0))
                self.check(g)

    def test_real_example_through_player_ports(self):
        from examples.imbue_growth import run
        g,snapshot=run();self.assertEqual(snapshot['schema_version'],266)
        self.assertEqual([r.hero_class for r in g.state.imbue_history],
                         [CardClass.DRUID,CardClass.MAGE,CardClass.DRUID])

    def test_split_damage_kind_survives_pending_choice_and_restore(self):
        from hs_sim.engine import DamageKind
        from hs_sim.engine.effects import SplitDamage
        self.r.register_behavior('typed',lambda c:[RequestChoice(1,(ChoiceOption('ok','ok',
            (SplitDamage(2,2,c.source_id,kind=DamageKind.HERO_POWER),)),))])
        self.r.register_card(CardDefinition('typed','typed',CardType.SPELL,on_play='typed'))
        g=self.game(hand=('typed',));self.play(g,'typed');self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):
            c=match.state.pending_choice;match.apply(SelectChoice(1,c.id,('ok',)))
            self.assertTrue(all(dict(e.data)['damage_kind']=='hero_power' for e in match.events if e.kind=='damage_dealt'))
        self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)

    def test_split_damage_rejects_spell_combat_and_invalid_kind(self):
        from hs_sim.engine import DamageKind
        from hs_sim.engine.effects import SplitDamage
        for kind in (DamageKind.SPELL,DamageKind.COMBAT,DamageKind.FATIGUE,'hero_power',None):
            with self.subTest(kind=kind),self.assertRaises(ValueError):SplitDamage(2,2,kind=kind)


if __name__=='__main__':unittest.main()
