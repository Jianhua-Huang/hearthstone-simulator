"""Real original entries and concentrated lifecycle/recovery coverage."""
from dataclasses import asdict
from functools import lru_cache
import random
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import classic_legendary_consumers as native
from hs_sim.engine import EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.actions import UseHandAction
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,Damage,Destroy,Draw,EquipWeapon,
    GrantKeyword,InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Silence,TriggerDeathrattles)
from hs_sim.engine.health_loss import ChangeHeroMaxHealth
from hs_sim.engine.model import (BattlecryRepeatSpec,CardDefinition,CardType,Keyword,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.turn_scheduling import QueueTurns,SkipTurns
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest

KNIGHT,NAT,HARRISON,ALEX,BEAST,MILL=native.ROOTS;FINKLE=native.FINKLE
P='k690.';A=P+'plain';TAUNT=P+'taunt';DORMANT=P+'dormant';DOUBLE=P+'double'
KILL=P+'kill';HUSH=P+'hush';OUT=P+'out';TAKE=P+'take';GRANT=P+'grant'
DRAW=P+'draw';MAKE=P+'make';HIT=P+'hit';SHRINK=P+'shrink';SPELL=P+'spell'
WEAPON=P+'weapon';REPLACE=P+'replacement';DR_WEAPON=P+'death_weapon';WEAPON_BODY=P+'weapon_body'
NAT_WATCH=P+'nat_watch';HEALTH_WATCH=P+'health_watch';COST_WATCH=P+'cost_watch';SUMMON_WATCH=P+'summon_watch'
WATCH=P+'watch';FAIL=P+'fail'
EXTRA=P+'extra';SKIP=P+'skip'


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer'):
    r=opening_registry();native.register_classic_legendary_consumers(r)
    for cid,keywords in((A,()),(TAUNT,(Keyword.TAUNT,))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=3,attack=1,health=40,
            keywords=keywords,metadata=metadata(collectible=False)))
    r.register_card(CardDefinition(DORMANT,DORMANT,CardType.MINION,health=40,dormant_turns=2,
        keywords=(Keyword.TAUNT,),metadata=metadata(collectible=False)))
    r.register_card(CardDefinition(DOUBLE,DOUBLE,CardType.MINION,health=40,
        battlecry_repeats=(BattlecryRepeatSpec(2),),metadata=metadata(collectible=False)))
    r.register_behavior(WEAPON_BODY,lambda c:(EquipWeapon(c.player_id,REPLACE),))
    for cid,attack,durability,body in((WEAPON,2,3,None),(REPLACE,1,1,None),(DR_WEAPON,2,3,WEAPON_BODY)):
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,cost=3,attack=attack,durability=durability,
            deathrattle=body,metadata=metadata(collectible=False)))
    scripts={KILL:lambda c:(Destroy(c.target_id,c.source_id),),HUSH:lambda c:(Silence(c.target_id),),
        OUT:lambda c:(ReturnToHand(c.target_id),),TAKE:lambda c:(ChangeControl(c.target_id,c.player_id),),
        GRANT:lambda c:(GrantKeyword(c.target_id,Keyword.TAUNT,c.source_id),),
        DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),MAKE:lambda c:(AddToHand(c.player_id,SPELL,source_id=c.source_id),),
        HIT:lambda c:(Damage(c.target_id,20,c.source_id),),
        SHRINK:lambda c:(ChangeHeroMaxHealth(c.player_id,-20,c.source_id),),SPELL:lambda c:(),
        EXTRA:lambda c:(QueueTurns((c.player_id,),c.source_id),),
        SKIP:lambda c:(SkipTurns(3-c.player_id,source_id=c.source_id),)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=5 if cid==SPELL else 1,
            on_play=cid,targeting=TargetSpec()if cid in(KILL,HUSH,OUT,TAKE,GRANT,HIT)else None,
            metadata=metadata(collectible=False)))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K690 deliberate continuation rollback')))
    def watch(c):
        e=c.event;source=c.state.entities.get(e.source_id);target=c.state.entities.get(e.target_id);extra=()
        if e.kind=='random_choice':
            if source is None or source.card_id!=NAT:return()
            extra=(ReturnToHand(source.id),)
        elif e.kind=='hero_health_set':
            if source is None or source.card_id!=ALEX:return()
        elif e.kind=='cost_modifier_added':
            if source is None or source.card_id!=MILL:return()
        elif target is None or target.card_id!=FINKLE:return()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('move','Move source',extra),
            ChoiceOption('fault','Fail after random work',(
                RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),
                InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    for cid,event in((NAT_WATCH,'random_choice'),(HEALTH_WATCH,'hero_health_set'),
            (COST_WATCH,'cost_modifier_added'),(SUMMON_WATCH,'minion_summoned')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=40,
            triggers=(TriggerSpec(event,WATCH),),metadata=metadata(collectible=False)))
    r.validate();return r


class ClassicLegendaryConsumerTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=(A,)*20,enemy_deck=(A,)*20,
            player=1,seed=690,enemy_weapon=None,armor=0):
        self.mode='small'
        return Game.from_scenario(Scenario(tuple(PlayerSetup('mage.hero'if p==1 else'warrior.hero',
            hand=hand if p==player else enemy_hand,board=board if p==player else enemy,
            deck=deck if p==player else enemy_deck,mana=20,max_mana=20,mana_cap=20,
            armor=armor if p==player else 0,weapon_card_id=enemy_weapon if p!=player else None)for p in(1,2)),
            active_player=player,seed=seed),fixture('writer'))
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def hand(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].hand]
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def price(self,g,cid,p=1):
        e=self.entity(g,cid,p)
        return(g.quote_cost(e.id)if p==g.state.active_player else quote_cost(g.state,g.registry,e)).amount
    def programs(self,g,p=2):return[e for e in g.state.players[p].player_effects if e.spec_id==native.PROGRAM]
    def nat_seed(self,index):return next(s for s in range(100)if random.Random(s).randrange(2)==index)

    def test_complete_primary_faces_full_domain_and_actual_dependency_pins(self):
        d=native.load_batch();self.assertEqual(len(d['official_observations']),20);self.assertEqual(len(d['original_candidate_ids']),732)
        for row in d['cards']+d['dependencies']:
            cid=row['record']['id'];self.assertEqual(canonical_digest(asdict(fixture().card(cid))),row['definition_sha256'])
            self.assertEqual(canonical_digest(asdict(fixture().pool_card(cid))),row['pool_card_sha256'])
        self.assertIsNone(next(x['record']['attack']for x in d['cards']if x['record']['id']==NAT))
        self.assertEqual(fixture().card(NAT).attack,0);self.assertEqual(fixture().card(KNIGHT).hand_actions[0].kind,'trade')
        self.assertNotIn('EX1_560',fixture().cards)

    def test_all_seven_actual_faces_pay_once_and_keep_original_printed_stats(self):
        for cid in(*native.ROOTS,FINKLE):
            with self.subTest(cid=cid):
                g=self.game((cid,));c=fixture().card(cid);source=self.play(g,cid,self.hero(g,2).id if cid==ALEX else None)
                self.assertEqual(g.state.players[1].mana,20-c.cost)
                self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(c.attack,c.health))
        self.assertFalse(fixture().card(FINKLE).metadata.collectible)

    def test_black_knight_destroys_only_current_enemy_taunt(self):
        g=self.game((KNIGHT,),board=(TAUNT,),enemy=(TAUNT,A));target=self.unit(g,TAUNT,2).id;self.play(g,KNIGHT,target)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.players[1].board),2)
        self.assertEqual(len(g.state.players[2].board),1);self.assertEqual(g.state.players[1].mana,16)

    def test_black_knight_rejects_friendly_or_non_taunt_without_paying(self):
        for cid,p in((TAUNT,1),(A,2)):
            g=self.game((KNIGHT,),board=(TAUNT,),enemy=(TAUNT,A));before=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,KNIGHT,self.unit(g,cid,p).id)
            self.assertEqual(g.snapshot(),before)

    def test_black_knight_can_play_without_available_target_and_dormant_does_not_count(self):
        g=self.game((KNIGHT,),enemy=(DORMANT,A));self.play(g,KNIGHT);self.assertEqual(len(g.state.players[2].board),2)
        g=self.game((KNIGHT,),enemy=(TAUNT,));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,KNIGHT)
        self.assertEqual(g.snapshot(),before)

    def test_black_knight_uses_granted_and_silenced_current_taunt(self):
        g=self.game((GRANT,KNIGHT),enemy=(A,));target=self.unit(g,A,2).id;self.play(g,GRANT,target);self.play(g,KNIGHT,target)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        g=self.game((HUSH,KNIGHT),enemy=(TAUNT,));target=self.unit(g,TAUNT,2).id;self.play(g,HUSH,target);self.play(g,KNIGHT)
        self.assertEqual(g.state.entities[target].zone,Zone.BOARD)

    def test_black_knight_trade_pays_one_draws_different_card_without_battlecry(self):
        g=self.game((KNIGHT,),enemy=(TAUNT,),deck=(A,));source=self.entity(g,KNIGHT).id
        g.apply(UseHandAction(1,source,'trade'));self.assertEqual(g.state.players[1].mana,19)
        self.assertEqual(self.hand(g),[A]);self.assertEqual(g.state.entities[source].zone,Zone.DECK)
        self.assertEqual(len(g.state.players[2].board),1);self.assertEqual(len(g.state.play_history),0);self.portable(g)

    def test_nat_has_no_entry_or_opponent_turn_attempt(self):
        g=self.game((NAT,),seed=self.nat_seed(0));rng=g._rng.getstate();self.play(g,NAT)
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(self.hand(g),[]);self.end(g)
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(self.hand(g,2),[A])

    def test_nat_two_equal_branches_extra_or_no_extra_draw_at_own_start(self):
        for branch in(0,1):
            g=self.game(board=(NAT,),seed=self.nat_seed(branch));self.end(g);self.end(g)
            self.assertEqual(self.hand(g),[A]*(2 if branch==0 else 1))
            self.assertEqual(sum(e.kind=='random_choice'for e in g.events),1)

    def test_nat_silence_and_source_retirement_remove_future_attempts(self):
        for cid in(HUSH,KILL,OUT):
            g=self.game((cid,),board=(NAT,),seed=self.nat_seed(0));self.play(g,cid,self.unit(g,NAT).id)
            rng=g._rng.getstate();self.end(g);self.end(g);self.assertEqual(g._rng.getstate(),rng)

    def test_nat_extra_draw_fatigue_and_actual_overdraw_are_ordinary_draws(self):
        g=self.game(board=(NAT,),deck=(),seed=self.nat_seed(0));self.end(g);self.end(g)
        self.assertEqual(self.hero(g).health,27)
        g=self.game((A,)*10,board=(NAT,),seed=self.nat_seed(0));self.end(g);self.end(g)
        self.assertEqual(len(self.hand(g)),10);self.assertEqual(sum(x.outcome=='burned'for x in g.state.draw_history),2)

    def test_nat_sample_wait_restores_rollback_and_accepted_draw_survives_source_return(self):
        g=self.game(board=(NAT,NAT_WATCH),seed=self.nat_seed(0));source=self.unit(g,NAT).id;self.end(g);self.end(g)
        before=g.snapshot();g=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g,'move');self.assertEqual(g.state.entities[source].zone,Zone.HAND)
        self.assertEqual(self.hand(g).count(A),2);self.portable(g)

    def test_harrison_destroys_actual_enemy_weapon_then_draws_original_durability(self):
        g=self.game((HARRISON,),enemy_weapon=WEAPON);weapon=g.state.players[2].weapon_id;self.play(g,HARRISON)
        self.assertEqual(g.state.entities[weapon].zone,Zone.GRAVEYARD);self.assertIsNone(g.state.players[2].weapon_id)
        self.assertEqual(self.hand(g),[A]*3);self.assertEqual(g.state.players[1].mana,15)

    def test_harrison_no_weapon_does_not_draw_or_fatigue(self):
        g=self.game((HARRISON,),deck=());self.play(g,HARRISON);self.assertEqual(self.hero(g).health,30)
        self.assertEqual(g.state.draw_history,[])

    def test_harrison_weapon_deathrattle_replacement_does_not_reprice_or_destroy_new_weapon(self):
        g=self.game((HARRISON,),enemy_weapon=DR_WEAPON);self.play(g,HARRISON)
        weapon=g.state.entities[g.state.players[2].weapon_id];self.assertEqual((weapon.card_id,weapon.durability),(REPLACE,1))
        self.assertEqual(self.hand(g),[A]*3);self.portable(g)

    def test_harrison_draws_burn_normally_after_hand_capacity(self):
        g=self.game((HARRISON,)+(A,)*9,enemy_weapon=WEAPON);self.play(g,HARRISON)
        self.assertEqual(len(self.hand(g)),10);self.assertEqual(sum(x.outcome=='burned'for x in g.state.draw_history),2)

    def test_alexstrasza_both_heroes_keep_maximum_and_armor_without_heal_or_damage(self):
        for p in(1,2):
            g=self.game((ALEX,),armor=8);before=len(g.events);self.play(g,ALEX,self.hero(g,p).id)
            self.assertEqual((self.hero(g,p).health,self.hero(g,p).max_health),(15,30));self.assertEqual(self.hero(g).armor,8)
            self.assertFalse(any(e.kind in('damage_dealt','healed')for e in g.events[before:]))

    def test_alexstrasza_raises_low_health_and_respects_existing_reduced_maximum_policy(self):
        g=self.game((HIT,ALEX),armor=0);self.play(g,HIT,self.hero(g).id);self.play(g,ALEX,self.hero(g).id)
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(15,30))
        g=self.game((SHRINK,ALEX));self.play(g,SHRINK);self.play(g,ALEX,self.hero(g).id)
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(10,10))

    def test_alexstrasza_rejects_minion_and_missing_target_atomically(self):
        for target in('minion','none'):
            g=self.game((ALEX,),enemy=(A,));before=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,ALEX,self.unit(g,A,2).id if target=='minion'else None)
            self.assertEqual(g.snapshot(),before)

    def test_alexstrasza_health_assignment_wait_preserves_value_and_failure(self):
        g=self.game((ALEX,),board=(HEALTH_WATCH,));self.play(g,ALEX,self.hero(g,2).id);before=g.snapshot();g=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(self.hero(g,2).health,15);self.portable(g)

    def test_beast_actual_death_summons_full_named_three_three_for_opponent(self):
        g=self.game((KILL,),board=(BEAST,));self.play(g,KILL,self.unit(g,BEAST).id);child=self.unit(g,FINKLE,2)
        self.assertEqual((child.attack,child.health,child.controller),(3,3,2));self.assertFalse(child.keywords)
        self.assertEqual(g.state.players[1].board,[])

    def test_beast_stolen_death_uses_current_controller_enemy_and_independent_board_slot(self):
        g=self.game((TAKE,KILL),board=(A,A),enemy=(A,BEAST));source=self.unit(g,BEAST,2).id
        self.play(g,TAKE,source);self.play(g,KILL,source)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[2].board],[A,FINKLE]);self.portable(g)

    def test_beast_silenced_death_and_full_enemy_board_have_no_child(self):
        g=self.game((HUSH,KILL),board=(BEAST,));source=self.unit(g,BEAST).id;self.play(g,HUSH,source);self.play(g,KILL,source)
        self.assertEqual(g.state.players[2].board,[])
        g=self.game((KILL,),board=(BEAST,),enemy=(A,)*7);self.play(g,KILL,self.unit(g,BEAST).id)
        self.assertEqual(len(g.state.players[2].board),7);self.assertFalse(any(e.card_id==FINKLE for e in g.state.entities.values()))

    def test_beast_child_summon_wait_has_independent_restore_and_rollback(self):
        g=self.game((KILL,),board=(BEAST,SUMMON_WATCH));self.play(g,KILL,self.unit(g,BEAST).id)
        before=g.snapshot();g=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(self.unit(g,FINKLE,2).health,3)

    def test_millhouse_installs_one_opponent_program_without_changing_current_prices(self):
        g=self.game((MILL,SPELL),enemy_hand=(SPELL,));source=self.play(g,MILL)
        self.assertEqual(len(self.programs(g)),1);self.assertEqual(self.programs(g)[0].source_id,source)
        self.assertEqual(self.price(g,SPELL),5);self.assertEqual(self.price(g,SPELL,2),5)
        self.assertEqual(self.programs(g,1),[])

    def test_millhouse_next_opponent_turn_all_existing_drawn_and_generated_spells_pay_zero(self):
        g=self.game((MILL,),enemy_hand=(SPELL,DRAW,MAKE),enemy_deck=(SPELL,)*10);self.play(g,MILL);self.end(g)
        self.assertEqual(self.programs(g),[]);mana=g.state.players[2].mana
        self.play(g,SPELL,player=2);self.play(g,DRAW,player=2);self.play(g,MAKE,player=2)
        self.assertEqual(self.price(g,SPELL,2),0);self.play(g,SPELL,player=2)
        self.assertEqual(g.state.players[2].mana,mana);self.assertEqual(len(g.state.players[2].cost_modifiers),1)
        self.portable(g)

    def test_millhouse_does_not_discount_minions_and_expires_after_beneficiary_turn(self):
        g=self.game((MILL,SPELL),enemy_hand=(SPELL,A));self.play(g,MILL);self.end(g)
        self.assertEqual(self.price(g,A,2),3);self.assertEqual(self.price(g,SPELL,2),0);self.end(g)
        self.assertEqual(self.price(g,SPELL),5);self.assertEqual(self.price(g,SPELL,2),5)
        self.assertEqual(g.state.players[2].cost_modifiers,[]);self.end(g);self.assertEqual(self.price(g,SPELL,2),5)

    def test_millhouse_program_survives_silence_death_and_return_of_source(self):
        for action in(HUSH,KILL,OUT):
            g=self.game((MILL,action),enemy_hand=(SPELL,));source=self.play(g,MILL);self.play(g,action,source)
            self.end(g);self.assertEqual(self.price(g,SPELL,2),0);self.assertEqual(self.programs(g),[])

    def test_millhouse_repeated_battlecry_has_distinct_once_consumed_instances_and_one_payment(self):
        g=self.game((MILL,),board=(DOUBLE,),enemy_hand=(SPELL,));self.play(g,MILL)
        ids=[e.id for e in self.programs(g)];self.assertEqual(len(set(ids)),2);self.assertEqual(g.state.players[1].mana,18)
        self.end(g);self.assertEqual(self.programs(g),[]);self.assertEqual(len(g.state.players[2].cost_modifiers),2)
        self.assertEqual(self.price(g,SPELL,2),0);self.assertEqual(len(g.state.play_history),1)

    def test_millhouse_second_player_benefits_actual_opponent(self):
        g=self.game((MILL,),enemy_hand=(SPELL,),player=2);self.play(g,MILL,player=2);self.end(g)
        self.assertEqual(g.state.active_player,1);self.assertEqual(self.price(g,SPELL),0);self.portable(g)

    def test_millhouse_pending_waits_through_caster_extra_turn_until_actual_enemy_start(self):
        g=self.game((MILL,EXTRA),enemy_hand=(SPELL,));self.play(g,MILL);self.play(g,EXTRA);self.end(g)
        self.assertEqual(g.state.active_player,1);self.assertEqual(len(self.programs(g)),1);self.assertEqual(self.price(g,SPELL,2),5)
        self.end(g);self.assertEqual(g.state.active_player,2);self.assertEqual(self.price(g,SPELL,2),0)

    def test_millhouse_pending_is_not_consumed_by_skipped_enemy_slot(self):
        g=self.game((MILL,SKIP),enemy_hand=(SPELL,));self.play(g,MILL);self.play(g,SKIP);self.end(g)
        self.assertEqual(g.state.active_player,1);self.assertEqual(len(self.programs(g)),1);self.assertEqual(self.price(g,SPELL,2),5)
        self.end(g);self.assertEqual(g.state.active_player,2);self.assertEqual(self.price(g,SPELL,2),0)

    def test_millhouse_pending_and_cost_install_wait_restore_exact_consumption_deadline_and_rollback(self):
        g=self.game((MILL,),enemy=(COST_WATCH,),enemy_hand=(SPELL,));self.play(g,MILL);g=self.portable(g);self.end(g)
        self.assertEqual(self.programs(g),[]);before=g.snapshot();g=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g)
        self.assertEqual(self.price(g,SPELL,2),0);self.assertEqual(g.state.players[2].cost_modifiers[0].expires_turn,g.state.turn)
        self.end(g);self.assertEqual(self.price(g,SPELL,2),5);self.portable(g)

    def test_standard_host_real_millhouse_discount_and_black_knight_taunt_destroy_restore(self):
        self.mode='host';h=host('writer');taunt='CORE_CS2_179';bolt='CORE_EX1_238'
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_02',hand=(MILL,KNIGHT),board=(taunt,),
            deck=('CORE_CS2_182',)*8,mana=20,max_mana=20,mana_cap=20),PlayerSetup('HERO_02',hand=(bolt,),
            board=(taunt,),deck=('CORE_CS2_182',)*8,mana=20,max_mana=20,mana_cap=20)),
            generation_context=h.context,seed=690),h.registry)
        target=self.unit(g,taunt,2).id;self.play(g,KNIGHT,target);self.play(g,MILL);self.end(g)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);mana=g.state.players[2].mana
        self.play(g,bolt,self.unit(g,taunt).id,player=2);self.assertEqual(g.state.players[2].mana,mana);self.portable(g)
