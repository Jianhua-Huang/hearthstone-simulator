"""Actual five parents, all seven borrowed Parts and three full generated faces."""
from dataclasses import asdict
from functools import lru_cache
import random
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import past_fixed_parts_mines as native
from hs_sim.cards.simple_followup_p92_cards import register_simple_followup_p92_cards
from hs_sim.cards.simple_followup_p93_cards import (register_simple_followup_p93_cards,
    PLATING,REWINDER,HORN,CLOAK,COOLANT,SWITCH,BLADES)
from hs_sim.engine import EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.deck_shuffles import capture_cost
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,Damage,Destroy,DestroyBatch,Draw,
    InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Silence,Transform,TriggerDeathrattles)
from hs_sim.engine.model import (BattlecryRepeatSpec,CardDefinition,CardType,DamageKind,Keyword,TargetSpec,TriggerSpec,Zone)
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest

TOSH,TINK,JUG,THERMA,WON=native.ROOTS;DINO,SQUIRREL,MINE=native.DEPENDENCIES
SPARES=native.SPARES;LEPER=native.LEPER
P='k689.';A=P+'plain';SMALL=P+'small';POWER=P+'power';IMMUNE=P+'immune';DORMANT=P+'dormant';LOC=P+'location'
KILL=P+'kill';KILL_ALL=P+'kill_all';KILL_ENEMY=P+'kill_enemy';BOOST=P+'boost';HUSH=P+'hush';TAKE=P+'take'
OUT=P+'out';MUTATE=P+'mutate';DRAW=P+'draw';TRIGGER=P+'trigger';DOUBLE=P+'double'
PART_WATCH=P+'part_watch';RANDOM_WATCH=P+'random_watch';DECK_WATCH=P+'deck_watch'
DAMAGE_WATCH=P+'damage_watch';SUMMON_WATCH=P+'summon_watch';WATCH=P+'watch';FAIL=P+'fail'


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer'):
    r=opening_registry();register_simple_followup_p92_cards(r);register_simple_followup_p93_cards(r)
    native.register_past_fixed_parts_mines(r)
    for cid,attack,health,bonus,keywords in((A,1,40,0,()),(SMALL,1,1,0,()),
            (POWER,1,40,2,()),(IMMUNE,1,40,0,(Keyword.IMMUNE,))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=attack,health=health,
            spell_damage=bonus,keywords=keywords,metadata=metadata(collectible=False)))
    r.register_card(CardDefinition(DORMANT,DORMANT,CardType.MINION,health=40,dormant_turns=2,metadata=metadata(collectible=False)))
    r.register_behavior(LOC,lambda c:())
    r.register_card(CardDefinition(LOC,LOC,CardType.LOCATION,durability=3,on_use=LOC,metadata=metadata(collectible=False)))
    r.register_card(CardDefinition(DOUBLE,DOUBLE,CardType.MINION,health=40,
        battlecry_repeats=(BattlecryRepeatSpec(2),),metadata=metadata(collectible=False)))
    board=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
    def destroy_group(c,players):
        ids=tuple(i for p in players for i in c.state.players[p].board if c.state.entities[i].kind==CardType.MINION and c.state.entities[i].active)
        return(DestroyBatch(ids,c.source_id),)
    scripts={KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        KILL_ALL:lambda c:destroy_group(c,(1,2)),KILL_ENEMY:lambda c:destroy_group(c,(3-c.player_id,)),
        BOOST:lambda c:(Buff(c.target_id,3,3,c.source_id),),HUSH:lambda c:(Silence(c.target_id),),
        TAKE:lambda c:(ChangeControl(c.target_id,c.player_id),),OUT:lambda c:(ReturnToHand(c.target_id),),
        MUTATE:lambda c:(Transform(c.target_id,SQUIRREL),),DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),
        TRIGGER:lambda c:(TriggerDeathrattles(c.target_id,c.source_id),)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1,on_play=cid,
            targeting=board if cid in(KILL,BOOST,HUSH,TAKE,OUT,MUTATE,TRIGGER)else None,metadata=metadata(collectible=False)))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K689 deliberate named-delivery rollback')))
    def watch(c):
        e=c.event;source=c.state.entities.get(e.source_id);target=c.state.entities.get(e.target_id);extra=()
        if e.kind=='card_added_to_hand':
            if target is None or target.card_id not in SPARES:return()
        elif e.kind=='random_choice':
            values=dict(e.data)
            if source is None or source.card_id!=TINK or set(values['candidates'])==set(native.FORMS):return()
            original=int(values['selected']);extra=(ReturnToHand(original),)
        elif e.kind=='card_added_to_deck':
            if target is None or target.card_id!=MINE:return()
        elif e.kind=='damage_dealt':
            if source is None or source.card_id!=MINE:return()
        elif target is None or target.card_id!=LEPER:return()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('move','Move original',extra),
            ChoiceOption('fault','Fail after random damage',(
                RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    for cid,event in((PART_WATCH,'card_added_to_hand'),(RANDOM_WATCH,'random_choice'),
            (DECK_WATCH,'card_added_to_deck'),(DAMAGE_WATCH,'damage_dealt'),(SUMMON_WATCH,'minion_summoned')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=40,
            triggers=(TriggerSpec(event,WATCH),),metadata=metadata(collectible=False)))
    r.validate();return r


class PastFixedPartsMinesTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=(A,)*20,enemy_deck=(A,)*20,player=1,seed=689):
        self.mode='small'
        return Game.from_scenario(Scenario(tuple(PlayerSetup('mage.hero'if p==1 else'warrior.hero',
            hand=hand if p==player else enemy_hand,board=board if p==player else enemy,
            deck=deck if p==player else enemy_deck,mana=20,max_mana=20,mana_cap=20)for p in(1,2)),
            active_player=player,seed=seed),fixture('writer'))
    def hand(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].hand]
    def parts(self,g,p=1):return[c for c in self.hand(g,p)if c in SPARES]
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def part_seed(self,cid):return next(s for s in range(2000)if random.Random(s).randrange(7)==SPARES.index(cid))

    def test_complete_raw_roles_children_pins_and_actual_reused_part_body(self):
        d=native.load_batch();self.assertEqual(len(d['original_candidate_ids']),732);self.assertEqual(len(d['official_observations']),24)
        self.assertEqual(d['member_ids'],list(SPARES));self.assertEqual(d['member_weights'],[1]*7)
        for row in d['cards']+d['dependencies']+d['existing_dependencies']:
            cid=row['record']['id']
            if cid=='TIME_013':continue
            self.assertEqual(canonical_digest(asdict(fixture().card(cid))),row['definition_sha256'])
            self.assertEqual(canonical_digest(asdict(fixture().pool_card(cid))),row['pool_card_sha256'])
        self.assertEqual(fixture().card(TOSH).battlecry,fixture().card(native.GNOME).deathrattle)
        self.assertEqual(fixture().card(TOSH).deathrattle,native.PART_BODY)

    def test_all_eight_original_faces_pay_once_and_tokens_are_actual_vanilla_beasts(self):
        for cid in(*native.ROOTS,*native.DEPENDENCIES):
            with self.subTest(cid=cid):
                g=self.game((cid,));source=self.play(g,cid);card=fixture().card(cid)
                self.assertEqual(g.state.players[1].mana,20-card.cost)
                if card.kind==CardType.MINION:
                    self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(card.attack,card.health))
                if cid in native.FORMS:self.assertFalse(card.metadata.collectible);self.assertIsNone(card.battlecry)

    def test_toshley_all_seven_generated_parts_have_real_normal_play_effects(self):
        for cid in SPARES:
            with self.subTest(cid=cid):
                g=self.game((TOSH,),board=(A,),seed=self.part_seed(cid));target=self.unit(g,A).id;self.play(g,TOSH)
                self.assertEqual(self.parts(g),[cid]);self.play(g,cid,target);e=g.state.entities[target]
                if cid==PLATING:self.assertEqual((e.attack,e.health),(1,41))
                elif cid==BLADES:self.assertEqual((e.attack,e.health),(2,40))
                elif cid==SWITCH:self.assertEqual((e.attack,e.health),(40,1))
                elif cid==HORN:self.assertIn(Keyword.TAUNT,e.keywords)
                elif cid==COOLANT:self.assertTrue(e.frozen)
                elif cid==CLOAK:self.assertIn(Keyword.STEALTH,e.keywords)
                else:self.assertEqual(e.zone,Zone.HAND);self.assertIn(target,g.state.players[1].hand)
                self.assertEqual(g.state.players[1].mana,13)

    def test_generated_cloak_expires_at_original_next_owner_turn_start(self):
        g=self.game((TOSH,),board=(A,),seed=self.part_seed(CLOAK));target=self.unit(g,A).id;self.play(g,TOSH);self.play(g,CLOAK,target)
        self.end(g);self.assertIn(Keyword.STEALTH,g.state.entities[target].keywords)
        self.end(g);self.assertNotIn(Keyword.STEALTH,g.state.entities[target].keywords);self.portable(g)

    def test_toshley_battlecry_and_real_deathrattle_each_sample_once(self):
        g=self.game((TOSH,KILL));source=self.play(g,TOSH);self.play(g,KILL,source)
        self.assertEqual(len(self.parts(g)),2);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.players[1].mana,13);self.portable(g)

    def test_toshley_stolen_death_and_full_receiver_hand_keep_actual_burned_part(self):
        g=self.game((KILL,),enemy=(TOSH,),enemy_hand=(A,)*10,player=2)
        source=self.unit(g,TOSH,1).id;self.play(g,KILL,source,player=2)
        burned=[e for e in g.state.entities.values()if e.card_id in SPARES]
        self.assertEqual(len(burned),1);self.assertEqual(burned[0].zone,Zone.GRAVEYARD)
        self.assertEqual(burned[0].controller,1);self.assertEqual(len(g.state.players[1].hand),10);self.portable(g)
        g=self.game((TAKE,KILL),enemy=(TOSH,));source=self.unit(g,TOSH,2).id;self.play(g,TAKE,source);self.play(g,KILL,source)
        self.assertEqual(len(self.parts(g)),1);self.assertEqual(self.parts(g,2),[])

    def test_toshley_silenced_source_has_no_death_reward(self):
        g=self.game((HUSH,KILL),board=(TOSH,));source=self.unit(g,TOSH).id;self.play(g,HUSH,source);rng=g._rng.getstate();self.play(g,KILL,source)
        self.assertEqual(self.parts(g),[]);self.assertEqual(g._rng.getstate(),rng)

    def test_toshley_actual_part_notification_wait_and_failure_keep_original_draw(self):
        g=self.game((TOSH,),board=(PART_WATCH,));self.play(g,TOSH);before=g.snapshot();part=self.parts(g)
        g=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(self.parts(g),part);self.portable(g)

    def test_tinkmaster_empty_other_minion_pool_does_not_consume_rng(self):
        g=self.game((TINK,),board=(DORMANT,LOC));rng=g._rng.getstate();self.play(g,TINK)
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(self.unit(g,TINK).health,3)

    def test_tinkmaster_samples_target_then_form_and_excludes_own_body(self):
        seen=set()
        for seed in range(10):
            g=self.game((TINK,),board=(A,),enemy=(IMMUNE,),seed=seed);ids=(self.unit(g,A).id,self.unit(g,IMMUNE,2).id)
            rng=random.Random();rng.setstate(g._rng.getstate());target=rng.choice(ids);form=rng.choice(native.FORMS)
            source=self.play(g,TINK);seen.add((target==ids[0],form))
            self.assertEqual(g.state.entities[target].card_id,form);self.assertEqual(g._rng.getstate(),rng.getstate())
            self.assertEqual(g.state.entities[source].card_id,TINK)
        self.assertEqual(len(seen),4)

    def test_tinkmaster_transform_uses_original_slot_identity_and_fresh_printed_stats(self):
        g=self.game((BOOST,TINK),enemy=(A,),seed=1);target=self.unit(g,A,2).id;self.play(g,BOOST,target)
        self.play(g,TINK);e=g.state.entities[target];self.assertIn(e.card_id,native.FORMS)
        self.assertEqual(g.state.players[2].board,[target]);card=fixture().card(e.card_id)
        self.assertEqual((e.attack,e.health),(card.attack,card.health));self.assertFalse(g.state.death_history);self.portable(g)

    def test_tinkmaster_wait_keeps_original_target_form_candidates_and_rng(self):
        g=self.game((TINK,),board=(RANDOM_WATCH,),enemy=(A,),seed=0);target=self.unit(g,A,2).id
        self.play(g,TINK);self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.entities[target].card_id,A)
        g=self.portable(g);self.choose(g);self.assertIn(g.state.entities[target].card_id,native.FORMS);self.portable(g)

    def test_tinkmaster_departed_original_is_not_retargeted_after_wait(self):
        g=self.game((TINK,),board=(RANDOM_WATCH,),enemy=(A,),seed=0);target=self.unit(g,A,2).id;self.play(g,TINK)
        g=self.portable(g);self.choose(g,'move');self.assertEqual(g.state.entities[target].zone,Zone.HAND)
        self.assertEqual(g.state.entities[target].card_id,A);self.assertEqual(self.unit(g,TINK).card_id,TINK);self.portable(g)

    def test_tinkmaster_failed_wait_rolls_back_form_rng_and_payment(self):
        g=self.game((TINK,),board=(RANDOM_WATCH,),enemy=(A,),seed=0);self.play(g,TINK);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(g.state.players[1].mana,17);self.portable(g)

    def test_both_juggernauts_share_actual_mine_but_keep_distinct_original_identities(self):
        for cid in(JUG,WON):
            with self.subTest(cid=cid):
                g=self.game((cid,));source=self.play(g,cid);mine=self.entity(g,MINE,2,'deck')
                self.assertEqual((mine.owner,mine.controller,mine.cost),(2,2,6));self.assertEqual(g.state.entities[source].card_id,cid)
                record=g.state.deck_shuffle_history[-1];self.assertEqual((record.actor_id,record.player_id),(1,2))
                self.assertEqual(record.source.card_id,cid);self.assertEqual(record.first_card.card_id,MINE)
                self.assertEqual(capture_cost(g.state,1).quantity,0);self.assertEqual(capture_cost(g.state,2).quantity,0)

    def test_juggernaut_actual_battlecry_and_deathrattle_are_two_semantic_shuffles(self):
        g=self.game((JUG,KILL));source=self.play(g,JUG);self.play(g,KILL,source)
        mines=[g.state.entities[i]for i in g.state.players[2].deck if g.state.entities[i].card_id==MINE]
        self.assertEqual(len(mines),2);self.assertEqual(len(g.state.deck_shuffle_history),2)
        self.assertEqual([r.source.card_id for r in g.state.deck_shuffle_history],[JUG,JUG]);self.portable(g)

    def test_mine_actual_generated_draw_cast_hits_drawer_and_replaces_with_real_card(self):
        g=self.game((JUG,),enemy_deck=(A,),seed=1);self.play(g,JUG)
        self.assertEqual(g.state.entities[g.state.players[2].deck[0]].card_id,MINE);self.end(g)
        self.assertEqual(self.hero(g,2).health,20);self.assertEqual(self.hand(g,2),[A])
        self.assertEqual(len(g.state.draw_history),2);self.assertEqual(len(g.state.cast_history),1)
        self.assertEqual(g.state.cast_history[0].player_id,2);self.assertEqual(g.state.players[2].mana,20);self.portable(g)

    def test_mine_chain_two_real_generated_spells_then_one_replacement_draw(self):
        def order(seed):
            r=random.Random(seed);d=[A]
            for _ in range(2):d.insert(r.randrange(len(d)+1),MINE)
            return d
        seed=next(s for s in range(1000)if order(s)==[MINE,MINE,A])
        g=self.game((JUG,KILL),enemy_deck=(A,),seed=seed);source=self.play(g,JUG);self.play(g,KILL,source);self.end(g)
        self.assertEqual(self.hero(g,2).health,10);self.assertEqual(self.hand(g,2),[A])
        self.assertEqual(len(g.state.draw_history),3)
        self.assertEqual([row.card_id for row in g.state.cast_history],[KILL,MINE,MINE]);self.portable(g)

    def test_mine_normal_hand_play_pays_six_self_damages_without_replacement_draw(self):
        g=self.game((MINE,));self.play(g,MINE);self.assertEqual(self.hero(g).health,20)
        self.assertEqual(g.state.players[1].mana,14);self.assertFalse(g.state.draw_history);self.portable(g)

    def test_mine_uses_drawer_spell_modifier_under_existing_local_spell_policy(self):
        g=self.game((JUG,),enemy=(POWER,),enemy_deck=(A,),seed=1);self.play(g,JUG);self.end(g)
        self.assertEqual(self.hero(g,2).health,18);result=g.state.damage_history[-1].health_result
        self.assertEqual((result.base_amount,result.source_controller,result.damage_kind),(10,2,DamageKind.SPELL.value))

    def test_mine_shuffle_notification_wait_keeps_original_semantic_record(self):
        g=self.game((JUG,),board=(DECK_WATCH,));self.play(g,JUG);self.assertIsNotNone(g.state.pending_choice)
        before=g.snapshot();g=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g)
        self.assertEqual(len(g.state.deck_shuffle_history),1);self.assertEqual(sum(g.state.entities[i].card_id==MINE for i in g.state.players[2].deck),1);self.portable(g)

    def test_actual_mine_damage_wait_restores_original_replacement_tail(self):
        g=self.game((JUG,),enemy=(DAMAGE_WATCH,),enemy_deck=(A,),seed=1);self.play(g,JUG);self.end(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.hero(g,2).health,20);self.assertEqual(self.hand(g,2),[])
        before=g.snapshot();g=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(self.hand(g,2),[A]);self.portable(g)

    def test_thermaplugg_enemy_death_summons_real_leper_with_actual_deathrattle(self):
        g=self.game((KILL,KILL),board=(THERMA,),enemy=(A,));self.play(g,KILL,self.unit(g,A,2).id)
        leper=self.unit(g,LEPER);self.assertEqual((leper.attack,leper.health),(2,1));self.play(g,KILL,leper.id)
        self.assertEqual(self.hero(g,2).health,28);self.assertEqual(len(g.state.players[1].board),1);self.portable(g)

    def test_thermaplugg_friendly_death_and_transform_are_not_enemy_deaths(self):
        g=self.game((KILL,MUTATE),board=(THERMA,A),enemy=(A,));self.play(g,KILL,self.unit(g,A).id)
        self.play(g,MUTATE,self.unit(g,A,2).id);self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[THERMA])

    def test_thermaplugg_two_actual_enemy_deaths_are_two_independent_summons(self):
        g=self.game((KILL_ENEMY,),board=(THERMA,),enemy=(A,A));self.play(g,KILL_ENEMY)
        self.assertEqual(sum(g.state.entities[i].card_id==LEPER for i in g.state.players[1].board),2);self.portable(g)

    def test_thermaplugg_dead_source_and_full_board_do_not_summon(self):
        g=self.game((KILL_ALL,),board=(THERMA,),enemy=(A,));self.play(g,KILL_ALL);self.assertEqual(g.state.players[1].board,[])
        g=self.game((KILL,),board=(THERMA,)+(A,)*6,enemy=(A,));self.play(g,KILL,self.unit(g,A,2).id)
        self.assertEqual(len(g.state.players[1].board),7);self.assertFalse(any(g.state.entities[i].card_id==LEPER for i in g.state.players[1].board))

    def test_thermaplugg_second_player_uses_enemy_current_controller(self):
        g=self.game((KILL,),board=(THERMA,),enemy=(A,),player=2);self.play(g,KILL,self.unit(g,A,1).id,player=2)
        self.assertEqual(self.unit(g,LEPER,2).controller,2);self.portable(g)

    def test_thermaplugg_summon_notification_wait_preserves_named_child_and_rollback(self):
        g=self.game((KILL,),board=(THERMA,SUMMON_WATCH),enemy=(A,));self.play(g,KILL,self.unit(g,A,2).id);before=g.snapshot()
        g=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(self.unit(g,LEPER).health,1);self.portable(g)

    def test_repeated_toshley_and_juggernaut_battlecries_keep_one_physical_payment(self):
        g=self.game((TOSH,),board=(DOUBLE,));self.play(g,TOSH);self.assertEqual(len(self.parts(g)),2);self.assertEqual(g.state.players[1].mana,14)
        g=self.game((JUG,),board=(DOUBLE,));self.play(g,JUG);self.assertEqual(len(g.state.deck_shuffle_history),2)
        self.assertEqual(g.state.players[1].mana,14);self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def test_standard_host_executes_real_enemy_death_reward_and_child_damage(self):
        self.mode='host';h=host('writer');bolt='CORE_EX1_238'
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_02',hand=(THERMA,bolt,bolt),deck=('CORE_CS2_182',)*8,
            mana=20,max_mana=20,mana_cap=20),PlayerSetup('HERO_08',board=(LEPER,),deck=('CORE_CS2_182',)*8)),generation_context=h.context,seed=689),h.registry)
        self.play(g,THERMA);self.play(g,bolt,self.unit(g,LEPER,2).id)
        self.assertEqual(self.hero(g).health,28);self.assertEqual(self.unit(g,LEPER).health,1)
        self.play(g,bolt,self.unit(g,LEPER).id);self.assertEqual(self.hero(g,2).health,28);self.portable(g)
