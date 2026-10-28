"""Direct selected Secret CASTs retain ordinary discovery and physical receipts."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json,unittest
from unittest.mock import patch
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from tools import card_batch as batch
from hs_sim.cards import ring_toss_secret_casts as native
from hs_sim.engine import EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.discovery_delivery import validate_completion
from hs_sim.engine.effects import AddToHand,ChoiceOption,Damage,InvokeBehavior,RequestChoice
from hs_sim.engine.model import (CardClass,CardDefinition,CardType,CostSpec,Keyword,LimitedTriggerSpec,SecretSpec,Zone)
from hs_sim.engine.pools import (DiscoverFromPool,GenerateFromPool,GenerationContext,PoolCard,PoolDefinition,
    PoolMember,PoolQuery,resolve_candidates)
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.local_pool_format import build_cn37_local_pool_format

P='k623.'
A,B,C,D,E,F=SECRETS=tuple(P+'secret'+str(i) for i in range(6))
FILL,HIGH,LOW,PREP_ONE,PREP_FIVE,WAIT,AFTER_WAIT,FAIL_NOW,FILL_HAND,FAIL=(P+s for s in
    ('fill','higher','equal','prepare_one','prepare_five','cast_wait','after_wait','fail_now','fill_hand','fail'))

def context(mode):return GenerationContext('k623-diagnostic-'+mode,'experimental')


@lru_cache(None)
def registry(mode='normal',role='writer'):
    if mode not in ('normal','full','empty'):raise ValueError('Unknown direct Secret fixture')
    r=opening_registry();native.register_ring_toss_secret_casts(r)
    r.register_behavior(FILL,lambda c:())
    for cid,cost in ((FILL,0),(HIGH,5),(LOW,4)):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=FILL,metadata=metadata(tribes=())))
    for cid in SECRETS:
        r.register_behavior(cid,lambda c:(Damage(c.state.players[3-c.player_id].hero_id,1,c.source_id),))
        r.register_secret_condition(cid,lambda c:c.event.player_id==3-c.player_id)
        card=CardDefinition(cid,cid,CardType.SPELL,cost=3,keywords=(Keyword.SECRET,),
            secret=SecretSpec(cid,('card_committed',),cid,cid),metadata=metadata(CardClass.MAGE,tribes=()))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    members=() if mode=='empty' else (F,) if mode=='full' else (A,B,C)
    r.register_pool(PoolDefinition(native.POOL,'k623-explicit-complete-diagnostic-'+mode,
        context(mode).target_id,context(mode).mode,tuple(PoolMember(cid)for cid in members),complete=True))
    for cid,faces in ((PREP_ONE,(A,)),(PREP_FIVE,SECRETS[:5])):
        r.register_behavior(cid,lambda c,faces=faces:tuple(CastSpell(c.player_id,face,c.source_id)for face in faces))
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata(tribes=())))
    def fail(c):raise ResolutionError('K623 deliberate selected CAST reaction failure')
    r.register_behavior(FAIL,fail)
    for cid,event in ((WAIT,'spell_cast_accepted'),(AFTER_WAIT,'card_discovered'),
            (FAIL_NOW,'spell_cast_accepted'),(FILL_HAND,'spell_cast_accepted')):
        def eligible(c,cid=cid):
            source=c.state.entities.get(c.event.source_id)
            return (source is not None and source.card_id in native.DEPENDENCIES if cid==FILL_HAND else
                c.event.player_id==c.player_id if cid==AFTER_WAIT else source is not None and source.card_id in SECRETS)
        def watch(c,cid=cid):
            if cid==FILL_HAND:return(AddToHand(c.player_id,FILL,c.source_id),)
            failure=InvokeBehavior(FAIL,c.source_id,c.player_id)
            if cid==FAIL_NOW:return(failure,)
            return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(failure,))),c.source_id),)
        r.register_behavior(cid,watch);r.register_trigger_condition(cid,eligible)
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=10,
            limited_triggers=(LimitedTriggerSpec(event,cid,cid),)))
    r.validate();return r


class RingTossSecretCastTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'
    def game(self,hand=('DMF_105',),*,mode='normal',mana=10,weapon=None,hand_cap=None,enemy_hand=()):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero',hand=hand,deck=('card.1',)*8,mana=mana,max_mana=10,
                weapon_card_id=weapon,hand_cap=hand_cap),
            PlayerSetup('warrior.hero',hand=enemy_hand,deck=('card.1',)*8,mana=10,max_mana=10)),
            seed=623,generation_context=context(mode)),registry(mode))
    def pick(self,g,cid):self.choose(g,next(o.id for o in g.state.pending_choice.options if o.card_id==cid))
    def secret_ids(self,g):return tuple(g.state.entities[i].card_id for i in g.state.players[1].secrets)
    def no_leak(self,g,cid):
        self.assertNotIn(cid,json.dumps(g.for_player(2).observe()))
    def rollback(self,g):
        g=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);return g

    def test_two_complete_rows_four_primary_faces_and_both_real_corrupt_bodies(self):
        d=native.load_batch();rows={v['record']['id']:v['record']for v in d['dependencies']}
        for o in d['official_observations']:batch.check_face(rows[o['card_id']],o['face'],o['locale'])
        r=registry();self.assertEqual(r.card('DMF_105').hand_progress.upgrade_card_id,'DMF_105t')
        self.assertIn(Keyword.CORRUPTED,r.card('DMF_105t').keywords)
        self.assertFalse(d['new_standard_roots']);self.assertFalse(d['source_scope_bound'])

    def test_new_cast_destination_rejects_unrelated_queries_rewards_and_random_generation(self):
        fields=dict(player_id=1,pool_id=native.POOL,query=native.SECRETS,source_id=1,destination='cast')
        DiscoverFromPool(**fields);DiscoverFromPool(**dict(fields,discoveries=2))
        for delta in (dict(query=PoolQuery(kinds=(CardType.SPELL,))),dict(discoveries=3),dict(count=2),
                dict(delivery='after_all'),dict(replacement=False),dict(cost=CostSpec(delta=-1)),
                dict(temporary_until_turn=1),dict(unselected_to_hand=True),dict(unselected_to_hand=0),
                dict(entry_keywords=[]),dict(source_id=None)):
            with self.assertRaises(ValueError):DiscoverFromPool(**dict(fields,**delta))
        with self.assertRaises(ValueError):GenerateFromPool(1,native.POOL,native.SECRETS,source_id=1,destination='cast')

    def test_final_source_face_failure_does_not_partially_register_cards_or_behaviours(self):
        r=opening_registry();before=r.fingerprint();d=deepcopy(native.load_batch())
        d['dependencies'][-1]['record']['cost']=-1
        with patch.object(native,'load_batch',return_value=d),self.assertRaises(ValueError):native.register_ring_toss_secret_casts(r)
        self.assertEqual(r.fingerprint(),before)

    def test_base_ring_pays_four_then_secret_cast_is_free_and_never_enters_hand(self):
        g=self.game(mana=4);source=self.play(g,'DMF_105')
        self.assertEqual(g.state.players[1].mana,0);self.assertEqual({o.card_id for o in g.state.pending_choice.options},set((A,B,C)))
        self.pick(g,A);self.assertEqual(self.secret_ids(g),(A,));self.assertFalse(g.state.players[1].hand)
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(len(g.state.cast_history),2)
        cast=g.state.cast_history[-1];self.assertEqual((cast.caster_id,cast.origin,cast.from_zone),(source,'effect',None))
        self.assertEqual(g.state.entities[cast.source_id].zone,Zone.SECRET)
        self.assertFalse(any(e.kind=='card_added_to_hand' and e.target_id==cast.source_id for e in g._events))

    def test_full_hand_does_not_burn_or_block_the_direct_selected_secret(self):
        g=self.game(mana=4,weapon=FILL_HAND,hand_cap=1);self.play(g,'DMF_105')
        self.assertEqual(len(g.state.players[1].hand),1);self.pick(g,B)
        self.assertEqual(self.secret_ids(g),(B,));self.assertEqual(len(g.state.players[1].hand),1)

    def test_higher_actual_paid_play_corrupts_and_two_sequential_casts_pay_ring_only_once(self):
        g=self.game(('DMF_105',HIGH));eid=self.entity(g,'DMF_105').id;self.play(g,HIGH)
        self.assertEqual(g.state.entities[eid].card_id,'DMF_105t');self.play(g,'DMF_105t')
        self.assertEqual(g.state.players[1].mana,1);self.pick(g,A)
        self.assertEqual(self.secret_ids(g),(A,));self.assertIsNotNone(g.state.pending_choice)
        g=self.portable(g);self.pick(g,B)
        self.assertEqual(self.secret_ids(g),(A,B));self.assertEqual(g.state.players[1].mana,1)
        self.assertEqual(len(g.state.card_discovery_history),2);self.assertEqual(len(g.state.play_history),2)
        self.assertEqual(len(g.state.cast_history),4)

    def test_equal_cost_does_not_corrupt_the_original_form(self):
        g=self.game(('DMF_105',LOW));eid=self.entity(g,'DMF_105').id;self.play(g,LOW)
        self.assertEqual(g.state.entities[eid].card_id,'DMF_105')

    def test_corrupted_second_offer_keeps_existing_secret_and_duplicate_cast_does_not_install_twice(self):
        g=self.game(('DMF_105t',),mana=4);self.play(g,'DMF_105t');self.pick(g,A)
        self.assertIn(A,{o.card_id for o in g.state.pending_choice.options});self.pick(g,A)
        self.assertEqual(self.secret_ids(g),(A,));self.assertEqual(len(g.state.cast_history),3)
        self.assertEqual(g.state.players[1].mana,0);self.portable(g)

    def test_preexisting_duplicate_stays_in_the_original_offer_without_candidate_cropping(self):
        g=self.game(('DMF_105',PREP_ONE));self.play(g,PREP_ONE);self.play(g,'DMF_105')
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},set((A,B,C)))
        self.pick(g,A);self.assertEqual(self.secret_ids(g),(A,))

    def test_five_secret_capacity_keeps_the_nonduplicate_candidate_and_normal_cast_decides_installation(self):
        g=self.game(('DMF_105',PREP_FIVE),mode='full');self.play(g,PREP_FIVE)
        self.assertEqual(len(g.state.players[1].secrets),5);self.play(g,'DMF_105')
        self.assertEqual([o.card_id for o in g.state.pending_choice.options],[F]);self.pick(g,F)
        self.assertEqual(self.secret_ids(g),SECRETS[:5]);self.assertFalse(g.state.players[1].hand)
        self.assertEqual(g.state.entities[g.state.cast_history[-1].source_id].zone,Zone.GRAVEYARD)
        self.portable(g)

    def test_empty_complete_secret_domain_does_not_create_a_menu_or_consume_rng(self):
        g=self.game(mode='empty');before=g._rng.getstate();self.play(g,'DMF_105')
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g._rng.getstate(),before)
        self.assertFalse(g.state.card_discovery_history);self.assertEqual(g.state.players[1].mana,6)

    def test_original_menu_restores_replays_and_invalid_selection_rolls_back(self):
        g=self.game();self.play(g,'DMF_105');g=self.portable(g);saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.choose(g,'not-offered')
        self.assertEqual(g.snapshot(),saved);self.pick(g,C);self.portable(g)

    def test_selected_cast_wait_keeps_original_allocation_private_and_resumes_without_payment(self):
        g=self.game(('DMF_105t',),mana=4,weapon=WAIT);self.play(g,'DMF_105t');self.pick(g,A)
        # Secret activation is the existing synchronous payload step; its
        # accepted-event listener waits after activation and before completion.
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.secret_ids(g),(A,))
        self.assertEqual(g.state.pending_choice.options[0].id,'continue')
        self.no_leak(g,A);g=self.rollback(g)
        self.assertEqual(self.secret_ids(g),(A,));self.assertEqual(g.state.players[1].mana,0)
        self.pick(g,B);self.assertEqual(self.secret_ids(g),(A,B));self.portable(g)

    def test_after_discover_wait_occurs_after_actual_secret_cast_before_second_menu(self):
        g=self.game(('DMF_105t',),weapon=AFTER_WAIT);self.play(g,'DMF_105t');self.pick(g,A)
        self.assertEqual(self.secret_ids(g),(A,));self.assertEqual(g.state.pending_choice.options[0].id,'continue')
        g=self.rollback(g);self.assertEqual({o.card_id for o in g.state.pending_choice.options},set((A,B,C)))
        self.pick(g,C);self.assertEqual(self.secret_ids(g),(A,C))

    def test_cast_reaction_failure_restores_original_menu_choice_rng_and_allocators(self):
        g=self.game(weapon=FAIL_NOW);self.play(g,'DMF_105');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.pick(g,A)
        self.assertEqual(g.snapshot(),saved);self.assertFalse(g.state.players[1].secrets)

    def test_completion_rejects_another_physical_recipient_or_selected_card_identity(self):
        g=self.game();self.play(g,'DMF_105');self.pick(g,A)
        event=next(e for e in g._events if e.kind=='card_discovered')
        completion=FrameCodec(g.mechanics,g.registry).decode(json.loads(dict(event.data)['receipt']))
        for fact in (replace(completion.recipient,entity_id=g.state.players[1].hero_id),
                replace(completion.recipient,card_id=B)):
            with self.assertRaises(ValueError):validate_completion(g.state,g.registry,replace(completion,recipient=fact),closed=True)

    def test_installed_selected_secret_is_hidden_and_later_runs_its_ordinary_trigger(self):
        g=self.game(enemy_hand=(FILL,));self.play(g,'DMF_105');self.pick(g,A);self.no_leak(g,A)
        g.apply(EndTurn(1));self.play(g,FILL,player=2)
        self.assertFalse(g.state.players[1].secrets)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,29);self.portable(g)

    def test_real_local_complete_pool_and_existing_ranger_scout_copy_consumer(self):
        f=build_cn37_local_pool_format();r=f.registry
        candidates=resolve_candidates(r,f.context,native.POOL,native.SECRETS,current_class=CardClass.MAGE)
        self.assertEqual(len(candidates),6)
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=('DMF_105',),board=('GDB_841',),mana=4,max_mana=10),
            PlayerSetup('HERO_08',deck=('CORE_EX1_162',)*8,mana=10,max_mana=10)),seed=623,generation_context=f.context),r)
        self.play(g,'DMF_105');offered={o.card_id for o in g.state.pending_choice.options}
        self.assertTrue(offered <= {m.card_id for m in candidates});cid=sorted(offered)[0];self.pick(g,cid)
        self.assertEqual(self.secret_ids(g),(cid,));self.assertEqual(self.entity(g,cid).base_cost,r.card(cid).cost)
        self.assertNotEqual(self.entity(g,cid).id,g.state.players[1].secrets[0]);self.assertEqual(g.state.players[1].mana,0)


if __name__=='__main__':unittest.main()
