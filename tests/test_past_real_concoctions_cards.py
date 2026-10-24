"""Real five/15 Concoction family through physical hand entries and paid CASTs."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards.past_real_concoctions_cards import (ROOT, SINGLES, MIXTURE_VERSION, load_batch,
    register_past_real_concoctions_cards)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game, PlayerSetup,
    Rarity, Registry, Scenario, SnapshotError, TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Draw, InvokeBehavior, RequestChoice, ReturnToHand)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_combinations import HandCombinationProfile
from hs_sim.engine.model import CostSpec
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from tools import card_batch as batch

P = 'k498.'
HERO, POWER, A, F, E, WATCH, BONUS = (P+x for x in ('hero', 'power', 'plain', 'foreign', 'enemy', 'watch', 'bonus'))
META = CardMetadata(False, (CardClass.MAGE,), Rarity.NONE, tribes=(), factions=(), subtypes=())
NEUTRAL = replace(META, collectible=True, classes=(CardClass.NEUTRAL,), rarity=Rarity.COMMON)
FOREIGN = replace(NEUTRAL, classes=(CardClass.WARLOCK,))


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = Registry(P+mode); register_past_real_concoctions_cards(r)
    r.register_behavior(P+'empty', lambda c: ())
    r.register_card(CardDefinition(HERO, 'Hero', CardType.HERO, health=50, metadata=META))
    r.register_card(CardDefinition(POWER, 'Delivery probe', CardType.HERO_POWER, on_use=P+'give3', metadata=META))
    for card in (CardDefinition(A, 'Three-cost body', CardType.MINION, cost=3, attack=1, health=9, metadata=NEUTRAL),
                 CardDefinition(F, 'Foreign five-cost spell', CardType.SPELL, cost=5, on_play=P+'empty', metadata=FOREIGN)):
        r.register_card(card); r.register_pool_card(PoolCard.from_definition(card))
    r.register_behavior(P+'death', lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial(A),), SummonCause.capture(c)),))
    r.register_card(CardDefinition(E, 'Replenishing enemy', CardType.MINION, attack=1, health=9,
        deathrattle=P+'death' if mode == 'death_spawn' else None, metadata=META))
    r.register_card(CardDefinition(BONUS, 'Spell damage', CardType.MINION, health=8, spell_damage=1, metadata=META))
    for i, cid in enumerate(SINGLES, 1):
        body=P+'give'+str(i)
        r.register_behavior(body, lambda c, cid=cid: (AddToHand(c.player_id, cid, c.source_id),))
        r.register_card(CardDefinition(body, body, CardType.SPELL, on_play=body, metadata=META))
    r.register_behavior(P+'discounted4', lambda c: (AddToHand(c.player_id, SINGLES[3], c.source_id, cost=CostSpec(delta=-2)),))
    r.register_card(CardDefinition(P+'discounted4', 'Discounted input', CardType.SPELL, on_play=P+'discounted4', metadata=META))
    r.register_behavior(P+'draw', lambda c: (Draw(c.player_id, source_id=c.source_id),))
    r.register_card(CardDefinition(P+'draw', 'Draw', CardType.SPELL, on_play=P+'draw', metadata=META))
    def explode(c): raise ResolutionError('k498 deliberate transactional failure')
    r.register_behavior(P+'explode', explode)
    def observe(c):
        event=c.event; options=[ChoiceOption('continue','Continue',())]
        if event.kind == 'cards_recombined':
            relevant=mode in ('merge_wait','merge_fail')
        elif event.kind == 'random_choice':
            selected=dict(event.data).get('selected')
            relevant=mode=='random_wait' and selected is not None
            if relevant: options.append(ChoiceOption('return','Return selected',(ReturnToHand(selected[0]),)))
        elif event.kind == 'damage_dealt':
            target=c.state.entities.get(event.target_id)
            source=c.state.entities.get(event.source_id)
            relevant=(mode=='hit_wait' and source is not None and source.card_id=='RLK_570t3t' and
                target is not None and target.health==6)
            if relevant: options.append(ChoiceOption('return','Return original',(ReturnToHand(target.id),)))
        else:
            relevant=mode=='summon_wait' and c.state.entities.get(event.target_id) is not None and c.state.entities[event.target_id].card_id==A
        if not relevant:return ()
        if mode=='merge_fail':return (InvokeBehavior(P+'explode',c.source_id,c.player_id),)
        options.append(ChoiceOption('bad','Fail',(InvokeBehavior(P+'explode',c.source_id,c.player_id),)))
        return (RequestChoice(c.player_id,tuple(options),source_id=c.source_id),)
    r.register_behavior(P+'observe',observe)
    r.register_card(CardDefinition(WATCH,'Observer',CardType.MINION,health=8,metadata=META,triggers=tuple(
        TriggerSpec(event,P+'observe') for event in ('cards_recombined','random_choice','damage_dealt','minion_summoned'))))
    members=[PoolMember(F)]
    if mode=='missing_pool':
        missing=CardDefinition(P+'missing','Unimplemented eligible foreign spell',CardType.SPELL,cost=5,on_play=P+'empty',metadata=FOREIGN)
        r.register_pool_card(PoolCard.from_definition(missing));members.append(PoolMember(missing.id))
    r.register_pool(PoolDefinition('constructed.cards','fixture-v1','k498','experimental',tuple(members),complete=True))
    r.register_pool(PoolDefinition('constructed.minions','fixture-v1','k498','experimental',(PoolMember(A),),complete=True))
    r.validate();return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version','events','events_hash','state_hash')})
    return saved


class RealConcoctionTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(fixture)

    def game(self,hand=(),*,board=(),enemy=(),deck=(A,)*8,mode='normal',power=False,seed=498):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=tuple(hand),board=tuple(board),deck=tuple(deck),
            mana=10,max_mana=10,hero_power_card_id=POWER if power else None),
            PlayerSetup(HERO,board=tuple(enemy),deck=(A,)*8,mana=10,max_mana=10)),seed=seed,
            generation_context=GenerationContext('k498','experimental')),fixture(mode))

    def cards(self,g,cid,zone='hand',player=1):
        return [g.state.entities[i] for i in getattr(g.state.players[player],zone) if g.state.entities[i].card_id==cid]

    def mixture(self,g):
        return next(g.state.entities[i] for i in g.state.players[1].hand if
            g.state.entities[i].card_id.startswith('RLK_570') and g.state.entities[i].card_id not in SINGLES)

    def test_all_complete_rows_and_42_original_primary_responses(self):
        d=load_batch();self.assertEqual(len(d['dependencies']),21);self.assertEqual(len(d['official_observations']),42)
        rows={x['record']['id']:x['record'] for x in d['dependencies']}
        for o in d['official_observations']:
            self.assertEqual(batch.sha(o['response_file']),o['response_sha256'])
            batch.check_face(rows[o['card_id']],o['face'],o['locale'])
        self.assertEqual(sum(fixture().card(i).requires_target or fixture().card(i).targeting is not None for i in rows),6)

    def test_actual_constructed_boundary_adds_all_twenty_one_full_definitions(self):
        from hs_sim.cards import build_registry
        r=batch.registration_prefix(build_registry,'hs_sim.cards.past_real_concoctions_cards.register_past_real_concoctions_cards',
            register_past_real_concoctions_cards,after=True)
        self.assertEqual(len(r.cards),2721)
        for row in load_batch()['dependencies']:
            cid=row['record']['id'];self.assertEqual(r.card(cid),fixture().card(cid))

    def test_paid_concoctor_only_generates_one_of_five_real_singles(self):
        for seed in (0,1,2,7,11):
            g=self.game((ROOT,),seed=seed);source=self.play(g,ROOT)
            self.assertEqual(len(g.state.players[1].hand),1);self.assertIn(g.state.entities[g.state.players[1].hand[0]].card_id,SINGLES)
            self.assertEqual(g.state.players[1].mana,9);self.assertFalse(g.state.cast_history)
            self.assertEqual(g.state.play_history[-1].source_id,source)

    def test_one_single_never_pairs_with_itself(self):
        g=self.game((SINGLES[0],));self.assertEqual(len(g.state.players[1].hand),1)
        self.assertEqual(self.cards(g,SINGLES[0])[0].card_id,SINGLES[0]);self.assertFalse(g.state.death_history)

    def test_all_fifteen_actual_recipes_settle_initial_physical_pairs(self):
        profiles=[p for p in fixture().hand_combinations.values() if p.version==MIXTURE_VERSION]
        self.assertEqual(len(profiles),15)
        for profile in profiles:
            with self.subTest(result=profile.result_card_id):
                g=self.game((profile.right_card_id,profile.left_card_id))
                self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[profile.result_card_id])
                self.assertEqual(len(g.state.players[1].graveyard),2);self.assertFalse(g.state.death_history)

    def test_actual_acquisition_of_identical_singles_uses_two_distinct_entities(self):
        g=self.game((SINGLES[2],P+'give3'));original=self.cards(g,SINGLES[2])[0].id
        self.play(g,P+'give3');combined=self.mixture(g)
        self.assertEqual(combined.card_id,'RLK_570t3t');self.assertNotEqual(combined.id,original)
        self.assertEqual(len([e for e in g.state.entities.values() if e.card_id==SINGLES[2]]),2);self.portable(g)

    def test_random_acquisition_combines_with_original_held_single(self):
        g=self.game((SINGLES[0],ROOT));self.play(g,ROOT);self.mixture(g)
        self.assertEqual(len(g.state.players[1].hand),1);self.assertFalse(g.state.cast_history)

    def test_mixed_and_single_cards_do_not_form_recursive_mixtures(self):
        g=self.game(('RLK_570t1t1',SINGLES[0]));self.assertEqual(len(g.state.players[1].hand),2)

    def test_source_material_is_oldest_held_not_canonical_ingredient_name(self):
        g=self.game((P+'discounted4',P+'give1'));self.play(g,P+'discounted4');original=self.cards(g,SINGLES[3])[0].id
        self.play(g,P+'give1');mixed=self.mixture(g)
        self.assertEqual(mixed.card_id,'RLK_570t1t1');self.assertEqual(mixed.origin_entity_id,original)
        from hs_sim.engine.costs import quote_unselected_cost
        self.assertEqual(quote_unselected_cost(g.state,g.registry,mixed).amount,1)

    def test_full_hand_burns_before_it_can_merge_with_an_older_single(self):
        g=self.game((SINGLES[2],)+(A,)*9,power=True);old=self.cards(g,SINGLES[2])[0].id
        power=next(e.id for e in g.state.entities.values() if e.card_id==POWER and e.controller==1 and e.zone==Zone.HERO_POWER)
        g.apply(UseHeroPower(1,power));self.assertEqual(len(g.state.players[1].hand),10)
        self.assertEqual(self.cards(g,SINGLES[2])[0].id,old)
        self.assertFalse(any(g.state.entities[i].card_id=='RLK_570t3t' for i in g.state.players[1].hand))

    def test_ninth_card_admission_can_merge_without_extra_capacity(self):
        g=self.game((SINGLES[2],)+(A,)*8,power=True)
        power=next(e.id for e in g.state.entities.values() if e.card_id==POWER and e.controller==1 and e.zone==Zone.HERO_POWER)
        g.apply(UseHeroPower(1,power));self.assertEqual(len(g.state.players[1].hand),9)
        self.assertEqual(self.mixture(g).card_id,'RLK_570t3t')

    def test_all_twenty_real_spells_have_their_paid_effect_counts(self):
        # Independent card-text expectations: damage packets / draws / summons / foreign cards / destroys.
        cases={
            'RLK_570t1':(0,0,1,0,0),'RLK_570t2':(0,0,0,0,1),'RLK_570t3':(1,0,0,0,0),
            'RLK_570t4':(0,0,0,1,0),'RLK_570t5':(0,2,0,0,0),
            'RLK_570t1t1':(0,0,1,1,0),'RLK_570t1t2':(0,0,1,0,1),'RLK_570t1t3':(1,0,1,0,0),
            'RLK_570t1t4':(0,0,2,0,0),'RLK_570t2t1':(1,0,0,0,1),'RLK_570t2t2':(0,0,0,0,2),
            'RLK_570t3t':(2,0,0,0,0),'RLK_570t4t1':(0,0,0,1,1),'RLK_570t4t2':(1,0,0,1,0),
            'RLK_570t4t3':(0,0,0,2,0),'RLK_570tt1':(0,2,1,0,0),'RLK_570tt2':(1,2,0,0,0),
            'RLK_570tt3':(0,2,0,1,0),'RLK_570tt4':(0,2,0,0,1),'RLK_570tt5':(0,4,0,0,0)}
        for cid,(damage,draws,summons,foreign,destroys) in cases.items():
            with self.subTest(card=cid):
                g=self.game((cid,),enemy=(E,)*3);target=g.state.players[2].hero_id if damage else None
                self.play(g,cid,target)
                self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,50-3*damage)
                self.assertEqual(len(self.cards(g,A)),draws);self.assertEqual(len(self.cards(g,A,'board')),summons)
                self.assertEqual(len(self.cards(g,F)),foreign);self.assertEqual(len(g.state.players[2].board),3-destroys)
                self.assertEqual((len(g.state.cast_history),len(g.state.play_history),g.state.players[1].mana),(1,1,7))

    def test_damage_twice_scales_two_packets_with_ordinary_spell_damage(self):
        g=self.game(('RLK_570t3t',),board=(BONUS,));target=g.state.players[2].hero_id
        self.play(g,'RLK_570t3t',target);self.assertEqual(g.state.entities[target].health,42)

    def test_foreign_card_keeps_true_other_class_and_three_cost_reduction(self):
        g=self.game(('RLK_570t4',));self.play(g,'RLK_570t4');card,=self.cards(g,F)
        from hs_sim.engine.costs import quote_unselected_cost
        self.assertEqual(quote_unselected_cost(g.state,g.registry,card).amount,2)
        self.assertEqual(g.registry.card(card.card_id).metadata.classes,(CardClass.WARLOCK,))

    def test_unknown_eligible_foreign_card_is_not_removed_from_generation(self):
        g=self.game(('RLK_570t4',),mode='missing_pool');before=g.snapshot()
        with self.assertRaises((ResolutionError,UnsupportedDefinitionError)):self.play(g,'RLK_570t4')
        self.assertEqual(g.snapshot(),before)

    def test_printed_draw_before_summon_sequence_is_retained(self):
        g=self.game(('RLK_570tt1',));self.play(g,'RLK_570tt1')
        draws=[e.sequence for e in g.events if e.kind=='card_drawn']
        summoned=[e.sequence for e in g.events if e.kind=='minion_summoned']
        self.assertLess(max(draws),min(summoned))

    def test_full_board_keeps_other_printed_effect_of_summon_mixture(self):
        g=self.game(('RLK_570tt1',),board=(A,)*7);self.play(g,'RLK_570tt1')
        self.assertEqual(len(self.cards(g,A)),2);self.assertEqual(len(g.state.players[1].board),7)

    def test_two_destroys_accept_original_group_before_death_summons(self):
        g=self.game(('RLK_570t2t2',),enemy=(E,)*3,mode='death_spawn');self.play(g,'RLK_570t2t2')
        self.assertEqual(len(self.cards(g,E,'board',2)),1);self.assertEqual(len(self.cards(g,A,'board',2)),2)

    def test_empty_double_destroy_has_no_random_consumption(self):
        g=self.game(('RLK_570t2t2',));before=g.snapshot()['rng_state'];self.play(g,'RLK_570t2t2')
        self.assertEqual(g.snapshot()['rng_state'],before)

    def test_one_enemy_double_destroy_does_not_invent_a_second_target(self):
        g=self.game(('RLK_570t2t2',),enemy=(E,));self.play(g,'RLK_570t2t2')
        self.assertFalse(g.state.players[2].board);self.assertEqual(len(g.state.death_history),1)

    def test_merge_wait_restores_clone_replay_and_failed_choice(self):
        g=self.game((SINGLES[2],P+'give3'),board=(WATCH,),mode='merge_wait');self.play(g,P+'give3')
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.mixture(g).card_id,'RLK_570t3t')
        self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.portable(g)

    def test_failed_merge_reaction_restores_both_physical_hand_sources(self):
        g=self.game((SINGLES[2],P+'give3'),board=(WATCH,),mode='merge_fail');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,P+'give3')
        self.assertEqual(g.snapshot(),before)

    def test_selected_destroy_group_waits_restores_and_skips_a_returned_target(self):
        g=self.game(('RLK_570t2t2',),board=(WATCH,),enemy=(E,)*3,mode='random_wait')
        self.play(g,'RLK_570t2t2');self.assertIsNotNone(g.state.pending_choice);self.portable(g)
        self.choose(g,'return');self.assertEqual(len(self.cards(g,E,'hand',2)),1)
        self.assertEqual(len(g.state.death_history),1);self.assertEqual(len(g.state.players[2].board),1);self.portable(g)

    def test_second_damage_preserves_original_minion_residence_across_a_wait(self):
        g=self.game(('RLK_570t3t',),board=(WATCH,),enemy=(E,),mode='hit_wait');target=self.cards(g,E,'board',2)[0].id
        source=self.play(g,'RLK_570t3t',target);self.assertIsNotNone(g.state.pending_choice);self.portable(g)
        self.choose(g,'return');hits=[e for e in g.events if e.kind=='damage_dealt' and e.source_id==source]
        self.assertEqual(len(hits),1);self.assertIn(target,g.state.players[2].hand)

    def test_summon_component_pause_keeps_remaining_foreign_generation(self):
        g=self.game(('RLK_570t1t1',),board=(WATCH,),mode='summon_wait');self.play(g,'RLK_570t1t1')
        self.assertIsNotNone(g.state.pending_choice);self.assertFalse(self.cards(g,F));self.portable(g)
        self.choose(g);self.assertEqual(len(self.cards(g,F)),1);self.portable(g)

    def test_rehashed_group_cannot_borrow_a_future_cast(self):
        g=self.game(('RLK_570t2t2',),board=(WATCH,),enemy=(E,)*3,mode='random_wait');self.play(g,'RLK_570t2t2')
        saved=deepcopy(g.snapshot())
        def find(v):
            if isinstance(v,dict):
                if str(v.get('type','')).endswith('.DestroySelectedSpellGroup'):return v
                for value in v.values():
                    found=find(value)
                    if found is not None:return found
            elif isinstance(v,list):
                for value in v:
                    found=find(value)
                    if found is not None:return found
        value=find(saved['resolution_frame']);self.assertIsNotNone(value);value['fields']['cast_id']=999
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(saved),fixture('random_wait'))

    def test_player_views_exclude_private_recipe_and_hand_source_material(self):
        g=self.game((SINGLES[2],P+'give3'));self.play(g,P+'give3')
        for player in (1,2):
            view=json.dumps(g.for_player(player).observe())
            for key in ('fragment_ids','next_attachment_id','rng_state','resolution_frame'):
                self.assertNotIn('"'+key+'"',view)


if __name__=='__main__':unittest.main()
