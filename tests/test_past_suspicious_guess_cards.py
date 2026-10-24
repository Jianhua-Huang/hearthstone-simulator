"""Native Discover, delayed private guessing, and shared original-copy delivery."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards.past_suspicious_guess_cards import (ALCHEMIST, USHER, POOL_ID,
    load_batch, register_past_suspicious_guess_cards)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, PlayerSetup, Rarity, Registry, Scenario, TriggerSpec, Zone)
from hs_sim.engine.discovery_guesses import START, SELECTED, OFFERED, FINISHED
from hs_sim.engine.effects import (ChoiceOption, CopyMinion, Destroy, GainArmor,
    RequestChoice, ReturnToHand, Silence, ChangeControl)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import BattlecryRepeatSpec, ChoicePurpose, CostSpec
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.zones import CardReference, ModifyStoredCost
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonCause

P='k488.'
HERO, POWER, A, WATCH, REPEAT=(P+s for s in ('hero','power','a','watch','repeat'))
SPELLS=tuple(P+'s'+str(i)for i in range(3))
MINIONS=tuple(P+'m'+str(i)for i in range(3))
META=CardMetadata(collectible=True,classes=(CardClass.MAGE,),rarity=Rarity.COMMON,tribes=())
CTX=GenerationContext('k488-explicit-full-fixture','experimental')


def memories(entity):
    return tuple(e for e in entity.enchantments if e.discovery_guess is not None)


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=Registry(P+mode);register_past_suspicious_guess_cards(r)
    r.register_behavior(P+'marker',lambda c:(GainArmor(c.player_id,2),))
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=100,metadata=META,initial_hero_power=POWER))
    r.register_card(CardDefinition(POWER,POWER,CardType.HERO_POWER,on_use=P+'marker'))
    r.register_card(CardDefinition(A,A,CardType.MINION,health=5,metadata=replace(META,collectible=False)))
    r.register_card(CardDefinition(REPEAT,REPEAT,CardType.MINION,health=10,battlecry_repeats=(BattlecryRepeatSpec(),)))
    for cid in SPELLS:r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1,on_play=P+'marker',metadata=META))
    for cid in MINIONS:r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=2,attack=2,health=3,
        metadata=replace(META,rarity=Rarity.LEGENDARY)))
    def source(c):
        return next(c.state.entities[i]for player in c.state.players.values()for i in player.board
            if c.state.entities[i].card_id in(ALCHEMIST,USHER))
    def buff(c):
        target=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id in MINIONS)
        ref=CardReference.capture(target)
        return(BuffStoredCard(ref,3,4,c.source_id),ModifyStoredCost(ref,CostSpec(set_to=0),c.source_id))
    bodies=dict(buff=buff,kill=lambda c:(Destroy(source(c).id,c.source_id),),
        silence=lambda c:(Silence(source(c).id),),
        bounce=lambda c:(ReturnToHand(source(c).id),),
        control=lambda c:(ChangeControl(source(c).id,3-c.player_id),),
        copy=lambda c:(CopyMinion(source(c).id,c.player_id,cause=SummonCause.capture(c)),))
    for name,body in bodies.items():
        r.register_behavior(P+name,body);r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name))
    def watch(c):
        if mode=='die_during_delivery'and c.event.kind=='card_added_to_hand'and c.event.player_id==1:
            return(Destroy(source(c).id,c.source_id),)
        if mode=='wait_after_discovery'and c.event.kind=='card_discovered':
            return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),),c.source_id),)
        if c.event.kind=='card_added_to_hand'and c.event.player_id==2:
            if mode=='copy_failure':raise ResolutionError('K488 deliberate copy acquisition failure')
            if mode=='copy_wait':return(RequestChoice(2,(ChoiceOption('continue','Continue'),),c.source_id),)
        return()
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=10,
        triggers=(TriggerSpec('card_added_to_hand',P+'watch'),TriggerSpec('card_discovered',P+'watch'))))
    members=list((*SPELLS,*MINIONS))
    for cid in members:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if mode=='unknown':
        r.register_pool_card(PoolCard(P+'unknown',CardType.SPELL,1,META));members.append(P+'unknown')
    if mode=='unknown_legendary':
        r.register_pool_card(PoolCard(P+'unknown',CardType.MINION,1,replace(META,rarity=Rarity.LEGENDARY)));members.append(P+'unknown')
    if mode=='small':members=[SPELLS[0],MINIONS[0]]
    if mode=='empty':members=[]
    r.register_pool(PoolDefinition(POOL_ID,P+'complete-fixture',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in members),complete=True))
    r.validate();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events'])
    s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
    return s


class PastSuspiciousGuessTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)

    def game(self,card=ALCHEMIST,*,extra=(),board=(),enemy_hand=(),mode='normal'):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=(card,*extra),board=tuple(board),mana=10,max_mana=10),
            PlayerSetup(HERO,hand=tuple(enemy_hand),mana=10,max_mana=10)),seed=488,generation_context=CTX),registry(mode))

    def pick(self,g,card_id=None):
        choice=g.state.pending_choice
        from hs_sim.engine import SelectChoice
        item=next(o for o in choice.options if card_id is None or o.card_id==card_id)
        g.apply(SelectChoice(choice.player_id,choice.id,(item.id,)))
        return item.card_id

    def discover(self,g,card=ALCHEMIST,chosen=None):
        actor=self.play(g,card);chosen=self.pick(g,chosen)
        return actor,chosen

    def guess(self,g,chosen=None):
        g.apply(EndTurn(1));self.assertEqual(g.state.pending_choice.player_id,2)
        return self.pick(g,chosen)

    def test_two_full_roots_four_primary_faces_and_one_raw_riddle_are_preserved(self):
        d=load_batch();self.assertEqual(len(d['dependencies']),2);self.assertEqual(len(d['official_observations']),4)
        self.assertEqual(d['evidence_only'][0]['record']['id'],'REV_000e')
        self.assertNotIn('REV_000e',registry().cards)
        self.assertTrue(all((x['record']['cost'],x['record']['attack'],x['record']['health'])==(1,1,3)for x in d['dependencies']))
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])

    def test_native_spell_discover_then_correct_delayed_guess_copies_original(self):
        g=self.game();actor,chosen=self.discover(g);e=self.entity(g,chosen)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(memories(g.state.entities[actor])),1)
        self.guess(g,chosen);copied=self.entity(g,chosen,2)
        self.assertNotEqual(copied.id,e.id);self.assertEqual(copied.origin_entity_id,e.id)
        self.assertIsNotNone(copied.copy_origin)
        self.assertEqual(len(g.state.card_discovery_history),1)
        self.assertFalse(memories(g.state.entities[actor]));self.portable(g)

    def test_usher_discovers_only_current_class_legendary_minions(self):
        g=self.game(USHER);self.play(g,USHER)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},set(MINIONS))
        chosen=self.pick(g);self.guess(g,chosen);self.assertEqual(self.entity(g,chosen,2).kind,CardType.MINION)

    def test_wrong_guess_gives_no_card_and_consumes_only_this_riddle(self):
        g=self.game();actor,chosen=self.discover(g);wrong=next(cid for cid in SPELLS if cid!=chosen)
        self.guess(g,wrong);self.assertEqual(g.state.players[2].hand,[])
        self.assertFalse(memories(g.state.entities[actor]));self.assertFalse(any(a.behavior_id==START for a in g.state.entities[actor].abilities))
        g.apply(EndTurn(2));g.apply(EndTurn(1));self.assertIsNone(g.state.pending_choice)

    def test_guess_keeps_all_original_ordered_options_without_rediscovery_rng(self):
        g=self.game();self.play(g,ALCHEMIST);faces=tuple(o.card_id for o in g.state.pending_choice.options)
        chosen=self.pick(g);rng=g.snapshot()['rng_state'];g.apply(EndTurn(1))
        self.assertEqual(tuple(o.card_id for o in g.state.pending_choice.options),faces)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.pick(g,chosen);self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_playing_discovered_spell_does_not_remove_original_answer(self):
        g=self.game();actor,chosen=self.discover(g);original=self.entity(g,chosen).id;self.play(g,chosen)
        self.guess(g,chosen);self.assertEqual(self.entity(g,chosen,2).origin_entity_id,original)
        self.assertEqual(g.state.entities[original].zone,Zone.GRAVEYARD)

    def test_same_original_hand_residence_copy_keeps_current_stats_and_cost(self):
        g=self.game(USHER,extra=(P+'buff',));_,chosen=self.discover(g,USHER);self.play(g,P+'buff')
        original=self.entity(g,chosen);self.guess(g,chosen);copied=self.entity(g,chosen,2)
        from hs_sim.engine.costs import local_cost
        self.assertEqual((copied.attack,copied.max_health,local_cost(copied)[0]),(5,7,0))
        self.assertEqual(copied.origin_entity_id,original.id);self.portable(g)

    def test_death_before_opponent_start_cancels_guess(self):
        g=self.game(extra=(P+'kill',));self.discover(g);self.play(g,P+'kill');g.apply(EndTurn(1))
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.state.players[2].hand,[])

    def test_silence_before_opponent_start_removes_memory_and_trigger(self):
        g=self.game(extra=(P+'silence',));actor,_=self.discover(g);self.play(g,P+'silence')
        self.assertFalse(memories(g.state.entities[actor]));g.apply(EndTurn(1));self.assertIsNone(g.state.pending_choice)

    def test_normal_bounce_then_replay_does_not_revive_the_old_guess(self):
        g=self.game(extra=(P+'bounce',));actor,_=self.discover(g);self.play(g,P+'bounce')
        self.assertFalse(memories(g.state.entities[actor]));self.play(g,ALCHEMIST);chosen=self.pick(g)
        self.assertEqual(len(memories(g.state.entities[actor])),1);self.guess(g,chosen)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(g.state.players[2].hand),1)

    def test_control_transfer_keeps_the_original_opponent_as_guesser(self):
        g=self.game(extra=(P+'control',));actor,chosen=self.discover(g);self.play(g,P+'control')
        self.assertEqual(g.state.entities[actor].controller,2);self.guess(g,chosen)
        self.assertEqual(self.entity(g,chosen,2).controller,2);self.portable(g)

    def test_copied_source_has_independent_attachment_and_same_original_answer(self):
        g=self.game(extra=(P+'copy',));actor,chosen=self.discover(g);self.play(g,P+'copy')
        sources=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==ALCHEMIST]
        self.assertEqual(len(sources),2);self.assertNotEqual(memories(sources[0])[0].id,memories(sources[1])[0].id)
        g.apply(EndTurn(1));self.pick(g,chosen);self.assertIsNotNone(g.state.pending_choice);self.pick(g,chosen)
        self.assertEqual(len(g.state.players[2].hand),2);self.portable(g)

    def test_repeat_battlecries_make_two_independent_guesses_with_one_source_trigger(self):
        g=self.game(board=(REPEAT,));actor=self.play(g,ALCHEMIST)
        first=self.pick(g);second=self.pick(g)
        self.assertEqual(len(memories(g.state.entities[actor])),2)
        self.assertEqual(sum(a.kind=='trigger'and a.behavior_id==START for a in g.state.entities[actor].abilities),1)
        g.apply(EndTurn(1));self.pick(g,first);self.pick(g,second)
        self.assertEqual(len(g.state.players[2].hand),2);self.assertIsNone(g.state.pending_choice)

    def test_original_overflow_still_remembers_real_burned_recipient(self):
        g=self.game(extra=(SPELLS[0],)*9,board=(REPEAT,));actor=self.play(g,ALCHEMIST)
        first=self.pick(g);second=self.pick(g)
        memory=memories(g.state.entities[actor])[1].discovery_guess
        self.assertEqual(memory.recipient.zone,Zone.GRAVEYARD)
        g.apply(EndTurn(1));self.pick(g,first);self.pick(g,second)
        self.assertEqual(len(g.state.players[2].hand),2)

    def test_full_guesser_hand_uses_shared_copy_overflow(self):
        g=self.game(enemy_hand=(SPELLS[0],)*10);_,chosen=self.discover(g);self.guess(g,chosen)
        self.assertEqual(len(g.state.players[2].hand),10)
        burned=[g.state.entities[i]for i in g.state.players[2].graveyard if g.state.entities[i].card_id==chosen]
        self.assertEqual(len(burned),1);self.assertIsNotNone(burned[0].copy_origin)

    def test_one_option_pool_is_not_padded_and_has_one_valid_guess(self):
        g=self.game(mode='small');self.play(g,ALCHEMIST);self.assertEqual(len(g.state.pending_choice.options),1)
        chosen=self.pick(g);g.apply(EndTurn(1));self.assertEqual(len(g.state.pending_choice.options),1)
        self.pick(g,chosen);self.assertEqual(len(g.state.players[2].hand),1)

    def test_empty_pool_creates_no_memory_or_guess(self):
        g=self.game(mode='empty');actor=self.play(g,ALCHEMIST)
        self.assertIsNone(g.state.pending_choice);self.assertFalse(memories(g.state.entities[actor]))
        g.apply(EndTurn(1));self.assertIsNone(g.state.pending_choice)

    def test_unknown_eligible_candidates_fail_before_rng_and_rollback_payment(self):
        for card,mode in((ALCHEMIST,'unknown'),(USHER,'unknown_legendary')):
            with self.subTest(card=card):
                g=self.game(card,mode=mode);before=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,card)
                self.assertEqual(g.snapshot(),before)

    def test_first_discovery_wait_restores_then_schedules_exact_original_menu(self):
        g=self.game();self.play(g,ALCHEMIST);restored=self.portable(g);chosen=g.state.pending_choice.options[0].card_id
        self.pick(g,chosen);self.pick(restored,chosen);self.assertEqual(g.snapshot(),restored.snapshot())
        self.guess(g,chosen);self.guess(restored,chosen);self.assertEqual(g.snapshot(),restored.snapshot())

    def test_delayed_guess_wait_restores_clones_replays_then_copies_once(self):
        g=self.game();_,chosen=self.discover(g);g.apply(EndTurn(1));restored=self.portable(g)
        self.pick(g,chosen);self.pick(restored,chosen);self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(len(g.state.players[2].hand),1)

    def test_after_discovery_wait_contains_completed_riddle_and_recipient(self):
        g=self.game(board=(WATCH,),mode='wait_after_discovery');actor,chosen=self.discover(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertIsNotNone(memories(g.state.entities[actor])[0].discovery_guess.recipient)
        restored=self.portable(g);self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot())

    def test_source_dying_during_original_delivery_cannot_leave_a_late_riddle(self):
        g=self.game(board=(WATCH,),mode='die_during_delivery');actor,_=self.discover(g)
        self.assertEqual(g.state.entities[actor].zone,Zone.GRAVEYARD);g.apply(EndTurn(1));self.assertIsNone(g.state.pending_choice)

    def test_copy_acquisition_failure_rolls_back_choice_copy_and_private_receipt(self):
        g=self.game(board=(WATCH,),mode='copy_failure');_,chosen=self.discover(g);g.apply(EndTurn(1));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.pick(g,chosen)
        self.assertEqual(g.snapshot(),before)

    def test_copy_acquisition_wait_restores_without_reopening_guess(self):
        g=self.game(board=(WATCH,),mode='copy_wait');_,chosen=self.discover(g);g.apply(EndTurn(1));self.pick(g,chosen)
        self.assertIsNotNone(g.state.pending_choice);restored=self.portable(g)
        self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(len(g.state.players[2].hand),1)

    def test_rehashed_changed_memory_recipient_and_pending_menu_are_rejected(self):
        g=self.game();actor,chosen=self.discover(g);saved=g.snapshot();bad=deepcopy(saved)
        e=bad['state']['entities'][str(actor)]['enchantments'][0]['discovery_guess'];e['recipient']['entity_id']=actor
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry('normal','bad-memory'))
        g.apply(EndTurn(1));bad=deepcopy(g.snapshot());bad['state']['pending_choice']['options'][0]['card_id']=P+'a'
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry('normal','bad-menu'))

    def test_first_choice_answer_and_internal_memory_are_not_sent_to_opponent(self):
        g=self.game();self.play(g,ALCHEMIST)
        opponent=json.dumps(g.for_player(2).observe());self.assertNotIn('"options"',opponent)
        chosen=self.pick(g);g.apply(EndTurn(1))
        view=json.dumps(g.for_player(2).observe())
        for field in ('discovery_guess','discovery_id','recipient','battlecry_id','request','attachment_id'):
            self.assertNotIn('"'+field+'"',view)
        self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.EFFECT)
        self.assertNotIn(OFFERED,view);self.assertNotIn(FINISHED,view)

    def test_rehashed_removed_whole_pending_guess_is_rejected(self):
        g=self.game();self.discover(g);g.apply(EndTurn(1));bad=deepcopy(g.snapshot())
        reader=registry('normal','cropped-guess')
        self.assertEqual(reader.fingerprint(),bad['registry_fingerprint'])
        bad['state']['pending_choice']=None;bad['resolution_frame']=None
        with self.assertRaises(SnapshotError)as caught:Game.from_snapshot(rehash(bad),reader)
        self.assertNotIn('fingerprint',str(caught.exception).lower())
