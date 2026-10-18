"""Real Talya through all existing companion bodies and ordinary summon entry."""
from functools import lru_cache
import json
from random import Random
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.fixed_companion_cards import (COMPANIONS,COMPANION_UNIT,PREFIX,
    register_fixed_companion_cards)
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_companion_quantity_cards import (TALYA,PROGRAM,load_batch,
    register_native_companion_quantity_cards)
from hs_sim.cards.simple_followup_p13_cards import SPEAKER,register_simple_followup_p13_cards
from hs_sim.cards.simple_followup_p14_cards import BROLL,register_simple_followup_p14_cards
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,
    Registry,Scenario,SelectChoice,TargetSpec,Zone)
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,Destroy,
    InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import canonical_digest

ANIMAL='CORE_NEW1_031';CALL='CORE_OG_211';KHADGAR='CORE_DAL_575'
P='k191.';HERO=P+'hero';FILL=P+'filler';WATCH=P+'watch'


@lru_cache(maxsize=1)
def original_multiplier():return build_registry().card(KHADGAR)


@lru_cache(maxsize=None)
def registry(mode=None):
    r=Registry('k191-companion-quantity-'+str(mode))
    register_fixed_companion_cards(r)
    register_simple_followup_p13_cards(r)
    register_simple_followup_p14_cards(r)
    register_native_companion_quantity_cards(r)
    r.register_card(original_multiplier())
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=80))
    r.register_card(CardDefinition(FILL,FILL,CardType.MINION,attack=1,health=20))
    bodies={
        'noop':lambda c:(),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'take':lambda c:(ChangeControl(c.target_id,c.player_id),),
        'create':lambda c:(AddToHand(c.player_id,TALYA,c.source_id),),
        'summon':lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(TALYA),),SummonCause.capture(c)),),
        'other':lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(FILL),),SummonCause.capture(c)),),
        'fail':lambda c:(_ for _ in()).throw(ResolutionError('K191 deliberate reaction failure')),
    }
    for key,body in bodies.items():
        r.register_behavior(P+key,body)
        kwargs={'targeting':TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))}if key in ('kill','silence','bounce','take')else{}
        if key!='fail':r.register_card(CardDefinition(P+key,P+key,CardType.SPELL,on_play=P+key,**kwargs))
    if mode:
        def eligible(c):
            return(c.event.player_id==c.player_id and c.state.entities[c.event.target_id].card_id in COMPANIONS and
                sum(c.state.entities[i].card_id in COMPANIONS for i in c.state.players[c.player_id].board)==1)
        def watch(c):
            before=()
            if mode=='increase':before=(AddPlayerEffect(c.player_id,PROGRAM,c.source_id),)
            if mode in('random','immediate_failure'):
                before=(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),)
            if mode=='immediate_failure':before=(*before,InvokeBehavior(P+'fail',c.source_id,c.player_id))
            original=next(root for root in reversed(c.state.card_summon_history)if root.status=='active')
            options=(ChoiceOption('ok','Continue'),ChoiceOption('kill','Remove summoning source',
                (Destroy(original.request.cause.source.entity_id,c.source_id),)),ChoiceOption('fail','Rollback reaction',
                (RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(P+'fail',c.source_id,c.player_id))))
            return(*before,RequestChoice(c.player_id,options,c.source_id))
        r.register_trigger_condition(P+'eligible',eligible);r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,
            limited_triggers=(LimitedTriggerSpec('minion_summoned',P+'watch',condition_id=P+'eligible'),)))
    r.validate();return r


class NativeCompanionQuantityTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),other_hand=(),mode=None):
        self.mode=mode
        if mode:board=(*board,WATCH)
        return Game.from_scenario(Scenario((
            PlayerSetup(HERO,hand=hand,board=board,deck=(FILL,)*10,mana=80,max_mana=80,mana_cap=80),
            PlayerSetup(HERO,hand=other_hand,board=enemy,deck=(FILL,)*10,mana=80,max_mana=80,mana_cap=80)),seed=191),registry(mode))

    def play(self,g,cid,target=None,p=None):
        p=g.state.active_player if p is None else p
        eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,eid,target));return eid

    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def companions(self,g,p=1):
        return[g.state.entities[i].card_id for i in g.state.players[p].board if g.state.entities[i].card_id in COMPANIONS]

    def expected(self,g,n):
        s=g.snapshot()['rng_state'];r=Random();r.setstate((s[0],tuple(s[1]),s[2]))
        return[COMPANIONS[r.randrange(3)]for _ in range(n)]

    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));reader=registry.__wrapped__(self.mode)
        self.assertIsNot(reader,g.registry)
        self.assertEqual(Game.from_snapshot(s,reader).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for key in('resolution_frame','card_summon_history','source_allocation','rng_state','SummonEntryMaterial'):
                self.assertNotIn('"'+key+'"',public)

    def test_complete_real_root_source_stats_metadata_and_two_primary_faces(self):
        d=load_batch();raw=d['cards'][0]['record'];card=registry().card(TALYA)
        self.assertEqual(canonical_digest(raw),d['cards'][0]['record_sha256'])
        self.assertEqual(card.metadata,metadata_from_record(raw))
        self.assertEqual((card.cost,card.attack,card.health),(5,4,6))
        self.assertEqual(len(d['official_observations']),2)
        self.assertEqual(len(d['existing_dependencies']),7)
        self.assertFalse(d['formal_pool_complete']or d['cn_calibrated'])
        self.assertEqual(registry().player_effect(PROGRAM).producer_quantities[0].unit_id,COMPANION_UNIT)
        for mode in('random','all','choice'):
            self.assertNotIn('hero_power',registry().summon_producer_profile(PREFIX+mode).source_origins)

    def test_real_animal_two_independent_choices_one_cast_one_payment(self):
        g=self.game((TALYA,ANIMAL));source=self.play(g,TALYA)
        expected=self.expected(g,2);cast_count=len(g.state.cast_history);self.play(g,ANIMAL)
        self.assertEqual(self.companions(g),expected)
        self.assertEqual(g.state.players[1].mana,72)
        self.assertEqual(len(g.state.cast_history),cast_count+1)
        self.assertEqual(g.state.players[1].player_effects[0].source_id,source)
        roots=g.state.card_summon_history[-2:]
        self.assertEqual([x.request.selection for x in roots],['random']*2)
        self.assertEqual(roots[0].request.cause,roots[1].request.cause)
        self.portable(g)

    def test_repeated_battlecries_stack_as_two_persistent_instances(self):
        g=self.game((TALYA,TALYA,ANIMAL));self.play(g,TALYA);self.play(g,TALYA)
        expected=self.expected(g,3);self.play(g,ANIMAL)
        self.assertEqual(self.companions(g),expected)
        self.assertEqual(len(g.state.players[1].player_effects),2);self.portable(g)

    def test_source_silence_and_death_do_not_remove_permanent_program(self):
        g=self.game((TALYA,P+'silence',P+'kill',ANIMAL));source=self.play(g,TALYA)
        self.play(g,P+'silence',source);self.play(g,P+'kill',source);self.play(g,ANIMAL)
        self.assertEqual(len(self.companions(g)),2)
        self.assertEqual(len(g.state.players[1].player_effects),1);self.portable(g)

    def test_bounce_and_play_again_stacks_programs(self):
        g=self.game((TALYA,P+'bounce',ANIMAL));source=self.play(g,TALYA)
        self.play(g,P+'bounce',source);self.play(g,TALYA);self.play(g,ANIMAL)
        self.assertEqual(len(self.companions(g)),3)
        self.assertEqual(len(g.state.players[1].player_effects),2);self.portable(g)

    def test_creating_and_plain_summoning_talya_does_not_execute_battlecry(self):
        g=self.game((P+'create',P+'summon',ANIMAL));self.play(g,P+'create');self.play(g,P+'summon')
        self.assertFalse(g.state.players[1].player_effects);self.play(g,ANIMAL)
        self.assertEqual(len(self.companions(g)),1);self.portable(g)

    def test_unrelated_summon_is_not_a_companion_logical_unit(self):
        g=self.game((TALYA,P+'other'));self.play(g,TALYA);self.play(g,P+'other')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[TALYA,FILL])
        self.assertEqual(len(g.state.card_summon_history),1)

    def test_call_keeps_original_three_order_then_one_random_companion(self):
        g=self.game((TALYA,CALL));self.play(g,TALYA);expected=self.expected(g,1)
        self.play(g,CALL);self.assertEqual(self.companions(g),[*COMPANIONS,*expected])
        roots=g.state.card_summon_history[-4:]
        self.assertEqual([x.request.selection for x in roots],['first']*3+['random'])
        self.assertEqual(len({x.request.cause.cast_id for x in roots}),1);self.portable(g)

    def test_speaker_retains_one_original_menu_then_independent_random_tail(self):
        g=self.game((TALYA,SPEAKER));self.play(g,TALYA);expected=self.expected(g,1);rng=g.snapshot()['rng_state']
        self.play(g,SPEAKER);self.assertEqual([x.id for x in g.state.pending_choice.options],list(COMPANIONS))
        self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)
        self.choose(g,COMPANIONS[1]);self.assertEqual(self.companions(g),[COMPANIONS[1],*expected]);self.portable(g)

    def test_broll_successful_cast_uses_companion_quantity(self):
        g=self.game((TALYA,P+'noop'),board=(BROLL,));self.play(g,TALYA);expected=self.expected(g,2)
        self.play(g,P+'noop');self.assertEqual(self.companions(g),expected)
        self.assertEqual(len(g.state.cast_history),1)
        roots=g.state.card_summon_history[-2:]
        self.assertTrue(all(x.request.cause.source.card_id==BROLL for x in roots));self.portable(g)

    def test_animal_and_after_cast_broll_each_quote_one_own_body(self):
        g=self.game((TALYA,ANIMAL),board=(BROLL,));self.play(g,TALYA);expected=self.expected(g,4)
        self.play(g,ANIMAL);self.assertEqual(self.companions(g),expected)
        roots=g.state.card_summon_history[-4:]
        self.assertEqual([x.request.cause.source.card_id for x in roots],[ANIMAL,ANIMAL,BROLL,BROLL])
        self.assertEqual(len(g.state.cast_history),1);self.portable(g)

    def test_no_program_preserves_single_random_without_extra_requests(self):
        g=self.game((ANIMAL,));expected=self.expected(g,1);self.play(g,ANIMAL)
        self.assertEqual(self.companions(g),expected);self.assertEqual(len(g.state.card_summon_history),1)

    def test_existing_board_multiplier_duplicates_each_selected_unit(self):
        g=self.game((TALYA,ANIMAL),board=(KHADGAR,));self.play(g,TALYA);expected=self.expected(g,2)
        self.play(g,ANIMAL);self.assertEqual(self.companions(g),[c for c in expected for _ in range(2)])
        self.assertEqual(len(g.state.card_summon_history),2);self.portable(g)

    def test_full_board_retains_original_no_selection_no_rng_policy(self):
        g=self.game((TALYA,ANIMAL),board=(FILL,)*6);self.play(g,TALYA);rng=g.snapshot()['rng_state']
        self.play(g,ANIMAL);self.assertFalse(self.companions(g));self.assertEqual(g.snapshot()['rng_state'],rng)
        self.assertEqual(len(g.state.players[1].player_effects),1);self.portable(g)

    def test_last_space_only_consumes_one_actual_random_choice(self):
        g=self.game((TALYA,ANIMAL),board=(FILL,)*5);self.play(g,TALYA);expected=self.expected(g,1)
        self.play(g,ANIMAL);self.assertEqual(self.companions(g),expected)
        roots=g.state.card_summon_history[-2:]
        self.assertEqual(sum(len(x.deliveries)for x in roots),1)
        self.assertEqual(len(g.state.players[1].board),7);self.portable(g)

    def test_companion_reaction_wait_restores_entire_original_tail(self):
        g=self.game((TALYA,ANIMAL),mode='wait');self.play(g,TALYA);expected=self.expected(g,2)
        self.play(g,ANIMAL);self.assertEqual(self.companions(g),expected[:1]);self.portable(g)
        self.choose(g);self.assertEqual(self.companions(g),expected);self.portable(g)

    def test_later_program_change_does_not_rewrite_already_quoted_body(self):
        g=self.game((TALYA,ANIMAL),mode='increase');self.play(g,TALYA)
        self.play(g,ANIMAL);self.assertEqual(len(g.state.players[1].player_effects),2);self.portable(g)
        self.choose(g);self.assertEqual(len(self.companions(g)),2);self.portable(g)

    def test_extra_random_unit_samples_after_original_entry_reactions(self):
        g=self.game((TALYA,ANIMAL),mode='random');self.play(g,TALYA)
        self.play(g,ANIMAL);first=self.companions(g);next_expected=self.expected(g,1)
        original_rng=g.snapshot()['rng_state'];self.portable(g);self.choose(g)
        self.assertEqual(self.companions(g),[*first,*next_expected])
        root=g.state.card_summon_history[-1]
        self.assertEqual(json.loads(json.dumps(root.rng_before)),original_rng);self.portable(g)

    def test_original_play_failure_rolls_back_payment_selection_and_extra_work(self):
        g=self.game((TALYA,ANIMAL),mode='immediate_failure');self.play(g,TALYA);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K191 deliberate'):self.play(g,ANIMAL)
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_broll_source_death_during_first_entry_keeps_owed_extra(self):
        g=self.game((TALYA,P+'noop'),board=(BROLL,),mode='wait');self.play(g,TALYA)
        self.play(g,P+'noop');self.portable(g);self.choose(g,'kill')
        self.assertEqual(len(self.companions(g)),2)
        self.assertFalse(any(g.state.entities[i].card_id==BROLL for i in g.state.players[1].board));self.portable(g)

    def test_choice_reaction_failure_rolls_back_rng_and_owed_tail(self):
        g=self.game((TALYA,ANIMAL),mode='wait');self.play(g,TALYA);self.play(g,ANIMAL)
        before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K191 deliberate'):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.portable(g);self.choose(g)
        self.assertEqual(len(self.companions(g)),2);self.portable(g)

    def test_opponent_cards_do_not_borrow_permanent_program(self):
        g=self.game((TALYA,),other_hand=(ANIMAL,));self.play(g,TALYA);g.apply(EndTurn(1))
        self.play(g,ANIMAL);self.assertEqual(len(self.companions(g,2)),1)
        self.assertFalse(g.state.players[2].player_effects);self.portable(g)

    def test_control_change_does_not_transfer_original_player_program(self):
        g=self.game((TALYA,),other_hand=(P+'take',ANIMAL));source=self.play(g,TALYA);g.apply(EndTurn(1))
        self.play(g,P+'take',source);self.play(g,ANIMAL)
        self.assertEqual(len(self.companions(g,2)),1)
        self.assertEqual(len(g.state.players[1].player_effects),1)
        self.assertFalse(g.state.players[2].player_effects);self.portable(g)

    def test_default_representative_registry_has_no_new_companion_program(self):
        from hs_sim.engine.representative import build_registry as representative
        r=representative();self.assertNotIn(PROGRAM,r.player_effects)
        self.assertNotIn(PREFIX+'random',r.summon_producer_profiles)


if __name__=='__main__':unittest.main()
