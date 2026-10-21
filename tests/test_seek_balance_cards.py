"""Two genuine child casts and original minion-half hand combination."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.seek_balance_cards import FULL, HOLY, LEFT, RIGHT, ROOT, SHADOW, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    DeckPolicy, DeckSpec, EndTurn, Game, IllegalAction, Keyword, MatchSetup,
    PlayCard, PlayerSetup, QuestSpec, QuestStageSpec, Rarity, RemoveQuest,
    Ruleset, Scenario, SelectChoice, SnapshotError, SpellSchool, TriggerSpec, Zone)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddToHand, ChoiceOption, CostSpec, Damage, Destroy,
    InvokeBehavior, ModifyCost, RandomDamage, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_combinations import HandCombinationProfile
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference, DiscardCard
from hs_sim.targets import canonical_digest

P='balance.test.'
H,S,N=(P+x for x in ('holy','shadow','none'))
WAIT_START,WAIT_REWARD,BAD=(P+x for x in ('wait_start','wait_reward','bad'))
END_AFTER_SHADOW=P+'end_after_shadow'
OTHER=P+'other_quest'
FILLERS=tuple(P+'filler.'+str(i) for i in range(30))


@lru_cache(maxsize=None)
def registry(role):
    assert role in ('writer','reader')
    r=build_registry();meta=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())
    r.register_behavior(P+'noop',lambda c: ())
    def fail(c):raise ResolutionError('Balance deliberate rollback')
    r.register_behavior(P+'fail',fail)
    for cid,school in ((H,SpellSchool.HOLY),(S,SpellSchool.SHADOW),(N,None)):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,spell_school=school,on_play=P+'noop',metadata=meta))
    for cid in FILLERS:
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=2,metadata=meta))
    r.register_card(CardDefinition(OTHER,OTHER,CardType.SPELL,cost=1,keywords=(Keyword.QUEST,),metadata=meta,
        quest=QuestSpec('quest',(QuestStageSpec(OTHER,1,('unused_test_event',),P+'noop',P+'noop'),))))
    def ref(c,cid):
        return next(c.state.entities[i] for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==cid)
    def remove(c):
        eid=next(i for i in c.state.players[c.player_id].quests if c.state.entities[i].card_id==HOLY)
        return (RemoveQuest(eid),)
    def destroy(c):
        eid=next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id in (RIGHT,FULL))
        return (Destroy(eid,c.source_id),)
    bodies={
        'auto_root':lambda c:(CastSpell(c.player_id,ROOT,c.source_id),),
        'auto_holy':lambda c:(CastSpell(c.player_id,H,c.source_id),),
        'auto_child':lambda c:(CastSpell(c.player_id,HOLY,c.source_id),),
        'remove_holy':remove,
        'left':lambda c:(AddToHand(c.player_id,LEFT,c.source_id),),
        'right':lambda c:(AddToHand(c.player_id,RIGHT,c.source_id),),
        'discard_left':lambda c:(DiscardCard(CardReference.capture(ref(c,LEFT)),c.source_id),),
        'discount_left':lambda c:(ModifyCost(ref(c,LEFT).id,CostSpec(delta=-2),c.source_id),),
        'destroy':destroy,
    }
    for suffix,body in bodies.items():
        cid=P+suffix;r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=meta))
    def wait(c):
        if c.event.player_id!=c.player_id:return ()
        if c.source.card_id==WAIT_START:
            if c.state.entities[c.event.source_id].card_id!=HOLY:return ()
        elif c.event.target_id is None or c.state.entities[c.event.target_id].card_id not in (LEFT,RIGHT):return ()
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',()),
            ChoiceOption('fail','Fail',(RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),
                InvokeBehavior(P+'fail',c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(P+'wait',wait)
    def bad(c):
        if c.event.player_id!=c.player_id or c.event.target_id is None or c.state.entities[c.event.target_id].card_id!=RIGHT:return ()
        return (RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),
            InvokeBehavior(P+'fail',c.source_id,c.player_id))
    r.register_behavior(P+'bad',bad)
    for cid,event,body in ((WAIT_START,'quest_started',P+'wait'),(WAIT_REWARD,'card_added_to_hand',P+'wait'),(BAD,'card_added_to_hand',P+'bad')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=9,metadata=meta,triggers=(TriggerSpec(event,body),)))
    def end_after_shadow(c):
        if c.event.player_id!=c.player_id or c.state.entities[c.event.source_id].card_id!=SHADOW:return ()
        return (Damage(c.state.players[3-c.player_id].hero_id,100,c.source_id),)
    r.register_behavior(P+'end_after_shadow',end_after_shadow)
    r.register_card(CardDefinition(END_AFTER_SHADOW,END_AFTER_SHADOW,CardType.MINION,health=9,metadata=meta,
        triggers=(TriggerSpec('quest_started',P+'end_after_shadow'),)))
    r.validate();r.freeze();return r


class SeekBalanceTests(unittest.TestCase):
    def game(self,hand=(ROOT,),*,enemy_hand=(),board=(),rules=None):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_09',hand=hand,board=board,mana=10,max_mana=10,deck=FILLERS),
            PlayerSetup('HERO_08',hand=enemy_hand,mana=10,max_mana=10,deck=FILLERS)),seed=247817),registry('writer'),ruleset=rules)
    def play(self,g,cid):
        pid=g.state.active_player;eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        return g.apply(PlayCard(pid,eid))
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;return g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def names(self,g,pid=1):return tuple(g.state.entities[i].card_id for i in g.state.players[pid].hand)
    def quests(self,g):return {g.state.entities[i].card_id:g.state.entities[i].quest_progress.value for i in g.state.players[1].quests}
    def portable(self,g):
        r=registry('reader' if g.registry is registry('writer') else 'writer')
        snapshot=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(snapshot,r)
        self.assertEqual(other.snapshot(),snapshot);self.assertEqual(g.clone().snapshot(),snapshot)
        self.assertEqual(replay(build_replay(g),r).snapshot(),snapshot)
        return other
    def complete(self,g,school):
        for _ in range(4):self.play(g,school)

    def test_a00_complete_six_raw_faces_twelve_primary_observations_and_old_full_reward_preserved(self):
        from tools.card_batch import check_face
        d=load_batch();rows={r['record']['id']:r for k in ('cards','dependencies','existing_dependencies')for r in d[k]}
        self.assertEqual(len(rows),6);self.assertEqual(len(d['official_observations']),12)
        for face in d['official_observations']:check_face(rows[face['card_id']]['record'],face['face'],face['locale'])
        self.assertEqual(canonical_digest(asdict(registry('writer').card(FULL))),rows[FULL]['definition_sha256'])

    def test_a01_pair_declarations_require_two_distinct_children_and_frozen_hand_profiles(self):
        root=registry('writer').card(ROOT)
        self.assertEqual(root.quest.kind,'paired_quest');self.assertTrue(root.quest.starts_in_hand)
        for stages in (root.quest.stages[:1],root.quest.stages*2,(root.quest.stages[0],)*2):
            with self.subTest(stages=len(stages)),self.assertRaises(ValueError):QuestSpec('paired_quest',stages)
        p=HandCombinationProfile(FULL,LEFT,RIGHT)
        with self.assertRaises(ValueError):replace(p,right_card_id=LEFT)
        with self.assertRaises(ValueError):replace(p,version='unknown')
        with self.assertRaises(TypeError):registry('writer').hand_combinations[FULL]=p

    def test_a02_real_thirty_card_opening_guarantees_the_original_root_and_restores_mulligan(self):
        r=registry('writer');decks=(DeckSpec('HERO_09','HERO_09bp',CardClass.PRIEST,(ROOT,*FILLERS[:29])),
            DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,FILLERS))
        policy=DeckPolicy(P+'policy','cn37-explicit-balance-fixture','experimental',tuple(r.cards))
        g=Game.from_decks(MatchSetup(decks,policy,'GAME_005',seed=247817,first_player=1),r)
        self.assertIn(ROOT,self.names(g));g=self.portable(g)
        while g.state.pending_choice is not None:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        self.play(g,ROOT);self.assertEqual(self.quests(g),{HOLY:0,SHADOW:0});self.portable(g)

    def test_a03_profile_registration_order_does_not_change_fingerprint_or_physical_settlement(self):
        # Independent generic contract fixture; these six faces are not real
        # card integrations or additions to the constructed candidate pool.
        from hs_sim.engine.representative import build_registry as defaults
        profiles=tuple(HandCombinationProfile(P+'order.'+group+'.full',P+'order.'+group+'.left',P+'order.'+group+'.right')for group in ('a','b'))
        registries=[]
        for reverse in (False,True):
            r=defaults()
            for profile in profiles:
                for cid in (profile.result_card_id,profile.left_card_id,profile.right_card_id):
                    r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=1))
            for profile in reversed(profiles) if reverse else profiles:r.register_hand_combination(profile)
            r.validate();r.freeze();registries.append(r)
        self.assertEqual(registries[0].fingerprint(),registries[1].fingerprint())
        setup=Scenario((PlayerSetup('HERO_01',hand=tuple(p.left_card_id for p in profiles)+tuple(p.right_card_id for p in profiles)),PlayerSetup('HERO_08')))
        first,second=(Game.from_scenario(setup,r)for r in registries)
        self.assertEqual(first.snapshot(),second.snapshot())
        self.assertEqual(Game.from_snapshot(first.snapshot(),registries[1]).snapshot(),first.snapshot())

    def test_b00_one_paid_root_casts_two_real_child_spells_without_extra_hand_plays(self):
        g=self.game();self.play(g,ROOT)
        self.assertEqual(g.state.players[1].mana,9);self.assertEqual(self.quests(g),{HOLY:0,SHADOW:0})
        self.assertEqual(tuple(c.card_id for c in g.state.cast_history),(ROOT,HOLY,SHADOW))
        self.assertEqual(tuple(c.origin for c in g.state.cast_history),('hand','effect','effect'))
        self.assertEqual(tuple(c.quest_parent_cast_id for c in g.state.cast_history),(None,1,1))
        self.assertTrue(all(c.completed for c in g.state.cast_history));self.assertEqual(len(g.state.play_history),1)
        self.assertFalse(any(g.state.entities[i].card_id==ROOT for i in g.state.players[1].quests));self.portable(g)

    def test_b01_holy_and_shadow_progress_independently_and_complete_in_either_order(self):
        for first,second,half,remaining in ((H,S,LEFT,SHADOW),(S,H,RIGHT,HOLY)):
            with self.subTest(first=first):
                g=self.game((ROOT,*(H,)*4,*(S,)*4));self.play(g,ROOT)
                for _ in range(3):self.play(g,first);self.play(g,second)
                self.assertEqual(self.quests(g),{HOLY:3,SHADOW:3});self.play(g,first)
                self.assertEqual(self.quests(g),{remaining:3});self.assertIn(half,self.names(g))
                self.play(g,second);self.assertFalse(self.quests(g));self.assertIn(FULL,self.names(g));self.portable(g)

    def test_b02_ordinary_main_quest_remains_blocked_until_both_children_finish(self):
        g=self.game((ROOT,OTHER,*(H,)*4,*(S,)*4));self.play(g,ROOT)
        for stage in (0,1):
            before=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,OTHER)
            self.assertEqual(g.snapshot(),before)
            self.complete(g,H if stage==0 else S)
        self.play(g,OTHER);self.assertEqual(self.quests(g),{OTHER:0})

    def test_b03_source_admission_requires_two_actual_quest_area_slots_before_payment(self):
        g=self.game(rules=Ruleset(max_secret_zone=1));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,ROOT)
        self.assertEqual(g.snapshot(),before)

    def test_b04_automatic_root_still_casts_two_children_without_inventing_paid_plays(self):
        g=self.game((P+'auto_root',));self.play(g,P+'auto_root')
        self.assertEqual(self.quests(g),{HOLY:0,SHADOW:0});self.assertEqual(g.state.players[1].mana,10)
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(tuple(c.origin for c in g.state.cast_history),('hand','effect','effect','effect'))
        self.portable(g)

    def test_b05_same_child_name_cast_by_an_unrelated_spell_cannot_bypass_the_main_quest_lock(self):
        g=self.game((ROOT,P+'remove_holy',P+'auto_child'));self.play(g,ROOT);self.play(g,P+'remove_holy')
        self.assertEqual(self.quests(g),{SHADOW:0});self.play(g,P+'auto_child')
        self.assertEqual(self.quests(g),{SHADOW:0});self.assertTrue(any(e.kind=='quest_activation_failed'for e in g._events));self.portable(g)

    def test_b06_prior_and_opponent_casts_do_not_count_but_new_automatic_holy_casts_do(self):
        g=self.game((H,ROOT,P+'auto_holy',N),enemy_hand=(H,));self.play(g,H);self.play(g,ROOT)
        self.assertEqual(self.quests(g),{HOLY:0,SHADOW:0});self.play(g,N);self.play(g,P+'auto_holy')
        self.assertEqual(self.quests(g),{HOLY:1,SHADOW:0});g.apply(EndTurn(1));self.play(g,H)
        self.assertEqual(self.quests(g),{HOLY:1,SHADOW:0});self.portable(g)

    def test_b07_terminal_after_second_activation_keeps_both_original_accepted_child_quests(self):
        g=self.game(board=(END_AFTER_SHADOW,));self.play(g,ROOT)
        self.assertNotEqual(g.state.status,'playing');self.assertEqual(self.quests(g),{HOLY:0,SHADOW:0})
        self.assertTrue(g.state.cast_history[0].interrupted);self.portable(g)

    def test_b08_native_one_cost_repetitions_do_not_replace_original_quest_activation_or_inherit_pair_permission(self):
        g=self.game(board=('TLC_836',));self.play(g,ROOT)
        self.assertEqual(self.quests(g),{HOLY:0,SHADOW:0})
        originals=[c for c in g.state.cast_history if c.quest_parent_cast_id is not None]
        repeats=[c for c in g.state.cast_history if c.origin=='native_repeat']
        self.assertEqual({c.card_id for c in originals},{HOLY,SHADOW});self.assertTrue(repeats)
        self.assertTrue(all(c.quest_parent_cast_id is None for c in repeats))
        self.assertEqual({g.state.entities[i].quest_progress.activation_cast_id for i in g.state.players[1].quests},{c.id for c in originals})
        self.portable(g)

    def test_c00_wait_between_child_casts_preserves_the_exact_open_parent_and_second_child(self):
        g=self.game(board=(WAIT_START,));self.play(g,ROOT)
        self.assertEqual(self.quests(g),{HOLY:0});self.assertIsNotNone(g.state.pending_choice)
        g=self.portable(g);self.choose(g);self.assertEqual(self.quests(g),{HOLY:0,SHADOW:0})
        self.assertGreater(g.state.cast_history[2].action,g.state.cast_history[0].action)
        self.assertEqual(tuple(c.card_id for c in g.state.cast_history),(ROOT,HOLY,SHADOW));self.portable(g)

    def test_c01_failed_between_child_resume_rolls_back_only_the_resume_and_keeps_original_payment(self):
        g=self.game(board=(WAIT_START,));self.play(g,ROOT);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.assertEqual(g.state.players[1].mana,9)
        self.choose(g);self.assertEqual(self.quests(g),{HOLY:0,SHADOW:0});self.portable(g)

    def test_c02_reward_wait_keeps_both_original_child_quests_until_ordinary_finish(self):
        g=self.game((ROOT,*(H,)*4),board=(WAIT_REWARD,));self.play(g,ROOT);self.complete(g,H)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.quests(g),{HOLY:4,SHADOW:0})
        self.assertIn(LEFT,self.names(g));g=self.portable(g);self.choose(g)
        self.assertEqual(self.quests(g),{SHADOW:0});self.assertEqual(self.names(g).count(LEFT),1);self.portable(g)

    def test_c03_failed_reward_resume_keeps_one_already_created_original_half(self):
        g=self.game((ROOT,*(H,)*4),board=(WAIT_REWARD,));self.play(g,ROOT);self.complete(g,H);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(self.names(g).count(LEFT),1)

    def test_d00_minion_halves_combine_across_intervening_cards_in_both_orders(self):
        for hand in ((LEFT,N,RIGHT),(RIGHT,N,LEFT)):
            with self.subTest(hand=hand):
                g=self.game(hand);self.assertEqual(self.names(g),(FULL,N))
                self.assertFalse(g.state.death_history);self.assertFalse(g.state.discard_history);self.portable(g)

    def test_d01_halves_in_different_hands_do_not_combine_or_leak(self):
        g=self.game((LEFT,),enemy_hand=(RIGHT,));self.assertEqual(self.names(g),(LEFT,));self.assertEqual(self.names(g,2),(RIGHT,))
        self.assertNotIn(RIGHT,json.dumps(g.for_player(1).observe()));self.assertNotIn(LEFT,json.dumps(g.for_player(2).observe()))
        self.portable(g)

    def test_d02_discarded_half_is_not_reused_when_the_other_half_later_arrives(self):
        g=self.game((LEFT,P+'discard_left',P+'right'));self.play(g,P+'discard_left');self.play(g,P+'right')
        self.assertEqual(self.names(g),(RIGHT,));self.assertEqual(len(g.state.discard_history),1);self.portable(g)

    def test_d03_local_canonical_left_discount_survives_combination_into_a_new_entity(self):
        g=self.game((LEFT,P+'discount_left',P+'right'));left=g.state.players[1].hand[0]
        self.play(g,P+'discount_left');self.play(g,P+'right');self.assertEqual(self.names(g),(FULL,))
        eid=g.state.players[1].hand[0];self.assertNotEqual(eid,left)
        self.assertEqual(g.state.hand_entries[g.state.entities[eid].hand_entry_id-1].source_id,left)
        self.assertEqual(quote_cost(g.state,g.registry,g.state.entities[eid]).amount,3)
        self.assertEqual(g.state.entities[left].zone,Zone.GRAVEYARD);self.portable(g)

    def test_d04_failed_acquisition_after_combination_rolls_back_both_halves_new_body_rng_and_history(self):
        g=self.game((LEFT,P+'right'),board=(BAD,));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,P+'right')
        self.assertEqual(g.snapshot(),before);self.assertIn(LEFT,self.names(g));self.assertNotIn(FULL,self.names(g))

    def test_e00_life_half_independently_summons_a_current_four_four_taunt_copy(self):
        g=self.game((LEFT,));self.play(g,LEFT);board=[g.state.entities[i]for i in g.state.players[1].board]
        self.assertEqual(len(board),2);self.assertTrue(all((e.card_id,e.attack,e.health)==(LEFT,4,4)for e in board))
        self.assertTrue(all(Keyword.TAUNT in e.keywords for e in board));self.portable(g)

    def test_e01_death_half_independently_has_reborn_and_real_nonspell_deathrattle(self):
        g=self.game((RIGHT,P+'destroy',P+'destroy'));self.play(g,RIGHT);self.play(g,P+'destroy')
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,25)
        self.assertEqual(len(g.state.players[1].board),1);reborn=g.state.entities[g.state.players[1].board[0]]
        self.assertEqual((reborn.card_id,reborn.health),(RIGHT,1));self.play(g,P+'destroy')
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,20);self.assertFalse(g.state.players[1].board);self.portable(g)

    def test_e02_combined_reward_keeps_its_existing_full_battlecry_and_body(self):
        g=self.game((LEFT,N,RIGHT));self.play(g,FULL)
        board=[g.state.entities[i]for i in g.state.players[1].board]
        self.assertEqual(len(board),2);self.assertTrue(all((e.card_id,e.attack,e.health)==(FULL,8,8)for e in board))
        self.assertTrue(all(Keyword.TAUNT in e.keywords and Keyword.REBORN in e.keywords for e in board));self.portable(g)

    def test_f00_rehashed_active_children_cannot_claim_an_unrelated_parent_caster(self):
        g=self.game();self.play(g,ROOT);s=json.loads(json.dumps(g.snapshot()))
        s['state']['cast_history'][2]['caster_id']=g.state.players[1].hero_id
        from test_current_deck_empty_basics import rehash
        rehash(s)
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry('reader'))

    def test_f01_player_projections_show_public_quest_progress_without_original_cast_proofs(self):
        g=self.game((ROOT,H));self.play(g,ROOT);self.play(g,H)
        for pid in (1,2):
            wire=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for key in ('"cast_history"','"activation_cast_id"','"quest_parent_cast_id"','"paired_quest"','"resolution_frame"','"original_deck"','"rng_state"'):
                self.assertNotIn(key,wire)

    def test_f02_rehashed_quest_progress_cannot_borrow_the_other_child_activation(self):
        g=self.game();self.play(g,ROOT);s=json.loads(json.dumps(g.snapshot()))
        eid=next(i for i in g.state.players[1].quests if g.state.entities[i].card_id==HOLY)
        s['state']['entities'][str(eid)]['quest_progress']['activation_cast_id']=3
        from test_current_deck_empty_basics import rehash
        rehash(s)
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry('reader'))


if __name__=='__main__':unittest.main()
