"""Four paid secret entries and their original death/turn/play/copy facts."""
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from tools import card_batch as batch
from hs_sim.cards import past_mage_secret_consumers as native
from hs_sim.engine import Attack,EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import (AddToHand,Buff,ChoiceOption,Damage,Destroy,Draw,GainArmor,GrantKeyword,Heal,
    InvokeBehavior,ModifyCost,RandomDamage,RequestChoice,Summon,Transform)
from hs_sim.engine.health_loss import LoseHealth
from hs_sim.engine.interrupts import CounterMinion
from hs_sim.engine.model import CardClass,CardDefinition,CardType,CostSpec,Keyword,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.secrets import SetSecret
from hs_sim.local_pool_format import build_cn37_local_pool_format

EFFIGY,WARD,FAIRE,CLONE=native.LEAVES
P='k630.'
LOW,HIGH,HIGH2,REWARD1,REWARD2,SLEEP,LOCATION,SELFBUFF,SELFDIE,SELFCHANGE,FILL,UNKNOWN=(P+x for x in
    ('low','high','high2','reward1','reward2','sleep','location','selfbuff','selfdie','selfchange','fill','unknown'))
KILL,WOUND,HURT,HEAL,ARMOR,IMMUNE,LOSS,DISCOUNT,SUMMON,SET_FAIRE,WAIT,FAIL,COUNTER=(P+x for x in
    ('kill','wound','hurt','heal','armor','immune','loss','discount','summon','set_faire','wait','fail','counter'))
CONTEXT=GenerationContext('k630-complete-diagnostic-domain','experimental')


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=opening_registry();native.register_past_mage_secret_consumers(r)
    for cid,cost,hp,extra in ((LOW,3,6,{}),(HIGH,6,12,{}),(HIGH2,6,10,{}),(REWARD1,3,5,{}),
            (REWARD2,3,7,{}),(SLEEP,10,8,{'dormant_turns':5}),(FILL,1,3,{}),
            (SELFBUFF,3,6,{'battlecry':SELFBUFF}),(SELFDIE,3,6,{'battlecry':SELFDIE}),
            (SELFCHANGE,3,6,{'battlecry':SELFCHANGE})):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=2,health=hp,
            metadata=metadata(tribes=()),**extra))
    r.register_behavior(SELFBUFF,lambda c:(Buff(c.source_id,4,5,c.source_id),))
    r.register_behavior(SELFDIE,lambda c:(Destroy(c.source_id),))
    r.register_behavior(SELFCHANGE,lambda c:(Transform(c.source_id,HIGH),))
    r.register_behavior(P+'noop',lambda c:())
    r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,cost=10,durability=2,on_use=P+'noop'))
    members=[REWARD1,REWARD2,HIGH]
    for cid in members:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if mode=='empty':members=[HIGH]
    if mode=='unknown':
        r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,3,metadata(tribes=())));members.append(UNKNOWN)
    r.register_pool(PoolDefinition(native.POOL,'k630-entire-fixture-'+mode,CONTEXT.target_id,CONTEXT.mode,
        tuple(PoolMember(cid) for cid in members),complete=True))
    scripts={KILL:lambda c:(Destroy(c.target_id),),WOUND:lambda c:(Damage(c.target_id,2,c.source_id),),
        HURT:lambda c:(Damage(c.state.players[1].hero_id,2,c.source_id),),
        HEAL:lambda c:(Heal(c.state.players[1].hero_id,2,c.source_id),),
        ARMOR:lambda c:(GainArmor(1,5),),
        IMMUNE:lambda c:(GrantKeyword(c.state.players[1].hero_id,Keyword.IMMUNE,c.source_id),),
        LOSS:lambda c:(LoseHealth(c.state.players[1].hero_id,2,c.source_id),),
        DISCOUNT:lambda c:(ModifyCost(c.target_id,CostSpec(set_to=0),c.source_id),),
        SUMMON:lambda c:(Summon(c.player_id,LOW),),SET_FAIRE:lambda c:(SetSecret(1,FAIRE),)}
    for cid,body in scripts.items():
        extra={'targeting':TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))} if cid in (KILL,WOUND,DISCOUNT) else {}
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            metadata=metadata(CardClass.MAGE,tribes=()),**extra))
    def fail(c):raise ResolutionError('K630 deliberate secret continuation failure')
    r.register_behavior(FAIL,fail)
    def watch(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id not in native.LEAVES:return ()
        choices=[ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(
            RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))]
        high=next((i for i in c.state.players[1].board if c.state.entities[i].card_id==HIGH),None)
        if high is not None:choices.append(ChoiceOption('extra_death','Kill another later minion',(Destroy(high),)))
        return (RequestChoice(1,tuple(choices),c.source_id),)
    r.register_behavior(WAIT,watch)
    r.register_card(CardDefinition(WAIT,WAIT,CardType.MINION,cost=0,health=100,metadata=metadata(tribes=()),
        triggers=(TriggerSpec('secret_revealed',WAIT),) if mode=='reveal' else ()))
    r.register_behavior(COUNTER,lambda c:(CounterMinion(dict(c.event.data)['window_id']),))
    r.register_card(CardDefinition(COUNTER,COUNTER,CardType.SPELL,cost=0,keywords=(Keyword.SECRET,),
        secret=native.SecretSpec(COUNTER,('card_committed',),COUNTER,COUNTER)))
    r.register_secret_condition(COUNTER,lambda c:c.event is not None and c.event.kind=='card_committed' and
        c.event.player_id!=c.player_id and c.state.entities[c.event.source_id].kind==CardType.MINION)
    r.validate();r.freeze();return r


class PastMageSecretConsumerTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'
    def game(self,hand,*,board=(),enemy=(),other_hand=(),mode='normal',deck=None):
        self.mode=mode
        if mode=='reveal':board=(*board,WAIT)
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,board=board,deck=(FILL,)*15 if deck is None else deck,mana=10,max_mana=10),
            PlayerSetup('warrior.hero',hand=other_hand,board=enemy,deck=(FILL,)*15,mana=10,max_mana=10)),
            seed=630,generation_context=CONTEXT),registry(mode))
    def opponent(self,g):g.apply(EndTurn(1))
    def finish_opponent(self,g):g.apply(EndTurn(2))
    def own_board(self,g):return [g.state.entities[i] for i in g.state.players[1].board]
    def revealed(self,g,cid):return [e for e in g.events if e.kind=='secret_revealed' and g.state.entities[e.source_id].card_id==cid]
    def hand_ids(self,g):return [g.state.entities[i].card_id for i in g.state.players[1].hand]
    def resolve_wait(self,g,key='continue'):
        g=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,key);return g

    def test_full_four_rows_eight_primary_faces_and_original_secret_schools(self):
        d=native.load_batch();rows={x['record']['id']:x['record'] for x in d['dependencies']}
        for o in d['official_observations']:batch.check_face(rows[o['card_id']],o['face'],o['locale'])
        self.assertEqual([rows[c]['tags']['SECRET'] for c in native.LEAVES],[1]*4)
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['source_scope_bound'])

    def test_all_four_paid_entries_are_hidden_single_instance_secrets(self):
        for cid in native.LEAVES:
            g=self.game((cid,cid));source=self.play(g,cid);self.assertEqual(g.state.players[1].mana,7)
            self.assertEqual(g.state.players[1].secrets,[source]);saved=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,cid)
            self.assertEqual(g.snapshot(),saved);self.assertNotIn(cid,json.dumps(g.for_player(2).observe()));self.portable(g)

    def test_effigy_uses_original_same_price_full_random_domain(self):
        g=self.game((EFFIGY,),board=(LOW,),other_hand=(KILL,));target=g.state.players[1].board[0]
        self.play(g,EFFIGY);self.opponent(g);self.play(g,KILL,target,player=2)
        self.assertEqual(len(self.revealed(g,EFFIGY)),1);self.assertEqual(len(self.own_board(g)),1)
        self.assertIn(self.own_board(g)[0].card_id,(REWARD1,REWARD2));self.portable(g)

    def test_effigy_cannot_trigger_on_own_turn_or_enemy_death(self):
        g=self.game((EFFIGY,KILL),board=(LOW,),enemy=(LOW,),other_hand=(KILL,));own=g.state.players[1].board[0]
        self.play(g,EFFIGY);self.play(g,KILL,own);self.opponent(g)
        self.play(g,KILL,g.state.players[2].board[0],player=2);self.assertFalse(self.revealed(g,EFFIGY))

    def test_effigy_uses_original_printed_price_despite_local_board_discount(self):
        g=self.game((EFFIGY,DISCOUNT),board=(LOW,),other_hand=(KILL,));target=g.state.players[1].board[0]
        self.play(g,DISCOUNT,target);self.play(g,EFFIGY);self.opponent(g);self.play(g,KILL,target,player=2)
        self.assertEqual(g.state.death_history[0].base_cost,3);self.assertIn(self.own_board(g)[0].card_id,(REWARD1,REWARD2))

    def test_effigy_original_death_survives_later_death_during_reveal_choice(self):
        g=self.game((EFFIGY,),board=(LOW,HIGH),other_hand=(KILL,),mode='reveal');target=g.state.players[1].board[0]
        self.play(g,EFFIGY);self.opponent(g);self.play(g,KILL,target,player=2)
        self.assertIsNotNone(g.state.pending_choice);g=self.resolve_wait(g,'extra_death')
        self.assertEqual(g.state.death_history[-1].base_cost,6)
        self.assertTrue(any(e.card_id in (REWARD1,REWARD2) for e in self.own_board(g)));self.portable(g)

    def test_effigy_empty_same_price_domain_consumes_without_fake_summon(self):
        g=self.game((EFFIGY,),board=(LOW,),other_hand=(KILL,),mode='empty');target=g.state.players[1].board[0]
        self.play(g,EFFIGY);self.opponent(g);self.play(g,KILL,target,player=2)
        self.assertEqual(len(self.revealed(g,EFFIGY)),1);self.assertFalse(self.own_board(g));self.portable(g)

    def test_effigy_unknown_eligible_member_rejects_and_rolls_back_entire_death(self):
        g=self.game((EFFIGY,),board=(LOW,),other_hand=(KILL,),mode='unknown');target=g.state.players[1].board[0]
        self.play(g,EFFIGY);self.opponent(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,KILL,target,player=2)
        self.assertEqual(g.snapshot(),saved)

    def test_ward_owner_start_copies_only_the_single_highest_current_minion(self):
        g=self.game((WARD,),board=(LOW,HIGH));self.play(g,WARD);self.opponent(g)
        self.assertFalse(self.revealed(g,WARD));self.finish_opponent(g)
        self.assertEqual([e.card_id for e in self.own_board(g)],[LOW,HIGH,HIGH]);self.portable(g)

    def test_ward_uses_local_physical_cost_and_not_a_higher_printed_price(self):
        g=self.game((WARD,DISCOUNT),board=(LOW,HIGH));target=g.state.players[1].board[1]
        self.play(g,DISCOUNT,target);self.play(g,WARD);self.opponent(g);self.finish_opponent(g)
        self.assertEqual([e.card_id for e in self.own_board(g)],[LOW,HIGH,LOW])

    def test_ward_ties_use_one_uniform_original_random_branch(self):
        g=self.game((WARD,),board=(LOW,HIGH,HIGH2));ids=tuple(g.state.players[1].board);self.play(g,WARD)
        self.opponent(g);self.finish_opponent(g)
        events=[e for e in g.events if e.kind=='random_choice' and dict(e.data).get('producer')=='effect_branch']
        self.assertEqual(len(events),1);self.assertEqual(tuple(dict(events[0].data)['candidates']),tuple(str(i) for i in ids[1:]))
        self.assertIn(self.own_board(g)[-1].card_id,(HIGH,HIGH2));self.portable(g)

    def test_ward_current_copy_keeps_original_damage_and_stat_enchantments(self):
        g=self.game((WARD,WOUND),board=(HIGH,));target=g.state.players[1].board[0];self.play(g,WOUND,target)
        self.play(g,WARD);self.opponent(g);self.finish_opponent(g)
        self.assertEqual([e.health for e in self.own_board(g)],[10,10]);self.assertNotEqual(self.own_board(g)[0].id,self.own_board(g)[1].id)

    def test_ward_single_current_buffed_copy_never_replays_battlecry_or_samples_rng(self):
        g=self.game((SELFBUFF,WARD));self.play(g,SELFBUFF);self.play(g,WARD);rng=g.snapshot()['rng_state']
        self.opponent(g);self.finish_opponent(g)
        self.assertEqual([(e.attack,e.max_health) for e in self.own_board(g)],[(6,11),(6,11)])
        self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)

    def test_ward_excludes_dormant_and_location_slots(self):
        g=self.game((WARD,),board=(LOW,SLEEP,LOCATION));self.play(g,WARD);self.opponent(g);self.finish_opponent(g)
        self.assertEqual(self.own_board(g)[-1].card_id,LOW)

    def test_ward_empty_or_full_board_stays_hidden(self):
        for board in ((),(SLEEP,LOCATION),(LOW,)*7):
            g=self.game((WARD,),board=board);self.play(g,WARD);self.opponent(g);self.finish_opponent(g)
            self.assertFalse(self.revealed(g,WARD));self.assertEqual(len(g.state.players[1].secrets),1)

    def test_ward_reveal_wait_restores_before_random_tie_and_real_copy(self):
        g=self.game((WARD,),board=(HIGH,HIGH2),mode='reveal');self.play(g,WARD);self.opponent(g);self.finish_opponent(g)
        self.assertIsNotNone(g.state.pending_choice);g=self.resolve_wait(g)
        self.assertEqual(len(self.own_board(g)),4);self.portable(g)

    def test_faire_draws_three_in_opponent_end_phase_then_normal_owner_draw(self):
        g=self.game((FAIRE,));secret=self.play(g,FAIRE);self.opponent(g);self.finish_opponent(g)
        self.assertEqual(self.hand_ids(g),[FILL]*4);self.assertEqual(len(self.revealed(g,FAIRE)),1)
        draws=[e for e in g.events if e.kind=='card_drawn' and e.source_id==secret]
        self.assertEqual(len(draws),3);self.portable(g)

    def test_faire_positive_armor_damage_counts_even_without_health_loss(self):
        g=self.game((FAIRE,ARMOR),other_hand=(HURT,));self.play(g,ARMOR);self.play(g,FAIRE);self.opponent(g);self.play(g,HURT,player=2);self.finish_opponent(g)
        self.assertFalse(self.revealed(g,FAIRE));self.assertEqual(g.state.entities[g.state.players[1].hero_id].damage,0)

    def test_faire_healing_does_not_erase_prior_damage(self):
        g=self.game((FAIRE,),other_hand=(HURT,HEAL));self.play(g,FAIRE);self.opponent(g);self.play(g,HURT,player=2);self.play(g,HEAL,player=2);self.finish_opponent(g)
        self.assertFalse(self.revealed(g,FAIRE))

    def test_faire_damage_to_a_friendly_minion_does_not_count_as_hero_damage(self):
        g=self.game((FAIRE,),board=(LOW,),other_hand=(WOUND,));target=g.state.players[1].board[0]
        self.play(g,FAIRE);self.opponent(g);self.play(g,WOUND,target,player=2);self.finish_opponent(g)
        self.assertEqual(len(self.revealed(g,FAIRE)),1)

    def test_faire_own_turn_damage_does_not_block_next_clean_opponent_turn(self):
        g=self.game((FAIRE,HURT));self.play(g,HURT);self.play(g,FAIRE);self.opponent(g);self.finish_opponent(g)
        self.assertEqual(len(self.revealed(g,FAIRE)),1)

    def test_faire_immune_prevention_and_direct_health_loss_are_not_damage(self):
        for helper in (HURT,LOSS):
            g=self.game((FAIRE,IMMUNE),other_hand=(helper,));self.play(g,IMMUNE);self.play(g,FAIRE);self.opponent(g)
            self.play(g,helper,player=2);self.finish_opponent(g);self.assertEqual(len(self.revealed(g,FAIRE)),1)

    def test_faire_includes_damage_before_secret_is_set_in_the_same_opponent_turn(self):
        g=self.game((),other_hand=(HURT,SET_FAIRE));self.opponent(g);self.play(g,HURT,player=2);self.play(g,SET_FAIRE,player=2);self.finish_opponent(g)
        self.assertFalse(self.revealed(g,FAIRE));self.assertEqual(len(g.state.players[1].secrets),1)

    def test_faire_failed_turn_can_remain_for_a_later_clean_turn(self):
        g=self.game((FAIRE,),other_hand=(HURT,));self.play(g,FAIRE);self.opponent(g);self.play(g,HURT,player=2);self.finish_opponent(g)
        self.assertFalse(self.revealed(g,FAIRE));self.opponent(g);self.finish_opponent(g)
        self.assertEqual(len(self.revealed(g,FAIRE)),1)

    def test_faire_reveal_wait_recovers_draws_before_turn_handoff(self):
        g=self.game((FAIRE,),mode='reveal');self.play(g,FAIRE);self.opponent(g);self.finish_opponent(g)
        self.assertEqual(g.state.active_player,2);g=self.resolve_wait(g)
        self.assertEqual(g.state.active_player,1);self.assertEqual(self.hand_ids(g),[FILL]*4);self.portable(g)

    def test_faire_full_hand_and_empty_deck_use_shared_draw_burn_and_fatigue(self):
        g=self.game((FAIRE,)+(FILL,)*9);self.play(g,FAIRE);self.opponent(g);self.finish_opponent(g)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len(self.revealed(g,FAIRE)),1)
        g=self.game((FAIRE,),deck=());self.play(g,FAIRE);self.opponent(g);self.finish_opponent(g)
        self.assertEqual(g.state.players[1].fatigue,4);self.portable(g)

    def test_clone_copies_two_original_completed_opponent_minion_faces(self):
        g=self.game((CLONE,),other_hand=(LOW,));self.play(g,CLONE);self.opponent(g);self.play(g,LOW,player=2)
        self.assertEqual(self.hand_ids(g),[LOW,LOW]);self.assertEqual(len(self.revealed(g,CLONE)),1);self.portable(g)

    def test_clone_base_recipe_does_not_inherit_post_play_buffs_or_transformations(self):
        for cid in (SELFBUFF,SELFCHANGE):
            g=self.game((CLONE,),other_hand=(cid,));self.play(g,CLONE);self.opponent(g);self.play(g,cid,player=2)
            self.assertEqual(self.hand_ids(g),[cid,cid]);self.assertEqual([g.state.entities[i].max_health for i in g.state.players[1].hand],[6,6]);self.portable(g)

    def test_clone_does_not_require_original_minion_still_alive_after_battlecry(self):
        g=self.game((CLONE,),other_hand=(SELFDIE,));self.play(g,CLONE);self.opponent(g);self.play(g,SELFDIE,player=2)
        self.assertFalse(g.state.players[2].board);self.assertEqual(self.hand_ids(g),[SELFDIE,SELFDIE]);self.portable(g)

    def test_clone_ignores_spells_summons_and_owner_minion_plays(self):
        g=self.game((CLONE,LOW),other_hand=(SUMMON,));self.play(g,CLONE);self.play(g,LOW);self.opponent(g);self.play(g,SUMMON,player=2)
        self.assertFalse(self.revealed(g,CLONE))

    def test_clone_ignores_an_actually_countered_opponent_minion(self):
        g=self.game((COUNTER,CLONE),other_hand=(LOW,));self.play(g,COUNTER);self.play(g,CLONE);self.opponent(g);self.play(g,LOW,player=2)
        self.assertFalse(self.revealed(g,CLONE));self.assertFalse(g.state.players[2].board);self.portable(g)

    def test_clone_full_hand_burns_second_copy_through_ordinary_delivery(self):
        g=self.game((CLONE,)+(FILL,)*9,other_hand=(LOW,));self.play(g,CLONE);self.opponent(g);self.play(g,LOW,player=2)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(self.hand_ids(g).count(LOW),1);self.assertEqual(len(self.revealed(g,CLONE)),1)

    def test_clone_reveal_wait_preserves_original_material_and_rolls_back_failure(self):
        g=self.game((CLONE,),other_hand=(LOW,),mode='reveal');self.play(g,CLONE);self.opponent(g);self.play(g,LOW,player=2)
        self.assertIsNotNone(g.state.pending_choice);g=self.resolve_wait(g);self.assertEqual(self.hand_ids(g),[LOW,LOW]);self.portable(g)

    def test_complete_local_host_executes_all_four_real_secret_triggers(self):
        fmt=build_cn37_local_pool_format();r=fmt.registry
        body=next(cid for cid,c in r.cards.items() if c.kind==CardType.MINION and c.cost==3 and c.health>=3 and
            not c.keywords and not c.battlecry and not c.deathrattle and not c.triggers and not c.interactable and not c.dormant_turns)
        attacker=next(cid for cid,c in r.cards.items() if c.kind==CardType.MINION and c.attack>=r.card(body).health and
            not c.keywords and not c.battlecry and not c.deathrattle and not c.triggers and not c.interactable and not c.dormant_turns)
        for cid in native.LEAVES:
            g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(cid,),board=(body,),deck=(body,)*10,mana=10,max_mana=10),
                PlayerSetup('HERO_08',hand=(body,),board=(attacker,) if cid==EFFIGY else (),deck=(body,)*10,mana=10,max_mana=10)),
                generation_context=fmt.context,seed=630),r)
            self.play(g,cid);self.opponent(g)
            if cid==CLONE:self.play(g,body,player=2)
            elif cid==EFFIGY:g.apply(Attack(2,g.state.players[2].board[0],g.state.players[1].board[0]))
            else:self.finish_opponent(g)
            self.assertEqual(len(self.revealed(g,cid)),1)


if __name__=='__main__':unittest.main()
