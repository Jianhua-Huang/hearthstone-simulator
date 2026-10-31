"""Real paid entries, original histories and finite public-provider boundaries."""
from functools import lru_cache
from copy import deepcopy
import unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_history_resource_providers as native
from hs_sim.engine import Attack,EndTurn,Game,PlayerSetup,Scenario,UseMinionAbility
from hs_sim.engine.effects import (AddToHand,Buff,ChoiceOption,Damage,Destroy,Freeze,GainArmor,GrantKeyword,
    InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import (ActivatedAbilitySpec,AttackPolicySpec,CardDefinition,CardType,CostSpec,
    DamageKind,HealthFlow,HealthLayer,HealthOp,HealthRule,Keyword,LimitedTriggerSpec,PaymentType,Resource,
    SpellSchool,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.pools import GenerationContext,PoolCard,generation_candidates
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.attack_policies import attack_limit
from hs_sim.engine.costs import local_cost
from hs_sim.local_pool_format import build_cn37_local_pool_format

BEARON,KARGAL,SAURFANG,ZOK,CHEN,AKAMA,ASKARA,MALADAAR,OTHAAR,TALGATH=native.ROOTS
STAG,LOOKOUT,FAN,SNOW,FAR,CROSS,MORSHAN,GRUNT=native.DEPENDENCIES
P='k731.'
A,D,D_BC,D_BOUNCE,TITAN=(P+x for x in('a','draenei','draenei_cry','draenei_bounce','titan'))
NOOP,FROST,FIRE,HIGH,KILL,BOUNCE,HUSH,HIT,SHIELD,WF,GAIN,SUMMON_D,WAIT_SPELL,FAIL=(P+x for x in
    ('noop','frost','fire','high','kill','bounce','hush','hit','shield','windfury','hero_gain','summon_d','wait_spell','fail'))
FREEZE_SPELL=P+'freeze'
NINE,TEN,TWELVE=(P+x for x in('nine','ten','twelve'))
WAIT_COPY,WAIT_ATTACK,WAIT_GAIN=(P+x for x in('wait_copy','wait_attack','wait_gain'))
CTX=GenerationContext(P+'fixture','experimental')


@lru_cache(None)
def full(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer',host=False):
    h=full(role);r=h.registry if host else defaults()
    if not host:
        for cid in native.EXISTING+('BAR_021','BAR_078'):
            if cid in r.cards:continue
            card=h.registry.card(cid)
            for bid in(card.on_play,card.battlecry,card.combo,card.deathrattle):
                if bid is not None:r.register_behavior(bid,h.registry.behavior(bid))
            for t in card.triggers:r.register_behavior(t.behavior_id,h.registry.behavior(t.behavior_id))
            for t in card.limited_triggers:
                r.register_behavior(t.behavior_id,h.registry.behavior(t.behavior_id))
                if t.condition_id not in r._trigger_conditions:r.register_trigger_condition(t.condition_id,h.registry.trigger_condition(t.condition_id))
            if card.target_rule not in r._target_rules:r.register_target_rule(card.target_rule,h.registry.target_rule(card.target_rule))
            if card.use_rule not in r._use_rules:r.register_use_rule(card.use_rule,h.registry.use_rule(card.use_rule))
            r.register_card(card);r.register_pool_card(h.registry.pool_card(cid))
        native.register_past_history_resource_providers(r)
    plain=metadata(collectible=False,tribes=());draenei=metadata(collectible=False,tribes=('draenei',))
    r.register_behavior(D_BC,lambda c:(Buff(c.source_id,3,2,c.source_id),GainArmor(c.player_id,3)))
    r.register_behavior(D_BOUNCE,lambda c:(ReturnToHand(c.source_id),))
    r.register_behavior(P+'titan',lambda c:(GainArmor(c.player_id,1),))
    for cid,kw in((A,{}),(D,{}),(D_BC,dict(battlecry=D_BC)),(D_BOUNCE,dict(battlecry=D_BOUNCE)),
            (TITAN,dict(keywords=(Keyword.TITAN,),activated_abilities=tuple(ActivatedAbilitySpec(str(i),P+'titan')for i in range(3))))):
        card=CardDefinition(cid,cid,CardType.MINION,cost=2,attack=2,health=8,metadata=draenei if cid in(D,D_BC,D_BOUNCE)else plain,**kw)
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    def choice(c):
        options=(ChoiceOption('continue','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('fault','Fault',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))))
        original=c.state.entities.get(c.event.source_id)if c.event is not None else None
        if original is not None and original.kind==CardType.MINION:
            options+=(ChoiceOption('bounce','Return original played minion',(ReturnToHand(original.id),)),)
        ask=next((c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==ASKARA),None)
        if ask is not None:options+=(ChoiceOption('kill_source','Destroy original Askara',(Destroy(ask.id,c.source_id),)),)
        return(RequestChoice(c.player_id,options,c.source_id),)
    bodies={NOOP:lambda c:(),FROST:lambda c:(),FIRE:lambda c:(),HIGH:lambda c:(),NINE:lambda c:(),TEN:lambda c:(),TWELVE:lambda c:(),
        KILL:lambda c:(Destroy(c.target_id,c.source_id),),BOUNCE:lambda c:(ReturnToHand(c.target_id),),HUSH:lambda c:(Silence(c.target_id),),
        HIT:lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),),SHIELD:lambda c:(GrantKeyword(c.target_id,Keyword.DIVINE_SHIELD,c.source_id),),
        WF:lambda c:(GrantKeyword(c.target_id,Keyword.WINDFURY,c.source_id),),FREEZE_SPELL:lambda c:(Freeze(c.target_id,c.source_id),),
        GAIN:lambda c:(Buff(c.state.players[c.player_id].hero_id,5,0,c.source_id),GainArmor(c.player_id,7),Damage(c.state.players[c.player_id].hero_id,3,c.source_id)),
        SUMMON_D:lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(D),),SummonCause.capture(c)),),WAIT_SPELL:choice}
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K731 deliberate rollback')))
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        target=TargetSpec()if cid in(KILL,BOUNCE,HUSH,HIT,SHIELD,WF,FREEZE_SPELL)else None
        card=CardDefinition(cid,cid,CardType.SPELL,cost={HIGH:7,NINE:9,TEN:10,TWELVE:12}.get(cid,0),on_play=cid,targeting=target,
            spell_school=SpellSchool.FROST if cid==FROST else SpellSchool.FIRE if cid==FIRE else None,metadata=plain)
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    def copy_condition(c):
        if c.event is None or c.event.kind!='card_played':return False
        e=c.state.entities.get(c.event.source_id)
        return e is not None and e.card_id in(D,D_BC,D_BOUNCE)
    def attack_condition(c):
        e=None if c.event is None else c.state.entities.get(c.event.source_id)
        return e is not None and e.card_id==AKAMA
    for cid,event,condition in((WAIT_COPY,'card_played',copy_condition),(WAIT_ATTACK,'damage_dealt',attack_condition),
            (WAIT_GAIN,'hero_attack_gained',lambda c:c.event.player_id==c.player_id)):
        r.register_behavior(cid,choice);r.register_trigger_condition(cid,condition)
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=30,metadata=plain,
            limited_triggers=(LimitedTriggerSpec(event,cid,cid),)))
    r.validate();return r,h.context if host else CTX


class HistoryResourceProviderTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(lambda mode,role:fixture(role,mode=='host')[0])
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=None,enemy_deck=None,corpses=20,host=False,watch=None,hero='HERO_08'):
        self.mode='host'if host else'small';r,ctx=fixture('writer',host)
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=(A,)*12 if deck is None else deck,
            mana=40,max_mana=40,mana_cap=40,armor=500,corpses=corpses,weapon_card_id=watch),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(A,)*12 if enemy_deck is None else enemy_deck,
            mana=40,max_mana=40,mana_cap=40,armor=500)),seed=731,generation_context=ctx),r)
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def faces(self,g,p=1,zone='board'):return[g.state.entities[i].card_id for i in getattr(g.state.players[p],zone)]
    def attack(self,g,cid,*,p=1,target=None):g.apply(Attack(p,self.unit(g,cid,p).id,self.hero(g,3-p).id if target is None else target))
    def own_turn(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def fault(self,g):
        old=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),old)

    def test_complete_twenty_one_rows_forty_primary_faces_and_independent_eighteen_faces(self):
        d=native.load_batch();self.assertEqual(len(d['official_observations']),40);self.assertEqual(len(d['original_candidate_ids']),732)
        self.assertEqual(sum(len(d[k])for k in('cards','dependencies','existing_dependencies','evidence_only')),21)
        expected=((7,6,6),(7,5,5),(7,5,4),(6,6,6),(3,2,5),(5,3,6),(4,4,4),(6,5,5),(3,3,3),(3,3,3),
            (3,3,4),(5,5,5),(1,1,1),(5,5,5),(2,2,3),(4,4,6),(3,3,5),(2,2,2))
        for cid,stats in zip(native.ROOTS+native.DEPENDENCIES,expected):
            c=fixture()[0].card(cid);self.assertEqual((c.cost,c.attack,c.health),stats);self.assertEqual(c,fixture('independent-reader')[0].card(cid))
        self.assertEqual(tuple(d['validation_provider_ids']),native.POSTS)

    def test_exact_display_pins_preserve_static_words_and_reject_modified_source_or_primary(self):
        from tools import card_batch as cb
        d=native.load_batch()
        for cid in(BEARON,ZOK):
            raw=next(x['record']for x in d['cards']if x['record']['id']==cid)
            for o in d['official_observations']:
                if o['card_id']!=cid:continue
                cb.check_face(raw,o['face'],o['locale'],d['display_normalizations'][cid])
                changed=deepcopy(raw);changed['attack']+=1
                with self.assertRaises(ValueError):cb.check_face(changed,o['face'],o['locale'],d['display_normalizations'][cid])
                face=deepcopy(o['face']);face['text']+=' extra rule'
                with self.assertRaises(ValueError):cb.check_face(raw,face,o['locale'],d['display_normalizations'][cid])

    def test_all_ten_current_host_roots_and_eight_actual_dependency_paid_entries(self):
        for cid in native.ROOTS+native.DEPENDENCIES:
            g=self.game((cid,),host=True);sid=self.play(g,cid)
            self.assertTrue(g.state.play_history[0].completed);self.assertEqual(g.state.play_history[0].source_id,sid)

    def test_Bearon_counts_all_own_actual_Frost_casts_and_not_other_schools(self):
        g=self.game((FROST,FROST,FIRE,BEARON));self.play(g,FROST);self.play(g,FIRE);self.play(g,FROST);self.play(g,BEARON)
        self.assertEqual(self.faces(g).count(STAG),2);self.portable(g)

    def test_Bearon_does_not_count_opponent_casts(self):
        g=self.game((FROST,BEARON),enemy_hand=(FROST,));g.apply(EndTurn(1));self.play(g,FROST,player=2);g.apply(EndTurn(2))
        self.play(g,FROST);self.play(g,BEARON);self.assertEqual(self.faces(g).count(STAG),1)

    def test_Stag_actual_combat_freezes_damaged_hero_and_silence_removes_text(self):
        g=self.game((HUSH,),board=(STAG,));self.attack(g,STAG);self.assertTrue(self.hero(g,2).frozen)
        self.play(g,HUSH,self.unit(g,STAG).id);self.own_turn(g);self.attack(g,STAG);self.portable(g)

    def test_Stag_zero_damage_shield_does_not_freeze(self):
        g=self.game((SHIELD,),board=(STAG,),enemy=(A,));target=self.unit(g,A,2).id;self.play(g,SHIELD,target)
        self.attack(g,STAG,target=target);self.assertFalse(g.state.entities[target].frozen)

    def test_Kargal_counts_actual_repeat_entries_and_excludes_scenario_initial_board(self):
        g=self.game((MORSHAN,BOUNCE,KARGAL),board=(FAR,));sid=self.play(g,MORSHAN);self.play(g,BOUNCE,sid);self.play(g,MORSHAN);self.play(g,KARGAL)
        self.assertEqual(self.faces(g).count(LOOKOUT),2);self.portable(g)

    def test_Kargal_excludes_opponent_entries_and_Grunts(self):
        g=self.game((GRUNT,KARGAL),enemy_hand=(FAR,MORSHAN));g.apply(EndTurn(1));self.play(g,FAR,player=2);self.play(g,MORSHAN,player=2);g.apply(EndTurn(2))
        self.play(g,GRUNT);self.play(g,KARGAL);self.assertNotIn(LOOKOUT,self.faces(g))

    def test_Far_Post_actual_opponent_draw_local_cost_increase_and_ten_cap(self):
        g=self.game(board=(FAR,),enemy_deck=(HIGH,A));g.apply(EndTurn(1))
        card=self.entity(g,HIGH,2);self.assertEqual(local_cost(card)[0],8)
        self.assertEqual(self.hero(g).armor,500);self.portable(g)

    def test_Far_Post_local_nine_reaches_ten_and_never_lowers_ten_or_twelve(self):
        for cid,expected in((NINE,10),(TEN,10),(TWELVE,12)):
            g=self.game(board=(FAR,),enemy_deck=(cid,));g.apply(EndTurn(1));self.assertEqual(local_cost(self.entity(g,cid,2))[0],expected)

    def test_Crossroads_Post_buffs_own_all_current_minions_before_enemy_spell_payload(self):
        g=self.game(board=(CROSS,A),enemy_hand=(HIT,));g.apply(EndTurn(1));target=self.unit(g,A).id;self.play(g,HIT,target,player=2)
        self.assertEqual((g.state.entities[target].attack,g.state.entities[target].max_health,g.state.entities[target].health),(3,9,7));self.assertEqual(self.unit(g,CROSS).attack,5)

    def test_Morshan_Post_actual_opponent_minion_play_and_cannot_attack(self):
        g=self.game((WF,),board=(MORSHAN,),enemy_hand=(D,));self.play(g,WF,self.unit(g,MORSHAN).id)
        with self.assertRaises(IllegalAction):self.attack(g,MORSHAN)
        g.apply(EndTurn(1));self.play(g,D,player=2);self.assertEqual(self.faces(g).count(GRUNT),1);self.portable(g)

    def test_Saurfang_resurrects_two_actual_native_Frenzy_deaths_then_damages_other_minions(self):
        g=self.game((KILL,KILL,KILL,SAURFANG),board=('BAR_021','BAR_078',A),enemy=(A,))
        for cid in('BAR_021','BAR_078',A):self.play(g,KILL,self.unit(g,cid).id)
        self.play(g,SAURFANG);self.assertEqual(len(g.state.resurrection_history),2)
        self.assertEqual({g.state.death_history[x.death_id-1].card_id for x in g.state.resurrection_history},{'BAR_021','BAR_078'})
        self.assertEqual(self.unit(g,SAURFANG).health,4);self.assertTrue(any(e.kind=='limited_trigger_used'for e in g.events));self.portable(g)

    def test_Saurfang_printed_Frenzy_survives_silenced_death_qualification(self):
        g=self.game((HUSH,KILL,SAURFANG),board=('BAR_021',),enemy=('BAR_078',));sid=self.unit(g,'BAR_021').id
        self.play(g,HUSH,sid);self.play(g,KILL,sid);self.play(g,SAURFANG);self.assertEqual(len(g.state.resurrection_history),1)

    def test_Zok_uses_actual_turn_attack_and_armor_gains_not_current_remaining_armor(self):
        g=self.game((GAIN,ZOK));self.play(g,GAIN);self.assertEqual(self.hero(g).armor,504);self.play(g,ZOK)
        fans=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==FAN]
        self.assertEqual([(e.attack,e.health)for e in fans],[(6,8),(6,8)])
        self.assertEqual([(r.before,r.amount,r.after)for r in g.state.hero_attack_gain_history],[(0,5,5)]);self.portable(g)

    def test_Hero_Attack_gain_is_committed_before_public_listener_and_restores_with_original_events(self):
        g=self.game((GAIN,ZOK),watch=WAIT_GAIN);self.play(g,GAIN);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.hero_attack_gain_history[-1].amount,5);self.fault(g);g=self.portable(g);self.choose(g);self.play(g,ZOK)
        self.assertEqual([(g.state.entities[i].attack,g.state.entities[i].health)for i in g.state.players[1].board if g.state.entities[i].card_id==FAN],[(6,9),(6,9)])
        self.portable(g)

    def test_Hero_Attack_gain_history_cannot_be_truncated_after_rehashing(self):
        from hs_sim.engine.serialization import canonical_hash
        g=self.game((GAIN,));self.play(g,GAIN);bad=deepcopy(g.snapshot());bad['state']['hero_attack_gain_history']=[]
        bad['state_hash']=canonical_hash({k:v for k,v in bad.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaisesRegex(ValueError,'Hero Attack gains lost their full original event inventory'):
            Game.from_snapshot(bad,fixture('independent-reader')[0])

    def test_Zok_excludes_previous_turn_gains(self):
        g=self.game((GAIN,ZOK));self.play(g,GAIN);self.own_turn(g);self.play(g,ZOK)
        self.assertEqual([(g.state.entities[i].attack,g.state.entities[i].health)for i in g.state.players[1].board if g.state.entities[i].card_id==FAN],[(1,1),(1,1)])

    def test_Chen_counts_only_observed_casts_and_repeats_every_three(self):
        g=self.game((FROST,)*8+(CHEN,));self.play(g,FROST);self.play(g,FROST);self.play(g,CHEN)
        for _ in range(2):self.play(g,FROST)
        self.assertNotIn(SNOW,self.faces(g));self.play(g,FROST);self.assertEqual(self.faces(g).count(SNOW),1)
        for _ in range(3):self.play(g,FROST)
        self.assertEqual(self.faces(g).count(SNOW),2);self.portable(g)

    def test_Chen_partial_cycle_resets_on_actual_turn_boundary(self):
        g=self.game((CHEN,)+(FROST,)*5);self.play(g,CHEN);self.play(g,FROST);self.play(g,FROST);self.own_turn(g)
        self.play(g,FROST);self.assertNotIn(SNOW,self.faces(g));self.play(g,FROST);self.play(g,FROST);self.assertEqual(self.faces(g).count(SNOW),1)

    def test_Chen_opponent_casts_and_silence_do_not_advance_old_counter(self):
        g=self.game((CHEN,HUSH,FROST,FROST,FROST),enemy_hand=(FROST,)*3);sid=self.play(g,CHEN);g.apply(EndTurn(1))
        for _ in range(3):self.play(g,FROST,player=2)
        g.apply(EndTurn(2));self.assertNotIn(SNOW,self.faces(g));self.play(g,HUSH,sid)
        for _ in range(3):self.play(g,FROST)
        self.assertNotIn(SNOW,self.faces(g))

    def test_Chen_return_and_replay_start_a_new_counter(self):
        g=self.game((CHEN,BOUNCE)+(FROST,)*4);sid=self.play(g,CHEN);self.play(g,FROST);self.play(g,BOUNCE,sid);self.play(g,CHEN)
        self.play(g,FROST);self.play(g,FROST);self.assertNotIn(SNOW,self.faces(g));self.play(g,FROST);self.assertEqual(self.faces(g).count(SNOW),1)

    def test_Chen_waiting_third_cast_restores_original_partial_cycle_and_rng_rollback(self):
        g=self.game((CHEN,FROST,FROST,WAIT_SPELL));self.play(g,CHEN);self.play(g,FROST);self.play(g,FROST);self.play(g,WAIT_SPELL)
        self.assertIsNotNone(g.state.pending_choice);self.assertNotIn(SNOW,self.faces(g));self.fault(g);g=self.portable(g);self.choose(g)
        self.assertEqual(self.faces(g).count(SNOW),1);self.portable(g)

    def test_Akama_banks_an_extra_attack_before_ally_has_attacked(self):
        g=self.game(board=(AKAMA,A));self.attack(g,AKAMA);self.assertEqual(attack_limit(g.state,self.unit(g,A)),2)
        self.attack(g,A);self.attack(g,A)
        with self.assertRaises(IllegalAction):self.attack(g,A)
        self.assertEqual(self.unit(g,A).attacks_this_turn,2);self.portable(g)

    def test_Akama_actual_Windfury_banks_two_independent_extra_attacks(self):
        g=self.game((WF,),board=(AKAMA,A));self.play(g,WF,self.unit(g,AKAMA).id);self.attack(g,AKAMA);self.attack(g,AKAMA)
        self.assertEqual(attack_limit(g.state,self.unit(g,A)),3)
        for _ in range(3):self.attack(g,A)
        with self.assertRaises(IllegalAction):self.attack(g,A)

    def test_Akama_excludes_all_other_Akama_copies_and_preserves_sickness(self):
        g=self.game((D,),board=(AKAMA,AKAMA));self.play(g,D);self.attack(g,AKAMA)
        self.assertEqual([attack_limit(g.state,g.state.entities[i])for i in g.state.players[1].board if g.state.entities[i].card_id==AKAMA],[1,1])
        with self.assertRaises(IllegalAction):self.attack(g,D)

    def test_Akama_allowance_adds_to_later_Windfury_and_expires_without_resetting_attack_history(self):
        g=self.game((WF,),board=(AKAMA,A));self.attack(g,A);self.attack(g,AKAMA);self.play(g,WF,self.unit(g,A).id)
        self.assertEqual(attack_limit(g.state,self.unit(g,A)),3);self.assertEqual(self.unit(g,A).attacks_this_turn,1)
        self.attack(g,A);self.attack(g,A);g.apply(EndTurn(1));self.assertEqual(attack_limit(g.state,self.unit(g,A)),2)

    def test_Akama_preserves_shared_Titan_action_opportunities(self):
        g=self.game((NOOP,),board=(AKAMA,TITAN));t=self.unit(g,TITAN).id
        g.apply(UseMinionAbility(1,t,'0'));self.own_turn(g);g.apply(UseMinionAbility(1,t,'1'));self.own_turn(g)
        g.apply(UseMinionAbility(1,t,'2'));self.attack(g,AKAMA);self.attack(g,TITAN);self.assertEqual(g.state.entities[t].attacks_this_turn,2);self.portable(g)

    def test_Akama_does_not_remove_Frozen_with_extra_allowance(self):
        g=self.game((FREEZE_SPELL,),board=(AKAMA,A));self.play(g,FREEZE_SPELL,self.unit(g,A).id);self.attack(g,AKAMA)
        with self.assertRaises(IllegalAction):self.attack(g,A)

    def test_Akama_attack_health_wait_restores_actual_counters_before_allowance(self):
        g=self.game(board=(AKAMA,A),watch=WAIT_ATTACK);self.attack(g,AKAMA);self.assertIsNotNone(g.state.pending_choice)
        self.fault(g);g=self.portable(g);self.choose(g);self.assertEqual(attack_limit(g.state,self.unit(g,A)),2);self.assertEqual(self.unit(g,AKAMA).attacks_this_turn,1)

    def test_Askara_next_two_actual_Draenei_plays_exclude_other_plays_and_plain_summons(self):
        g=self.game((ASKARA,A,SUMMON_D,D,D));self.play(g,ASKARA);self.play(g,A);self.play(g,SUMMON_D)
        self.assertEqual(self.faces(g).count(D),1);self.play(g,D);self.play(g,D);self.assertEqual(self.faces(g).count(D),5)
        self.assertFalse([m for m in g.state.players[1].cost_modifiers if m.copy_after_play]);self.portable(g)

    def test_Askara_copies_current_post_Battlecry_body_without_repeating_Battlecry(self):
        g=self.game((ASKARA,D_BC));self.play(g,ASKARA);self.play(g,D_BC)
        bodies=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==D_BC]
        self.assertEqual([(e.attack,e.health)for e in bodies],[(5,10),(5,10)]);self.assertEqual(self.hero(g).armor,503)
        self.assertEqual(len([r for r in g.state.play_history if r.card_id==D_BC]),1);self.portable(g)

    def test_Askara_budget_persists_after_source_death_and_full_board_still_consumes_once(self):
        g=self.game((ASKARA,KILL,D));sid=self.play(g,ASKARA);self.play(g,KILL,sid);self.play(g,D)
        self.assertEqual(self.faces(g).count(D),2);self.assertEqual([m.uses_remaining for m in g.state.players[1].cost_modifiers if m.copy_after_play],[1])
        f=self.game((ASKARA,D),board=(A,)*5);self.play(f,ASKARA);self.play(f,D)
        self.assertEqual(self.faces(f).count(D),1);self.assertEqual([m.uses_remaining for m in f.state.players[1].cost_modifiers if m.copy_after_play],[1])

    def test_Askara_real_repeated_source_keeps_old_consumption_separate_from_new_budget(self):
        g=self.game((ASKARA,ASKARA,D));self.play(g,ASKARA);self.play(g,ASKARA)
        self.assertEqual(self.faces(g).count(ASKARA),3);self.assertEqual(sorted(m.uses_remaining for m in g.state.players[1].cost_modifiers if m.copy_after_play),[1,2])
        self.play(g,D);self.assertEqual(self.faces(g).count(D),3);self.assertEqual([m.uses_remaining for m in g.state.players[1].cost_modifiers if m.copy_after_play],[1])

    def test_Askara_Battlecry_returned_original_does_not_copy_new_hand_residence(self):
        g=self.game((ASKARA,D_BOUNCE));self.play(g,ASKARA);self.play(g,D_BOUNCE)
        self.assertNotIn(D_BOUNCE,self.faces(g));self.assertEqual(self.faces(g,zone='hand').count(D_BOUNCE),1)
        self.assertEqual([m.uses_remaining for m in g.state.players[1].cost_modifiers if m.copy_after_play],[1]);self.portable(g)

    def test_Askara_actual_pending_copy_effect_restores_and_source_death_does_not_cancel(self):
        g=self.game((ASKARA,D_BC),watch=WAIT_COPY);self.play(g,ASKARA);self.play(g,D_BC);self.assertIsNotNone(g.state.pending_choice)
        self.assertIn('CopyPaidMinion',str(g.snapshot()));self.fault(g);g=self.portable(g);self.choose(g,'kill_source')
        self.assertEqual(self.faces(g).count(D_BC),2);self.assertNotIn(ASKARA,self.faces(g));self.portable(g)

    def test_Askara_original_entry_bounced_during_pending_copy_is_not_rebound(self):
        g=self.game((ASKARA,D),watch=WAIT_COPY);self.play(g,ASKARA);self.play(g,D);g=self.portable(g);self.choose(g,'bounce')
        self.assertNotIn(D,self.faces(g));self.assertEqual(self.faces(g,zone='hand').count(D),1);self.portable(g)

    def test_Maladaar_next_card_uses_actual_corpses_without_spending_mana_again(self):
        g=self.game((MALADAAR,D,HIGH),corpses=8);self.play(g,MALADAAR);mana=g.state.players[1].mana;self.play(g,D)
        self.assertEqual(g.state.players[1].mana,mana);self.assertEqual(g.state.players[1].resources[Resource.CORPSES],6)
        self.assertEqual(g.state.play_history[-1].payment,PaymentType.CORPSES);self.play(g,HIGH);self.assertEqual(g.state.players[1].mana,mana-7);self.portable(g)

    def test_Maladaar_insufficient_corpses_rejects_atomically_and_keeps_budget(self):
        g=self.game((MALADAAR,HIGH),corpses=1);self.play(g,MALADAAR);old=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,HIGH)
        self.assertEqual(g.snapshot(),old);self.portable(g)

    def test_Maladaar_zero_cost_card_consumes_one_budget_and_does_not_fake_corpse_spend(self):
        g=self.game((MALADAAR,NOOP,D),corpses=5);self.play(g,MALADAAR);self.play(g,NOOP)
        self.assertEqual(g.state.play_history[-1].payment,PaymentType.CORPSES);self.assertEqual(g.state.players[1].resources[Resource.CORPSES],5)
        self.play(g,D);self.assertEqual(g.state.play_history[-1].payment,PaymentType.MANA)

    def test_Maladaar_unused_budget_expires_at_this_real_turn_end(self):
        g=self.game((MALADAAR,D));self.play(g,MALADAAR);self.own_turn(g);self.play(g,D);self.assertEqual(g.state.play_history[-1].payment,PaymentType.MANA)

    def test_Othaar_without_actual_building_ship_does_not_generate_or_consume_rng(self):
        g=self.game((OTHAAR,),host=True);old=g.snapshot()['rng_state'];self.play(g,OTHAAR)
        self.assertEqual(g.snapshot()['rng_state'],old);self.assertEqual(self.faces(g,zone='hand'),[])

    def test_Othaar_actual_piece_death_builds_ship_and_gives_three_distinct_complete_Arcane_candidates(self):
        g=self.game((KILL,OTHAAR),board=('SC_403a',),hero='HERO_06',host=True);self.play(g,KILL,self.unit(g,'SC_403a').id)
        from hs_sim.engine.starships import construction
        self.assertIsNotNone(construction(g.state,1));self.play(g,OTHAAR)
        hand=[g.state.entities[i]for i in g.state.players[1].hand];self.assertEqual(len(hand),3);self.assertEqual(len({x.card_id for x in hand}),3)
        for e in hand:self.assertEqual(g.registry.card(e.card_id).spell_school,SpellSchool.ARCANE);self.assertEqual(local_cost(e)[0],max(0,g.registry.card(e.card_id).cost-2))
        self.portable(g)

    def test_Talgath_doubles_only_current_undamaged_enemy_minion_packets(self):
        g=self.game((HIT,)*4,board=(TALGATH,A),enemy=(A,));target=self.unit(g,A,2).id
        self.play(g,HIT,target);self.assertEqual(g.state.entities[target].health,4);self.play(g,HIT,target);self.assertEqual(g.state.entities[target].health,2)
        self.play(g,HIT,self.unit(g,A).id);self.assertEqual(self.unit(g,A).health,6);self.play(g,HIT,self.hero(g,2).id);self.assertEqual(self.hero(g,2).armor,498);self.portable(g)

    def test_Talgath_multiple_sources_stack_and_Divine_Shield_keeps_original_health(self):
        g=self.game((SHIELD,HIT,HIT),board=(TALGATH,TALGATH),enemy=(A,));target=self.unit(g,A,2).id
        self.play(g,SHIELD,target);self.play(g,HIT,target);self.assertEqual(g.state.entities[target].health,8)
        self.play(g,HIT,target);self.assertNotIn(target,g.state.players[2].board)

    def test_Talgath_silence_removes_live_provider_without_leaving_target_enchantments(self):
        g=self.game((HUSH,HIT),board=(TALGATH,),enemy=(A,));self.play(g,HUSH,self.unit(g,TALGATH).id);self.play(g,HIT,self.unit(g,A,2).id)
        self.assertEqual(self.unit(g,A,2).health,6)

    def test_Talgath_real_Combo_gives_existing_Backstab_and_uses_ordinary_scaled_spell_damage(self):
        g=self.game((NOOP,TALGATH),enemy=(A,));self.play(g,NOOP);self.play(g,TALGATH);self.assertIn('CORE_CS2_072',self.faces(g,zone='hand'))
        self.play(g,'CORE_CS2_072',self.unit(g,A,2).id);self.assertEqual(self.unit(g,A,2).health,4);self.portable(g)

    def test_Talgath_first_play_has_no_unearned_Combo_Backstab(self):
        g=self.game((TALGATH,));self.play(g,TALGATH);self.assertNotIn('CORE_CS2_072',self.faces(g,zone='hand'))

    def test_new_public_policy_and_cycle_shapes_reject_unrelated_silent_extensions(self):
        with self.assertRaises(ValueError):AttackPolicySpec('additional_attacks')
        with self.assertRaises(ValueError):LimitedTriggerSpec('spell_cast_finished',NOOP,uses=1,reset='cycle_turn')
        with self.assertRaises(ValueError):HealthRule(HealthFlow.HEALING,HealthOp.SCALE,2,layer=HealthLayer.TARGET,target_relation='undamaged_enemy_minions',target_kinds=(CardType.MINION,))
        from hs_sim.engine.effects import AddCostModifier
        with self.assertRaises(ValueError):AddCostModifier(1,CostSpec(card_types=(CardType.MINION,)),uses_remaining=2,copy_after_play=True).__post_init__()

