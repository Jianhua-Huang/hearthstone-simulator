"""Fresh genuine discovery after the original physical same-turn hand play."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import json,random,unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import past_lightning_reflexes as native
from hs_sim.engine import EndTurn,Game,PlayCard,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import ChoiceOption,Draw,InvokeBehavior,RandomDamage,RequestChoice
from hs_sim.engine.hand_choice_followups import DiscoverForPlayFollowup,public_followups,validate_shape
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import CardClass,CardDefinition,CardType,SpellSchool,TriggerSpec
from hs_sim.engine.pools import DiscoverFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates,sample_candidates
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference,DiscardCard
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest

CARD=native.ROOTS[0];P='k677.'
N1,N2,N3,N4,FIRE,DRUID,NEUTRAL,DUMP,AUTO,WATCH,FAIL,COUNTER=(P+x for x in
    ('n1','n2','n3','n4','fire','druid','neutral','dump','auto','watch','fail','counter'))
CTX=GenerationContext('k677-complete-Nature-fixture','experimental')

@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()

@lru_cache(None)
def fixture(mode='four',role='writer'):
    r=opening_registry();native.register_past_lightning_reflexes(r)
    for cid in(N1,N2,N3,N4,FIRE,DRUID,NEUTRAL):
        r.register_behavior(cid,lambda c,cid=cid:(Draw(c.player_id,10,c.source_id),)if cid==N4 else())
        cc=CardClass.DRUID if cid==DRUID else CardClass.NEUTRAL if cid==NEUTRAL else CardClass.MAGE
        card=CardDefinition(cid,cid,CardType.SPELL,cost=1,on_play=cid,
            spell_school=SpellSchool.FIRE if cid==FIRE else SpellSchool.NATURE,metadata=metadata(cc))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    members=(N1,N2,N3,N4,FIRE,DRUID,NEUTRAL)if mode=='four'else(N1,)if mode=='one'else(N4,)if mode=='draw'else(FIRE,DRUID)
    r.register_pool(PoolDefinition('constructed.cards','k677-'+mode,CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in members),complete=True))
    def discard(c):
        root=next(x for x in c.state.hand_choice_followups if x.status=='armed')
        return(DiscardCard(CardReference.capture(c.state.entities[root.initial_entity_id]),c.source_id),)
    r.register_behavior(DUMP,discard);r.register_card(CardDefinition(DUMP,DUMP,CardType.SPELL,on_play=DUMP,metadata=metadata(collectible=False)))
    r.register_behavior(AUTO,lambda c:(CastSpell(c.player_id,CARD,c.source_id),)if c.event.player_id==c.player_id else())
    r.register_card(CardDefinition(AUTO,AUTO,CardType.MINION,health=20,
        triggers=(TriggerSpec('turn_started',AUTO),),metadata=metadata(collectible=False,tribes=())))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K677 deliberate rollback')))
    r.register_behavior(WATCH,lambda c:(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
        ChoiceOption('fault','Fail',(RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),
            InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),))
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,
        triggers=(TriggerSpec('card_discovered',WATCH),),metadata=metadata(collectible=False,tribes=())))
    r.register_behavior(COUNTER,lambda c:(CounterSpell(dict(c.event.data)['window_id']),)
        if c.event.player_id!=c.player_id and c.state.entities[c.event.source_id].card_id in(N1,N2,N3,NEUTRAL)else())
    r.register_card(CardDefinition(COUNTER,COUNTER,CardType.MINION,health=20,
        triggers=(TriggerSpec('card_committed',COUNTER),),metadata=metadata(collectible=False,tribes=())))
    r.validate();return r


class LightningReflexesTests(CardBatchTestMixin,unittest.TestCase):
    mode='four'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(mode,role))
    def game(self,hand=(CARD,),*,mode='four',board=(),enemy=(),active=1):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand if active==1 else(),board=board if active==1 else(),
                deck=('card.1',)*20,mana=10,max_mana=10),
            PlayerSetup('mage.hero',hand=hand if active==2 else(),board=board if active==2 else enemy,
                deck=('card.2',)*20,mana=10,max_mana=10)),active_player=active,seed=677,generation_context=CTX),fixture(mode,'writer'))
    def choose_card(self,g,cid):
        option=next(o for o in g.state.pending_choice.options if o.card_id==cid)
        self.choose(g,option.id)
    def first(self,g,cid=N1,p=1):
        self.play(g,CARD,player=p)
        if cid not in [o.card_id for o in g.state.pending_choice.options]:cid=g.state.pending_choice.options[0].card_id
        self.choose_card(g,cid);return g.state.hand_choice_followups[-1]
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def finish(self,g):
        n=0
        while g.state.pending_choice is not None:
            self.choose(g,g.state.pending_choice.options[0].id);n+=1;self.assertLess(n,15)

    def test_complete_original_card_four_primary_faces_and_actual_enchantment_evidence(self):
        d=native.load_batch();self.assertEqual((len(d['cards']),len(d['official_observations'])),(1,4))
        self.assertEqual(d['evidence_only'][0]['record']['id'],'TTN_317e')
        r=fixture('four','writer');self.assertEqual(canonical_digest(asdict(r.card(CARD))),d['cards'][0]['definition_sha256'])
        self.assertEqual(len(d['original_shaman_member_ids']),71);self.assertFalse(d['complete_shaman_source_bound'])

    def test_real_paid_entry_offers_only_full_current_class_or_neutral_nature_spells(self):
        g=self.game();source=self.play(g,CARD);root=g.state.hand_choice_followups[0]
        self.assertEqual(g.state.players[1].mana,9);self.assertEqual(len(root.offers),3)
        self.assertEqual({x.card_id for x in root.available_pool},{N1,N2,N3,N4,NEUTRAL})
        self.assertEqual(root.request.source_id,source);self.assertEqual(root.reward_mode,'rediscover')
        self.assertNotIn(FIRE,{x.card_id for x in root.offers});self.assertNotIn(DRUID,{x.card_id for x in root.offers})
        self.portable(g)

    def test_original_play_creates_separate_complete_fresh_offer_and_no_further_followup(self):
        g=self.game(mode='one');parent=self.first(g);g=self.portable(g)
        self.play(g,N1);self.assertIsNotNone(g.state.pending_choice)
        parent,child=g.state.hand_choice_followups
        self.assertEqual((parent.status,parent.reward_followup_id,child.parent_followup_id,child.reward_mode),('completed',2,1,'terminal'))
        self.assertEqual([x.card_id for x in child.available_pool],[N1])
        self.assertEqual([x.card_id for x in child.offers],[N1])
        self.assertEqual(child.initial_choice.purpose.value,'card_discovery')
        g=self.portable(g);self.choose_card(g,N1);self.assertEqual(g.state.hand_choice_followups[1].status,'terminal')
        self.play(g,N1);self.assertEqual(len(g.state.hand_choice_followups),2);self.assertIsNone(g.state.pending_choice)
        self.assertEqual(len(g.state.card_discovery_history),2);self.portable(g)

    def test_reward_samples_whole_pool_again_with_its_own_preserved_rng_and_can_repeat_first_card(self):
        g=self.game();parent=self.first(g);picked=g.state.entities[parent.initial_entity_id].card_id
        before=g._rng.getstate();self.play(g,picked);child=g.state.hand_choice_followups[1]
        self.assertEqual(child.rng_before,before);self.assertEqual(child.rng_after,g._rng.getstate())
        self.assertEqual(child.available_pool,parent.available_pool);self.assertIn(picked,{x.card_id for x in child.available_pool})
        self.assertEqual(len(child.available_pool),5);self.assertEqual(len(child.offers),3)
        self.assertIsNone(parent.reward_result);g=self.portable(g);self.finish(g);self.portable(g)

    def test_same_name_preexisting_physical_card_does_not_consume_original_discovered_residence(self):
        g=self.game((CARD,N1),mode='one');old=self.entity(g,N1).id;root=self.first(g)
        self.assertNotEqual(root.initial_entity_id,old)
        g.apply(PlayCard(1,old));self.assertEqual(g.state.hand_choice_followups[0].status,'armed')
        self.assertEqual(len(g.state.hand_choice_followups),1)
        g.apply(PlayCard(1,root.initial_entity_id));self.assertEqual(len(g.state.hand_choice_followups),2)
        self.finish(g);self.portable(g)

    def test_turn_end_expires_first_original_witness_and_later_play_does_not_rediscover(self):
        g=self.game(mode='one');root=self.first(g);self.cycle(g)
        self.assertEqual(g.state.hand_choice_followups[0].status,'expired')
        g.apply(PlayCard(1,root.initial_entity_id));self.assertEqual(len(g.state.hand_choice_followups),1)
        self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_discard_loses_original_witness_without_a_reward_or_rebinding_other_hand_card(self):
        g=self.game((CARD,DUMP,N1),mode='one');root=self.first(g);self.play(g,DUMP)
        self.assertEqual(g.state.hand_choice_followups[0].status,'lost');self.play(g,N1)
        self.assertEqual(len(g.state.hand_choice_followups),1);self.assertNotIn(root.initial_entity_id,g.state.players[1].hand)
        self.portable(g)

    def test_empty_original_current_class_pool_pays_without_choice_rng_or_partial_pool_fallback(self):
        g=self.game(mode='empty');before=g._rng.getstate();self.play(g,CARD)
        self.assertEqual(g._rng.getstate(),before);self.assertEqual(g.state.hand_choice_followups[0].status,'empty')
        self.assertEqual(g.state.players[1].mana,9);self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_countered_original_selected_hand_play_still_claims_one_fresh_discovery(self):
        g=self.game(mode='one',enemy=(COUNTER,));self.first(g);self.play(g,N1)
        self.assertEqual(g.state.cast_history[-1].failure,'countered');self.assertEqual(len(g.state.hand_choice_followups),2)
        self.finish(g);self.portable(g)

    def test_second_reward_is_full_real_discovery_even_when_played_spell_fills_hand_and_burns_it(self):
        g=self.game(mode='draw');self.first(g,N4);self.play(g,N4)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertIsNotNone(g.state.pending_choice)
        self.finish(g);parent,child=g.state.hand_choice_followups
        self.assertEqual((parent.status,child.status),('completed','not_hand'))
        self.assertEqual(len(g.state.card_discovery_history),2);self.portable(g)

    def test_automatic_initial_discovery_full_hand_burn_does_not_arm_a_reward(self):
        g=self.game((N1,)*10,mode='one',board=(AUTO,));self.cycle(g)
        self.assertEqual(len(g.state.players[1].hand),10)
        self.assertEqual(len(g.state.hand_choice_followups),1);self.assertEqual(g.state.hand_choice_followups[0].status,'not_hand')
        self.assertIsNone(g.state.hand_choice_followups[0].hand_entry_id);self.portable(g)

    def test_actual_second_player_owns_first_choice_payment_and_terminal_reward(self):
        g=self.game(mode='one',active=2);self.first(g,p=2);self.assertEqual(g.state.players[2].mana,9)
        self.play(g,N1,player=2);self.assertEqual(g.state.pending_choice.player_id,2);g=self.portable(g)
        self.finish(g);self.assertEqual(g.state.hand_choice_followups[1].request.player_id,2);self.portable(g)

    def test_two_actual_original_sources_keep_separate_physical_witnesses_and_child_ownership(self):
        g=self.game((CARD,CARD),mode='one');first=self.first(g);second=self.first(g)
        g.apply(PlayCard(1,first.initial_entity_id));self.finish(g)
        self.assertEqual([x.status for x in g.state.hand_choice_followups[:2]],['completed','armed'])
        self.assertEqual(g.state.hand_choice_followups[2].parent_followup_id,1)
        g.apply(PlayCard(1,second.initial_entity_id));self.finish(g)
        self.assertEqual(g.state.hand_choice_followups[3].parent_followup_id,2);self.portable(g)

    def test_both_real_discovery_delivery_reaction_waits_restore_and_failed_choice_rolls_back_rng(self):
        g=self.game(mode='one',board=(WATCH,));self.first(g)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.finish(g);self.play(g,N1)
        self.choose_card(g,N1);self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.finish(g);self.portable(g)

    def test_owner_observation_describes_new_discovery_without_showing_old_remaining_options_or_private_rng(self):
        g=self.game(mode='one');root=self.first(g);entity=g.state.entities[root.initial_entity_id]
        visible=public_followups(g.state,g.registry,entity)
        self.assertEqual(visible,[dict(source_card_id=CARD,expires_turn=g.state.turn,remaining=[],discover_again=True)])
        opponent=json.dumps(g.for_player(2).observe());self.assertNotIn('play_followups',opponent)
        for p in(1,2):
            text=json.dumps(g.for_player(p).observe())
            for key in('rng_before','parent_followup_id','reward_followup_id','available_pool'):self.assertNotIn('"'+key+'"',text)

    def test_fresh_links_reject_missing_borrowed_reversed_or_duplicate_child_without_weakening_old_modes(self):
        g=self.game(mode='one');self.first(g);self.play(g,N1)
        for changes in ({'reward_followup_id':1},{'reward_followup_id':3},{'reward_followup_id':None}):
            state=deepcopy(g.state);state.hand_choice_followups[0]=replace(state.hand_choice_followups[0],**changes)
            with self.assertRaises(ValueError):validate_shape(state)
        state=deepcopy(g.state);state.hand_choice_followups[1]=replace(state.hand_choice_followups[1],parent_followup_id=2)
        with self.assertRaises(ValueError):validate_shape(state)
        req=DiscoverFromPool(1,'constructed.cards',native.QUERY,source_id=1)
        with self.assertRaises(ValueError):DiscoverForPlayFollowup(req,'terminal')
        with self.assertRaises(ValueError):DiscoverForPlayFollowup(req,'rediscover',1)
        with self.assertRaises(ValueError):DiscoverForPlayFollowup(replace(req,count=2),'rediscover')
        with self.assertRaises(ValueError):DiscoverForPlayFollowup(replace(req,query=replace(native.QUERY,spell_schools=())),'rediscover')

    def test_real_standard_host_plays_discovered_actual_bolt_then_fresh_full_nature_offer(self):
        self.mode='host';h=host('writer');bolt='CORE_EX1_238'
        pool=resolve_candidates(h.registry,h.context,'constructed.cards',native.QUERY,current_class=CardClass.SHAMAN,
            source_card_id=CARD,player_id=1,exclude_source_by_rule=True)
        self.assertIn(bolt,{m.card_id for m in pool})
        seed=next(seed for seed in range(100)if bolt in sample_candidates(random.Random(seed),pool,3,replacement=False))
        deck=('CORE_EX1_169',)*12
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_02',hand=(CARD,),deck=deck,mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=deck,mana=10,max_mana=10)),seed=seed,generation_context=h.context),h.registry)
        self.play(g,CARD);self.choose_card(g,bolt);g=self.portable(g)
        self.play(g,bolt,g.state.players[2].hero_id);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,27)
        self.assertEqual(len(g.state.hand_choice_followups),2);self.assertEqual(g.state.hand_choice_followups[1].available_pool,pool)
        g=self.portable(g);self.finish(g);self.portable(g)
