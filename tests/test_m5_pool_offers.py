"""Grouped offers, payment eligibility, frozen selection and temporary delivery."""
from hs_sim.engine.model import CostAuraSpec
from dataclasses import replace
import json
import unittest
from hs_sim.engine import (Game,Scenario,PlayerSetup,CardType,CardClass,CardDefinition,CardMetadata,Rarity,
    PlayCard,UseHeroPower,EndTurn,SelectChoice,CostSpec,PaymentType,Resource,Keyword,TriggerSpec,Zone,
    PoolQuery,GenerationContext,ChooseFromPools,PoolOfferGroup,quote_generated_cost,CreateTemporaryCard,
    Imbue,RewindSpec,ResolutionError,ResolutionLimitExceeded,SnapshotError,IllegalAction,TargetSpec)
from hs_sim.engine.effects import (AddCostModifier,GrantCostAura,GainArmor,Damage,AddToHand,RequestChoice,
    ChoiceOption,InvokeBehavior,Summon,Silence,ReturnToHand,ReplaceHeroPower,ReplaceHero,RefreshHeroPower)
from hs_sim.engine.pools import PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.zones import CardReference,CopyCard,MoveCard
from hs_sim.engine.representative import build_registry,MOON_POOL_ID,MOON_SAMPLE_IDS,IMBUE_CLASS_POWERS
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
CTX=GenerationContext('local-2026-09-23','experimental')


class OfferFixtures:
    def setUp(self):
        self.r=build_registry()
        for cid,kind,cost in (('cm',CardType.MINION,2),('dm',CardType.MINION,7),('cs',CardType.SPELL,0),('ds',CardType.SPELL,7)):
            self.r.register_card(CardDefinition(cid,cid,kind,cost=cost,attack=1 if kind==CardType.MINION else 0,
                health=2 if kind==CardType.MINION else 0,
                metadata=CardMetadata(True,(CardClass.PRIEST,),Rarity.COMMON,tribes=())))
        self.pool('test',('cm','dm','cs','ds'))
        self.script('offer',lambda c:[self.offer(c)])
    def pool(self,pid,ids):
        for cid in ids:
            if cid not in self.r.pool_cards:self.r.register_pool_card(PoolCard.from_definition(self.r.card(cid)))
        self.r.register_pool(PoolDefinition(pid,'v1',CTX.target_id,CTX.mode,tuple(PoolMember(cid) for cid in ids)))
    def script(self,cid,fn,**kw):
        self.r.register_behavior(cid,fn);self.r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,**kw))
    def watch(self,fn,event='card_added_to_hand'):
        self.r.register_behavior('watch',fn)
        self.r.register_card(CardDefinition('watch','watch',CardType.MINION,health=4,triggers=(TriggerSpec(event,'watch'),)))
    def offer(self,c,**kw):
        values=dict(player_id=c.player_id,groups=tuple(PoolOfferGroup('test',PoolQuery(kinds=(kind,)))
            for kind in (CardType.MINION,CardType.SPELL)),source_id=c.source_id,
            cost=CostSpec(delta=-1),temporary_until=c.state.turn,affordable=True)
        values.update(kw);return ChooseFromPools(**values)
    def game(self,hand=('offer',),board=(),mana=10,context=CTX,power='EDR_449p'):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_09',hand=hand,board=board,
            hero_power_card_id=power,mana=mana,max_mana=10,deck=('CS2_182',)*4),
            PlayerSetup('HERO_08',mana=10,max_mana=10,deck=('CS2_182',)*4)),seed=66,generation_context=context),self.r)
    def play(self,g,cid='offer',target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target));return eid
    def use(self,g):g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
    def choose(self,g,cid=None):
        c=g.state.pending_choice;opt=next(o for o in c.options if cid is None or o.card_id==cid)
        g.apply(SelectChoice(c.player_id,c.id,(opt.id,)));return opt.card_id
    def hand(self,g,p=1):return [g.state.entities[i] for i in g.state.players[p].hand]
    def check(self,g):
        snapshot=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snapshot,self.r).snapshot(),snapshot)
        self.assertEqual(g.clone().snapshot(),snapshot)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),snapshot)
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as e:Game.from_snapshot(s,self.r)
        self.assertNotIn('digest mismatch',str(e.exception))


class OfferTests(OfferFixtures,unittest.TestCase):
    def test_hypothetical_quote_is_pure_and_matches_created_cost(self):
        g=self.game(mana=2);before=g.snapshot();q=quote_generated_cost(g.state,self.r,1,'cm',cost=CostSpec(delta=-1))
        self.assertIsNone(q.entity_id);self.assertEqual(q.amount,1);self.assertEqual(g.snapshot(),before)
        self.play(g);self.choose(g,'cm');self.assertEqual(g.quote_cost(self.hand(g)[0].id).amount,q.amount);self.check(g)
    def test_generated_quote_applies_aura_and_finite_modifier_without_consuming(self):
        self.script('mods',lambda c:[GrantCostAura(c.state.players[1].board[0],CostAuraSpec(CostSpec(delta=2))),AddCostModifier(1,CostSpec(delta=-1),uses_remaining=1)])
        g=self.game(hand=('mods','offer'),board=('CS2_182',));self.play(g,'mods');before=g.snapshot()
        q=quote_generated_cost(g.state,self.r,1,'cm',cost=CostSpec(delta=-1))
        self.assertEqual(q.amount,2);self.assertEqual(len(q.consumable_ids),1);self.assertEqual(g.snapshot(),before)
        self.play(g);cid=self.choose(g);card=self.hand(g)[0]
        self.assertEqual(g.quote_cost(card.id).amount,quote_generated_cost(g.state,self.r,1,cid,cost=CostSpec(delta=-1)).amount)
        self.check(g)
    def test_final_temporary_floor_applies_after_player_set_zero(self):
        self.script('floor',lambda c:[AddCostModifier(1,CostSpec(set_to=0)),self.offer(c,minimum_cost=2)])
        g=self.game(hand=('floor',),mana=2);self.play(g,'floor')
        self.assertTrue(all(o.preview.cost==2 for o in g.state.pending_choice.options));self.choose(g)
        self.assertEqual(g.quote_cost(self.hand(g)[0].id).amount,2);self.check(g)
    def test_grouped_offers_contain_one_minion_and_one_spell(self):
        g=self.game();self.play(g);c=g.state.pending_choice
        self.assertEqual([self.r.card(o.card_id).kind for o in c.options],[CardType.MINION,CardType.SPELL]);self.check(g)
    def test_multiple_results_per_group_are_distinct(self):
        self.script('many',lambda c:[self.offer(c,groups=(PoolOfferGroup('test',count=4),))])
        g=self.game(hand=('many',));self.play(g,'many');self.assertEqual(len({o.card_id for o in g.state.pending_choice.options}),4);self.check(g)
    def test_overlapping_groups_keep_separate_options(self):
        self.pool('single',('cs',));self.script('same',lambda c:[self.offer(c,groups=(PoolOfferGroup('single'),PoolOfferGroup('single')))])
        g=self.game(hand=('same',));self.play(g,'same');self.assertEqual([o.card_id for o in g.state.pending_choice.options],['cs','cs'])
        self.assertEqual(len({o.id for o in g.state.pending_choice.options}),2);self.choose(g);self.assertEqual(len(self.hand(g)),1);self.check(g)
    def test_affordability_uses_discount_and_remaining_mana(self):
        g=self.game(mana=1);self.play(g)
        self.assertEqual([o.card_id for o in g.state.pending_choice.options],['cm','cs']);self.check(g)
    def test_ordinary_offers_can_include_unaffordable_cards(self):
        self.script('any',lambda c:[self.offer(c,affordable=False,groups=(PoolOfferGroup('test',count=4),))])
        g=self.game(hand=('any',),mana=0);self.play(g,'any');self.assertEqual(len(g.state.pending_choice.options),4);self.check(g)
    def test_empty_group_omitted_without_borrowing_other_kind(self):
        g=self.game(mana=0);self.play(g)
        self.assertEqual([o.card_id for o in g.state.pending_choice.options],['cs']);self.choose(g);self.check(g)
    def test_empty_all_groups_preserves_random_state_and_continues(self):
        self.pool('expensive',('dm','ds'));self.script('empty',lambda c:[self.offer(c,groups=(PoolOfferGroup('expensive'),)),GainArmor(1,2)])
        g=self.game(hand=('empty',),mana=0);rng=g._rng.getstate();self.play(g,'empty')
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2);self.check(g)
    def test_minion_offered_on_full_board(self):
        g=self.game(board=('CS2_182',)*7);self.play(g);cid=g.state.pending_choice.options[0].card_id;self.choose(g,cid)
        self.assertFalse(any(isinstance(a,PlayCard) and a.entity_id==self.hand(g)[0].id for a in g.legal_actions()));self.check(g)
    def test_required_target_is_not_an_affordability_filter(self):
        self.pool('target',('EX1_332',));self.script('targeted',lambda c:[self.offer(c,groups=(PoolOfferGroup('target'),))])
        g=self.game(hand=('targeted',),mana=0);self.play(g,'targeted');self.choose(g)
        self.assertFalse(any(isinstance(a,PlayCard) for a in g.legal_actions()));self.check(g)
    def test_health_payment_eligibility_shares_strict_survival_check(self):
        self.pool('hp',('cm','dm'));self.script('hp',lambda c:[Damage(c.state.players[1].hero_id,24),
            self.offer(c,groups=(PoolOfferGroup('hp',count=2),),cost=CostSpec(payment=PaymentType.HEALTH))])
        g=self.game(hand=('hp',),mana=0);self.play(g,'hp');self.assertEqual([o.card_id for o in g.state.pending_choice.options],['cm']);self.check(g)
    def test_armor_payment_uses_actual_armor(self):
        self.pool('armor',('cm','dm'));self.script('armor',lambda c:[GainArmor(1,2),
            self.offer(c,groups=(PoolOfferGroup('armor',count=2),),cost=CostSpec(payment=PaymentType.ARMOR))])
        g=self.game(hand=('armor',),mana=0);self.play(g,'armor');self.assertEqual([o.card_id for o in g.state.pending_choice.options],['cm']);self.choose(g);self.check(g)
    def test_corpse_payment_does_not_use_mana(self):
        from hs_sim.engine.effects import GainResource
        self.pool('corpses',('cm','dm'));self.script('corpses',lambda c:[GainResource(1,Resource.CORPSES,2),
            self.offer(c,groups=(PoolOfferGroup('corpses',count=2),),cost=CostSpec(payment=PaymentType.CORPSES))])
        g=self.game(hand=('corpses',),mana=0);self.play(g,'corpses');self.assertEqual([o.card_id for o in g.state.pending_choice.options],['cm']);self.choose(g);self.check(g)
    def test_captured_options_survive_price_changes_before_delivery(self):
        self.watch(lambda c:[AddCostModifier(1,CostSpec(delta=20))],'choice_selected')
        g=self.game(board=('watch',),mana=1);self.play(g);offered=g.state.pending_choice.options;self.check(g)
        self.choose(g,'cm');self.assertEqual(self.hand(g)[0].card_id,'cm');self.assertEqual(g.quote_cost(self.hand(g)[0].id).amount,21)
        self.assertEqual(offered[0].preview.cost,1);self.check(g)
    def test_offer_does_not_consume_next_card_discount(self):
        self.script('discount',lambda c:[AddCostModifier(1,CostSpec(delta=-6),uses_remaining=1),self.offer(c)])
        g=self.game(hand=('discount',));self.play(g,'discount');self.assertEqual(g.state.players[1].cost_modifiers[0].uses_remaining,1)
        self.choose(g);self.assertEqual(g.state.players[1].cost_modifiers[0].uses_remaining,1);self.check(g)
    def test_temporary_cost_and_lifetime_visible_to_creation_reactions(self):
        self.watch(lambda c:[GainArmor(1,2)] if c.state.entities[c.event.target_id].hand_lifetime is not None and
            c.state.entities[c.event.target_id].cost==1 else [])
        g=self.game(board=('watch',),mana=1);self.play(g);self.choose(g,'cm')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2);self.check(g)
    def test_full_hand_still_offers_then_burns_selected_card(self):
        self.script('full',lambda c:[AddToHand(1,'CS2_182'),self.offer(c)])
        g=self.game(hand=('full',)+('CS2_182',)*9);self.play(g,'full');self.choose(g)
        self.assertEqual(len(self.hand(g)),10);self.assertEqual(g.events[-1].kind,'card_played')
        self.assertTrue(any(e.kind=='card_burned' for e in g.events));self.check(g)
    def test_no_entity_or_hand_entry_created_for_unchosen_candidates(self):
        g=self.game(mana=1);before=g.state.next_entity_id;entries=len(g.state.hand_entries);self.play(g)
        self.assertEqual(g.state.next_entity_id,before);self.assertEqual(len(g.state.hand_entries),entries)
        self.choose(g);self.assertEqual(g.state.next_entity_id,before+1);self.check(g)
    def test_card_expires_without_discard_or_death(self):
        g=self.game(mana=1);self.play(g);self.choose(g,'cm');card=self.hand(g)[0];g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[card.id].zone,Zone.GRAVEYARD);self.assertFalse(g.state.death_history)
        self.assertTrue(any(e.kind=='card_expired' for e in g.events));self.check(g)
    def test_played_temporary_minion_survives_deadline(self):
        g=self.game(mana=1);self.play(g);self.choose(g,'cm');card=self.hand(g)[0];self.play(g,'cm');g.apply(EndTurn(1))
        self.assertIn(card.id,g.state.players[1].board);self.assertIsNone(g.state.entities[card.id].hand_lifetime);self.check(g)
    def test_current_copy_and_transfer_preserve_deadline(self):
        self.script('move',lambda c:[CopyCard(CardReference.capture(c.state.entities[c.state.players[1].hand[0]]),2),
            MoveCard(CardReference.capture(c.state.entities[c.state.players[1].hand[0]]),2,Zone.HAND)])
        g=self.game(hand=('offer','move'),mana=1);self.play(g);self.choose(g,'cm')
        g.apply(PlayCard(1,next(e.id for e in self.hand(g) if e.card_id=='move')))
        self.assertEqual(len(self.hand(g,2)),2);self.assertTrue(all(e.hand_lifetime.expires_turn==1 for e in self.hand(g,2)))
        ids=[e.id for e in self.hand(g,2)];g.apply(EndTurn(1))
        self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in ids));self.check(g)
    def test_deck_move_clears_expired_lifetime_without_destroying_card(self):
        self.script('deck',lambda c:[MoveCard(CardReference.capture(c.state.entities[c.state.players[1].hand[0]]),1,Zone.DECK,'top')])
        g=self.game(hand=('offer','deck'),mana=1);self.play(g);self.choose(g,'cm');card=next(e for e in self.hand(g) if e.card_id=='cm')
        self.play(g,'deck');g.apply(EndTurn(1));self.assertIn(card.id,g.state.players[1].deck)
        self.assertIsNone(g.state.entities[card.id].hand_lifetime);self.assertEqual(g.state.entities[card.id].cost,1);self.check(g)
    def test_return_to_hand_clears_temporary_cost_and_deadline(self):
        self.script('bounce',lambda c:[ReturnToHand(c.state.players[1].board[0])])
        g=self.game(hand=('offer','bounce'),mana=1);self.play(g);self.choose(g,'cm');self.play(g,'cm');self.play(g,'bounce')
        card=self.hand(g)[0];self.assertIsNone(card.hand_lifetime);self.assertEqual(card.cost,2);self.check(g)
    def test_non_temporary_delivery_keeps_cost_without_deadline(self):
        self.script('normal',lambda c:[self.offer(c,temporary_until=None)])
        g=self.game(hand=('normal',),mana=1);self.play(g,'normal');self.choose(g,'cm')
        self.assertIsNone(self.hand(g)[0].hand_lifetime);self.assertEqual(self.hand(g)[0].cost,1);self.check(g)
    def test_missing_context_rolls_back(self):
        g=self.game(context=None);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)
    def test_all_groups_validated_before_any_random_draw(self):
        self.script('missing',lambda c:[self.offer(c,groups=(PoolOfferGroup('test'),PoolOfferGroup('missing')))])
        g=self.game(hand=('missing',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'missing')
        self.assertEqual(g.snapshot(),before)
    def test_unadapted_expensive_candidate_is_not_filtered_out(self):
        d=CardDefinition('missing','missing',CardType.MINION,cost=99,health=2,metadata=CardMetadata(True,(CardClass.PRIEST,),Rarity.COMMON))
        self.r.register_pool_card(PoolCard.from_definition(d));self.r.register_pool(PoolDefinition('gap','v1',CTX.target_id,CTX.mode,(PoolMember('missing'),)))
        self.script('gap',lambda c:[self.offer(c,groups=(PoolOfferGroup('gap'),))])
        g=self.game(hand=('gap',),mana=0);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'gap')
        self.assertEqual(g.snapshot(),before)
    def test_cost_filter_mismatch_rejects_all_candidates_before_rng(self):
        self.script('badcost',lambda c:[self.offer(c,cost=CostSpec(delta=-1,card_types=(CardType.SPELL,)))])
        g=self.game(hand=('badcost',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'badcost')
        self.assertEqual(g.snapshot(),before)
    def test_expired_creation_cost_is_transactional(self):
        self.script('expired',lambda c:[CreateTemporaryCard(1,'cm',c.state.turn,cost=CostSpec(delta=-1),cost_expires_turn=1)])
        g=self.game(hand=('expired',));g.apply(EndTurn(1));g.apply(EndTurn(2));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'expired')
        self.assertEqual(g.snapshot(),before)
    def test_choice_limit_checked_before_sampling(self):
        self.script('limit',lambda c:[self.offer(c,groups=(PoolOfferGroup('test',count=1000),))])
        g=self.game(hand=('limit',));before=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g,'limit')
        self.assertEqual(g.snapshot(),before)
    def test_paused_offer_restores_and_selects_same_result(self):
        g=self.game();self.play(g);self.check(g);restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)
    def test_missing_pool_in_frozen_receipt_rejected(self):
        g=self.game();self.play(g);s=g.snapshot()
        def change(v):
            if isinstance(v,dict):
                if v.get('type','').endswith('.PoolOfferGroup'):v['fields']['pool_id']='missing'
                for x in v.values():change(x)
            elif isinstance(v,list):
                for x in v:change(x)
        change(s);self.reject(s)
    def test_invalid_selected_identity_in_receipt_rejected(self):
        g=self.game();self.play(g);s=g.snapshot()
        def change(v):
            if isinstance(v,dict):
                if v.get('type','').endswith('.ResolvePoolOffer'):v['fields']['card_id']='CS2_182'
                for x in v.values():change(x)
            elif isinstance(v,list):
                for x in v:change(x)
        change(s);self.reject(s)
    def test_failure_after_delivery_rolls_back_only_choice_submission(self):
        self.r.register_behavior('fail',lambda c:[Summon(1,'missing')])
        self.script('bad',lambda c:[self.offer(c),InvokeBehavior('fail',c.source_id,1)])
        g=self.game(hand=('bad',));self.play(g,'bad');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),before);self.check(g)
    def test_rewind_does_not_accumulate_temporary_cards(self):
        self.script('rewind',lambda c:[self.offer(c)],keywords=(Keyword.REWIND,),rewind=RewindSpec())
        g=self.game(hand=('rewind',));self.play(g,'rewind');self.choose(g);self.check(g)
        c=g.state.pending_choice;g.apply(SelectChoice(1,c.id,('retry',)));self.assertFalse(self.hand(g));self.check(g)
        self.choose(g);self.assertEqual(len(self.hand(g)),1);self.check(g)
    def test_opponent_does_not_see_offer_cards_or_reduced_preview(self):
        g=self.game(mana=1);self.play(g)
        other=json.dumps(g.observe(2));self.assertNotIn('"cm"',other);self.assertNotIn('"cs"',other)
        own=g.observe(1)['pending_choice'];self.assertEqual(len(own['options']),2);self.choose(g,'cm')
        self.assertNotIn('"cm"',json.dumps(g.observe(2)));self.check(g)
    def test_lethal_selection_reaction_prevents_delivery(self):
        self.watch(lambda c:[Damage(c.state.players[2].hero_id,50)],'choice_selected')
        g=self.game(board=('watch',));self.play(g);self.choose(g);self.assertFalse(self.hand(g));self.check(g)
    def test_invalid_declarations_rejected(self):
        for kw in ({'groups':()},{'affordable':1},{'minimum_cost':1},{'groups':('bad',)},{'temporary_until':0},{'cost':{}}):
            values=dict(player_id=1,groups=(PoolOfferGroup('test'),));values.update(kw)
            with self.subTest(kw=kw),self.assertRaises(ValueError):ChooseFromPools(**values)
        with self.assertRaises(ValueError):PoolOfferGroup('test',count=0)
    def test_old_snapshot65_rejected(self):
        g=self.game();s=g.snapshot();s['schema_version']=65;self.reject(s)

    def test_deferred_offer_reads_resources_when_it_executes(self):
        self.script('wait',lambda c:[RequestChoice(1,(ChoiceOption('raise','raise',(AddCostModifier(1,CostSpec(delta=10)),)),)),self.offer(c)])
        g=self.game(hand=('wait',),mana=1);self.play(g,'wait');self.check(g);self.choose(g)
        self.assertIsNone(g.state.pending_choice);self.assertFalse(self.hand(g));self.check(g)
    def test_current_class_query_keeps_captured_class_after_selection_reaction(self):
        self.watch(lambda c:[ReplaceHero(1,'HERO_08')],'choice_selected')
        self.script('current',lambda c:[self.offer(c,groups=(PoolOfferGroup('test',PoolQuery(class_mode='current')),))])
        g=self.game(hand=('current',),board=('watch',));self.play(g,'current');self.choose(g)
        self.assertEqual(g.state.players[1].hero_class,CardClass.MAGE)
        self.assertIn(CardClass.PRIEST,self.r.card(self.hand(g)[0].card_id).metadata.classes);self.check(g)
    def test_generated_quote_rejects_mismatched_cost_and_nonphysical_definition(self):
        g=self.game();before=g.snapshot()
        with self.assertRaises(ValueError):quote_generated_cost(g.state,self.r,1,'cm',cost=CostSpec(card_ids=('cs',)))
        with self.assertRaises(ValueError):quote_generated_cost(g.state,self.r,1,'EDR_449p')
        self.assertEqual(g.snapshot(),before)
    def test_temporary_cost_expiration_does_not_expire_card_early(self):
        self.script('two',lambda c:[CreateTemporaryCard(1,'cm',3,cost=CostSpec(delta=-1),cost_expires_turn=1)])
        g=self.game(hand=('two',));self.play(g,'two');card=self.hand(g)[0];g.apply(EndTurn(1))
        self.assertIn(card.id,g.state.players[1].hand);self.assertEqual(g.state.entities[card.id].cost,2)
        self.assertEqual(g.state.entities[card.id].hand_lifetime.expires_turn,3);self.check(g)
    def test_unsupported_kind_is_rejected_before_affordability_filter(self):
        self.pool('hero',('HERO_09',));self.script('hero',lambda c:[self.offer(c,groups=(PoolOfferGroup('hero'),))])
        g=self.game(hand=('hero',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'hero')
        self.assertEqual(g.snapshot(),before)
    def test_temporary_quote_floor_filters_unaffordable_free_card(self):
        self.script('floor',lambda c:[self.offer(c,minimum_cost=1)])
        g=self.game(hand=('floor',),mana=0);rng=g._rng.getstate();self.play(g,'floor')
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g._rng.getstate(),rng);self.check(g)


class PriestOfferTests(OfferFixtures,unittest.TestCase):
    def test_manual_power_pays_before_affordability_and_offers_two_kinds(self):
        g=self.game(hand=(),mana=2);self.use(g)
        self.assertEqual(g.state.players[1].mana,0)
        self.assertEqual([self.r.card(o.card_id).kind for o in g.state.pending_choice.options],[CardType.MINION,CardType.SPELL])
        self.assertTrue(all(o.preview.cost==0 for o in g.state.pending_choice.options));self.check(g)
    def test_imbue_installs_moon_and_growth_discounts_choices(self):
        self.script('grow',lambda c:[Imbue(1,c.source_id,3)])
        g=self.game(hand=('grow',),power=None);self.play(g,'grow');self.use(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,'EDR_449p')
        for o in g.state.pending_choice.options:self.assertEqual(o.preview.cost,max(0,self.r.card(o.card_id).cost-3))
        self.choose(g);self.check(g)
    def test_choice_growth_does_not_change_captured_discount(self):
        self.watch(lambda c:[Imbue(1,c.source_id,4)],'choice_selected')
        g=self.game(hand=(),board=('watch',));self.use(g);cid=self.choose(g)
        self.assertEqual(self.hand(g)[0].cost,max(0,self.r.card(cid).cost-1));self.check(g)
    def test_power_replacement_does_not_cancel_pending_delivery(self):
        self.watch(lambda c:[ReplaceHeroPower(1,'HERO_08bp')],'choice_selected')
        g=self.game(hand=(),board=('watch',));source=g.state.players[1].hero_power_id;self.use(g);self.choose(g)
        self.assertEqual(self.hand(g)[0].origin_entity_id,source)
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,'HERO_08bp');self.check(g)
    def test_moon_pool_stays_priest_after_hero_class_change(self):
        self.script('mage',lambda c:[ReplaceHero(1,'HERO_08'),ReplaceHeroPower(1,'EDR_449p')])
        g=self.game(hand=('mage',));self.play(g,'mage');self.use(g)
        self.assertEqual(g.state.players[1].hero_class,CardClass.MAGE)
        self.assertTrue(all(CardClass.PRIEST in self.r.card(o.card_id).metadata.classes for o in g.state.pending_choice.options));self.check(g)
    def test_wisprider_automatic_choice_creates_one_temporary_card(self):
        g=self.game(hand=('EDR_519',),power=None);self.play(g,'EDR_519')
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(self.hand(g)),1)
        self.assertIsNotNone(self.hand(g)[0].hand_lifetime);self.assertEqual(g.state.hero_power_history[0].origin,'effect')
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn,0);self.check(g)
    def test_indirect_player_choice_can_be_owned_by_other_seat(self):
        from hs_sim.engine import TriggerHeroPower
        self.script('other',lambda c:[ReplaceHeroPower(2,'EDR_449p'),TriggerHeroPower(2,c.source_id,choices='player')])
        g=self.game(hand=('other',));self.play(g,'other');self.assertEqual(g.state.pending_choice.player_id,2)
        self.choose(g);self.assertEqual(len(self.hand(g,2)),1);self.check(g)
    def test_rewind_power_restores_payment_and_reoffers_without_duplicate_hand(self):
        self.r.register_card(CardDefinition('retry','retry',CardType.HERO_POWER,cost=2,on_use='m5.blessing_moon',
            keywords=(Keyword.REWIND,),rewind=RewindSpec()))
        g=self.game(hand=(),power='retry');self.use(g);self.choose(g);self.check(g)
        c=g.state.pending_choice;g.apply(SelectChoice(1,c.id,('retry',)))
        self.assertFalse(self.hand(g));self.assertEqual(g.state.players[1].mana,8);self.choose(g)
        self.assertEqual(len(self.hand(g)),1);self.assertEqual(len(g.state.hero_power_history),1);self.check(g)
    def test_all_eight_class_adapters_exist_without_claiming_complete_family(self):
        self.assertEqual(len(IMBUE_CLASS_POWERS),8)
        self.assertTrue(all(cid in self.r.cards for cid in IMBUE_CLASS_POWERS.values()))
        self.assertFalse(self.r.pool(MOON_POOL_ID,CTX).complete)
    def test_priest_default_heal_still_explicitly_missing(self):
        from hs_sim.engine import DeckPolicy,DeckSpec,validate_deck
        self.assertIsNone(self.r.card('HERO_09').initial_hero_power)
        report=validate_deck(DeckSpec('HERO_09','EDR_449p',CardClass.PRIEST,('BRM_004',)),self.r,
            DeckPolicy('test','test','experimental',('BRM_004',),deck_size=1))
        self.assertIn('hero_power',[i.code for i in report.issues])
    def test_paladin_existing_reinforce_is_now_bound_to_initial_hero(self):
        from hs_sim.engine import DeckPolicy,DeckSpec,validate_deck
        report=validate_deck(DeckSpec('HERO_04','HERO_04bp',CardClass.PALADIN,('CS2_182',)),self.r,
            DeckPolicy('test','test','experimental',('CS2_182',),deck_size=1))
        self.assertTrue(report.valid)
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_04',hero_power_card_id=self.r.card('HERO_04').initial_hero_power,
            mana=2,max_mana=2),PlayerSetup('HERO_08'))),self.r)
        self.use(g);self.assertEqual(g.state.entities[g.state.players[1].board[0]].card_id,'CS2_101t');self.check(g)
    def test_skill_cost_modifier_changes_remaining_affordability_budget(self):
        self.script('powercost',lambda c:[AddCostModifier(1,CostSpec(set_to=0,card_types=(CardType.HERO_POWER,)))])
        g=self.game(hand=('powercost',),mana=2);self.play(g,'powercost');self.use(g)
        self.assertEqual(g.state.players[1].mana,2)
        self.assertTrue(all(o.preview.cost<=2 for o in g.state.pending_choice.options));self.choose(g);self.check(g)
    def test_real_player_port_example(self):
        from examples.imbue_moon import run
        g,s=run();self.assertEqual(s['schema_version'],265);self.assertEqual(len(g.state.hero_power_history),2)


if __name__=='__main__':unittest.main()
