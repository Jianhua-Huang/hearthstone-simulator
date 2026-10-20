"""Real hand arrows keep the user's choice and execute the native target."""
from functools import lru_cache
import json
import unittest

from hs_sim.engine import (CardDefinition,CardType,Game,PlayCard,PlayerSetup,Scenario,
    ResolutionError,SelectChoice,SnapshotError,TriggerSpec,UseInteractable,Zone)
from hs_sim.engine.effects import ChoiceOption,Destroy,InvokeBehavior,RequestChoice
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.native_hand_targets import OFFERED,ACCEPTED,FINISHED
from hs_sim.engine.native_active_targets import ACCEPTED as ACTIVE_ACCEPTED
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.zones import CardReference,DestroyStoredCard,MoveCard
from test_native_random_target_domains import fixture as domain_fixture,CARD,UNIT

P='fixture.native.hand.';WATCH=P+'watch';MOTHER='BE_036';SPLIT='CATA_979';PHOENIX='CATA_EVENT_001';ALCHEMIST='JAIL_313'
SUN='WW_434';COIN='GAME_005';RIFT='TLC_446t1'
CONTEXT=GenerationContext('native-hand-arrows-explicit-fixture-v1','experimental')
POOL_MEMBERS=('JAM_017','CORE_BT_235')


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    r=domain_fixture.__wrapped__()
    # This complete two-member host is an explicit experimental pool, not a
    # filtered or certified Standard generation pool. Its full members survive.
    for cid in POOL_MEMBERS:
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition('constructed.cards','native-hand-arrows-v1',CONTEXT.target_id,
        CONTEXT.mode,tuple(PoolMember(cid)for cid in POOL_MEMBERS),complete=True))
    def watch(c):
        if mode=='fail':raise ResolutionError('Hand target callback observer failure')
        if mode=='wait':return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),c.source_id),)
        if c.state.entities[c.event.source_id].card_id!=MOTHER:return ()
        if mode=='clear':return tuple(DestroyStoredCard(CardReference.capture(c.state.entities[i]),c.source_id)for i in c.state.players[1].hand)
        if mode=='kill':
            source=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==CARD)
            return(Destroy(source),)
        if mode=='bounce':
            target=c.state.players[1].hand[0]
            return(MoveCard(CardReference.capture(c.state.entities[target]),1,Zone.DECK,position='top'),
                InvokeBehavior(P+'back',source_id=c.source_id,player_id=1,target_id=target))
        return ()
    r.register_behavior(P+'watch',watch)
    r.register_behavior(P+'back',lambda c:(MoveCard(CardReference.capture(c.state.entities[c.target_id]),1,Zone.HAND),))
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,
        triggers=(TriggerSpec('card_destroyed_in_hand'if mode in('wait','fail')else'choice_requested',P+'watch'),)))
    r.validate();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events'])
    s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('events','events_hash','state_hash')})
    return s


class NativeHandTargetTests(unittest.TestCase):
    def game(self,*,hand=(MOTHER,SUN,SUN),board=(CARD,),enemy=(UNIT,),mode='normal',seed=0):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_03',hand=hand,board=board,deck=(UNIT,)*16,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_03',board=enemy,deck=(UNIT,)*16,mana=40,max_mana=40,mana_cap=40)),seed=seed,
            generation_context=CONTEXT),fixture(mode))
    def entity(self,g,cid,zone='hand',player=1):
        return next(i for i in getattr(g.state.players[player],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid):g.apply(PlayCard(1,self.entity(g,cid)))
    def select(self,g,entity=None):
        q=g.state.pending_choice;item=q.options[0]if entity is None else next(o for o in q.options if o.entity_id==entity)
        g.apply(SelectChoice(q.player_id,q.id,(item.id,)))
    def selection(self,g,kind=ACCEPTED):
        e=next(e for e in reversed(g.events)if e.kind==kind)
        return FrameCodec(g.mechanics,g.registry).decode(json.loads(dict(e.data)['selection']))
    def portable(self,g,mode='normal'):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,fixture.__wrapped__(mode))
        self.assertEqual(s,other.snapshot());self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),fixture.__wrapped__(mode)).snapshot(),s)
        return other
    def costs(self,g,ids):return[quote_unselected_cost(g.state,g.registry,g.state.entities[i]).amount for i in ids]
    def test_real_mother_changes_selected_anchor_and_effect_bundle_without_rewriting_user_choice(self):
        g=self.game();self.play(g,MOTHER);ids=list(g.state.players[1].hand);q=g.state.pending_choice
        original=next(o.id for o in q.options if o.entity_id==ids[0]);self.select(g,ids[0]);s=self.selection(g)
        self.assertEqual(s.target_id,ids[1]);self.assertEqual(s.partition.submitted_target_id,ids[0])
        self.assertEqual(self.costs(g,ids),[2,1])
        chosen=next(e for e in g.events if e.kind=='choice_selected'and dict(e.data)['choice_id']==q.id)
        self.assertEqual(dict(chosen.data)['option_ids'],(original,));self.assertEqual(sum(e.kind==FINISHED for e in g.events),1)
        self.portable(g)
    def test_real_specialist_selects_only_original_spells_and_uses_their_original_callback(self):
        g=self.game(hand=(SPLIT,COIN,COIN,UNIT));self.play(g,SPLIT)
        options=g.state.pending_choice.options;ids=[o.entity_id for o in options]
        self.assertEqual(len(ids),2);self.select(g,ids[0]);s=self.selection(g)
        self.assertEqual(s.target_id,ids[1]);self.assertEqual(set(s.partition.target_ids),set(ids))
        self.assertNotIn(s.target_id,g.state.players[1].hand);self.assertIn(ids[0],g.state.players[1].hand)
        self.assertEqual(len(g.state.players[1].hand),4);self.portable(g)
    def test_real_phoenix_marks_selected_card_using_original_option_effect(self):
        g=self.game(hand=(PHOENIX,SUN,SUN));self.play(g,PHOENIX);ids=list(g.state.players[1].hand)
        self.select(g,ids[0]);s=self.selection(g)
        self.assertEqual(s.target_id,ids[1]);self.assertEqual(g.state.hand_deadlines[-1].targets[0].entity_id,s.target_id)
        self.portable(g)
    def test_real_alchemist_transforms_selected_card_and_retains_original_cost(self):
        g=self.game(hand=(ALCHEMIST,COIN,COIN));self.play(g,ALCHEMIST);ids=list(g.state.players[1].hand)
        self.select(g,ids[0]);s=self.selection(g)
        self.assertEqual(s.target_id,ids[1]);self.assertEqual(g.state.entities[ids[0]].card_id,COIN)
        self.assertNotEqual(g.state.entities[ids[1]].card_id,COIN)
        self.assertEqual(g.registry.card(g.state.entities[ids[1]].card_id).cost,5)
        self.assertEqual(quote_unselected_cost(g.state,g.registry,g.state.entities[ids[1]]).amount,0);self.portable(g)
    def test_real_rift_invests_native_selected_card_and_consumes_one_owner_use(self):
        g=self.game(hand=('TLC_446t',SUN,SUN));self.play(g,'TLC_446t');source=self.entity(g,RIFT,'board')
        ids=list(g.state.players[1].hand);g.apply(UseInteractable(1,source,ids[0]));s=self.selection(g,ACTIVE_ACCEPTED)
        self.assertEqual(s.target_id,ids[1]);self.assertEqual(s.partition.submitted_target_id,ids[0])
        self.assertEqual(g.state.interactable_history[-1].invested.entity_id,ids[1])
        self.assertNotIn(ids[1],g.state.players[1].hand);self.assertIn(ids[0],g.state.players[1].hand)
        self.assertEqual(len(g.state.interactable_history),1);self.portable(g)
    def test_no_native_source_keeps_original_hand_anchor_without_extra_rng(self):
        g=self.game(board=());self.play(g,MOTHER);ids=list(g.state.players[1].hand);rng=g.snapshot()['rng_state'];self.select(g,ids[0])
        self.assertEqual(self.costs(g,ids),[1,2]);self.assertEqual(g.snapshot()['rng_state'],rng)
        self.assertFalse(any(e.kind==ACCEPTED for e in g.events));self.portable(g)
    def test_enemy_native_source_changes_own_hand_choice_without_borrowing_enemy_hand(self):
        g=self.game(board=(),enemy=(CARD,UNIT));self.play(g,MOTHER);ids=list(g.state.players[1].hand);self.select(g,ids[0]);s=self.selection(g)
        self.assertEqual({x.source.controller for x in s.partition.carriers},{2})
        self.assertEqual({x.controller for x in s.partition.candidates},{1});self.assertEqual(self.costs(g,ids),[2,1]);self.portable(g)
    def test_single_original_candidate_consumes_native_draw_but_empty_hand_creates_no_choice(self):
        g=self.game(hand=(MOTHER,SUN));self.play(g,MOTHER);self.select(g);s=self.selection(g)
        self.assertNotEqual(s.rng_before,s.rng_after);self.assertEqual(len(s.partition.candidates),1);self.portable(g)
        g=self.game(hand=(MOTHER,));rng=g.snapshot()['rng_state'];self.play(g,MOTHER)
        self.assertIsNone(g.state.pending_choice);self.assertFalse(any(e.kind==OFFERED for e in g.events));self.assertEqual(g.snapshot()['rng_state'],rng)
    def test_pending_original_offer_restores_before_native_selection(self):
        g=self.game();self.play(g,MOTHER);other=self.portable(g)
        for current in(g,other):self.select(current)
        self.assertEqual(g.snapshot(),other.snapshot())
    def test_callback_wait_restores_full_hand_target_proof_and_remaining_generation(self):
        g=self.game(hand=(SPLIT,COIN,COIN),board=(CARD,WATCH),mode='wait');self.play(g,SPLIT);self.select(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.pending_choice.options[0].id,'ok')
        other=self.portable(g,'wait')
        for current in(g,other):self.select(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(sum(e.kind==ACCEPTED for e in g.events),1)
    def test_source_removed_by_original_choice_reactions_prevents_new_native_draw(self):
        g=self.game(board=(CARD,WATCH),mode='kill');self.play(g,MOTHER);ids=list(g.state.players[1].hand)
        rng=g.snapshot()['rng_state'];self.select(g,ids[0])
        self.assertEqual(self.costs(g,ids),[1,2]);self.assertEqual(g.snapshot()['rng_state'],rng)
        self.assertFalse(any(e.kind==ACCEPTED for e in g.events));self.portable(g,'kill')
    def test_failed_callback_rolls_back_to_original_pending_offer_and_rng(self):
        g=self.game(hand=(SPLIT,COIN,COIN),board=(CARD,WATCH),mode='fail');self.play(g,SPLIT);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.select(g)
        self.assertEqual(g.snapshot(),before);self.portable(g,'fail')
    def test_callback_wait_cannot_drop_the_unique_native_finish(self):
        g=self.game(hand=(SPLIT,COIN,COIN),board=(CARD,WATCH),mode='wait');self.play(g,SPLIT);self.select(g)
        s=json.loads(json.dumps(g.snapshot()))
        def prune(value):
            if isinstance(value,dict):
                for key,child in list(value.items()):
                    if isinstance(child,list):value[key]=[x for x in child if not(isinstance(x,dict)and str(x.get('type','')).endswith('.FinishNativeHandTarget'))]
                    prune(value[key])
            elif isinstance(value,list):
                for child in value:prune(child)
        prune(s['resolution_frame'])
        with self.assertRaises((SnapshotError,ValueError)):Game.from_snapshot(rehash(s),fixture.__wrapped__('wait'))
    def test_all_offered_cards_removed_before_target_phase_fizzles_without_rng(self):
        g=self.game(board=(CARD,WATCH),mode='clear');self.play(g,MOTHER);rng=g.snapshot()['rng_state'];self.select(g);s=self.selection(g)
        self.assertEqual(s.failure,'no_target');self.assertEqual(s.partition.candidates,());self.assertEqual(g.snapshot()['rng_state'],rng)
        self.assertTrue(g.state.battlecry_history[-1].completed);self.portable(g,'clear')
    def test_same_id_new_hand_residence_is_excluded_from_original_target_domain(self):
        g=self.game(board=(CARD,WATCH),mode='bounce');self.play(g,MOTHER);ids=list(g.state.players[1].hand)
        epoch=g.state.entities[ids[0]].zone_epoch;self.select(g,ids[0]);s=self.selection(g)
        self.assertGreater(g.state.entities[ids[0]].zone_epoch,epoch);self.assertEqual(s.partition.target_ids,(ids[1],))
        self.assertEqual(self.costs(g,ids),[6,1]);self.portable(g,'bounce')
    def test_real_tracking_discovery_is_not_randomized_as_a_hand_arrow(self):
        g=self.game(hand=('CORE_DS1_184',));self.play(g,'CORE_DS1_184')
        self.assertIsNotNone(g.state.pending_choice);self.select(g)
        self.assertFalse(any(e.kind in(OFFERED,ACCEPTED)for e in g.events));self.portable(g)
    def test_unused_hand_target_tag_does_not_randomize_explicit_hero_set_health(self):
        g=self.game(hand=('CATA_307',));rng=g.snapshot()['rng_state'];self.play(g,'CATA_307')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,15)
        self.assertFalse(any(e.kind in(OFFERED,ACCEPTED)for e in g.events));self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)
    def test_pending_offer_cannot_drop_its_hand_target_metadata(self):
        g=self.game();self.play(g,MOTHER);s=json.loads(json.dumps(g.snapshot()))
        def clear(value):
            if isinstance(value,dict):
                if 'native_target_request'in value:value['native_target_request']=None;return True
                return any(clear(x)for x in value.values())
            if isinstance(value,list):return any(clear(x)for x in value)
            return False
        self.assertTrue(clear(s['resolution_frame']))
        with self.assertRaises((SnapshotError,ValueError)):Game.from_snapshot(rehash(s),fixture.__wrapped__())
    def test_player_views_hide_offered_physical_facts_and_native_rng(self):
        g=self.game();self.play(g,MOTHER);self.select(g)
        for player in(1,2):
            public=json.dumps(g.observe(player))
            for hidden in(OFFERED,ACCEPTED,FINISHED,'target_facts','rng_before','native_target_request'):
                self.assertNotIn(hidden,public)


if __name__=='__main__':unittest.main()
