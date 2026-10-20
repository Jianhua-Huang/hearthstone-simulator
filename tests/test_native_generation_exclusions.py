"""Reviewed native random bans never become bans on named or physical cards."""
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import load_batch,register_candidate_pool_metadata
from hs_sim.engine import (CardDefinition,CardType,Game,PlayCard,PlayerSetup,Rarity,
    Registry,ResolutionError,Scenario,SelectChoice,SnapshotError,TriggerSpec)
from hs_sim.engine.effects import AddToHand,ChoiceOption,RequestChoice
from hs_sim.engine.pools import (DiscoverFromPool,GenerateFromPool,GenerationContext,
    PoolDefinition,PoolMember,PoolQuery,SPECIAL_GENERATION_KEYWORDS,resolve_candidates)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.zones import DrawMatching

BLOCKED=('JAIL_500','JAIL_831');BRIGHT='CORE_EX1_189';LEGEND='CORE_EX1_110';SPELL='CS2_029'
CTX=GenerationContext('native-generation-exclusions-test','experimental')
LEGEND_POOL='constructed.cards';SPELL_POOL='native-exclusion.spells'
GENERATE='native-exclusion.generate';DISCOVER='native-exclusion.discover'
NAMED='native-exclusion.named';WATCH='native-exclusion.watch'


def registry(mode='plain',*,old_policy=False):
    register=Registry.register_generation_exclusion
    def previous_scope(r,cid):
        if cid not in BLOCKED:register(r,cid)
    if old_policy:
        with patch.object(Registry,'register_generation_exclusion',previous_scope):r=build_registry()
    else:r=build_registry()
    for pool,members in((LEGEND_POOL,(BLOCKED[1],LEGEND)),(SPELL_POOL,(BLOCKED[0],SPELL))):
        r.register_pool(PoolDefinition(pool,'complete-two-member-experiment-v1',CTX.target_id,CTX.mode,
            tuple(PoolMember(cid)for cid in members),complete=True))
    scripts={GENERATE:lambda c:(GenerateFromPool(c.player_id,SPELL_POOL,PoolQuery(kinds=(CardType.SPELL,)),source_id=c.source_id),),
        DISCOVER:lambda c:(DiscoverFromPool(c.player_id,SPELL_POOL,PoolQuery(kinds=(CardType.SPELL,)),source_id=c.source_id),),
        NAMED:lambda c:(AddToHand(c.player_id,BLOCKED[1],c.source_id),
            DrawMatching(c.player_id,PoolQuery(card_ids=(BLOCKED[0],)),'skip',source_id=c.source_id))}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
    if mode!='plain':
        def watch(c):
            if c.state.entities[c.event.target_id].card_id!=LEGEND:return()
            if mode=='fault':raise RuntimeError('Explicit generated-card observer failure')
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),source_id=c.source_id),)
        r.register_behavior(WATCH,watch)
        r.register_card(CardDefinition(WATCH,'Explicit generation observer '+mode,CardType.MINION,health=5,
            triggers=(TriggerSpec('card_created',WATCH),)))
    return r


class NativeGenerationExclusionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.base=registry()
    def candidates(self,pool,query=PoolQuery()):
        return tuple(c.card_id for c in resolve_candidates(self.base,CTX,pool,query))
    def game(self,hand=(),*,deck=(LEGEND,),mode='plain'):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,deck=deck,
            board=()if mode=='plain'else(WATCH,),mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=(LEGEND,))),seed=320,generation_context=CTX),
            self.base if mode=='plain'else registry(mode))
    def play(self,g,cid):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid));return eid
    def hand(self,g):return[g.state.entities[i].card_id for i in g.state.players[1].hand]
    def portable(self,g,mode='plain'):
        saved=g.snapshot();self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(Game.from_snapshot(saved,registry(mode)).snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(mode)).snapshot(),saved)

    def test_flagged_real_spell_is_not_an_ordinary_random_candidate(self):
        self.assertEqual(self.candidates(SPELL_POOL,PoolQuery(kinds=(CardType.SPELL,))),(SPELL,))

    def test_flagged_contraband_king_is_not_a_random_legendary_candidate(self):
        self.assertEqual(self.candidates(LEGEND_POOL,PoolQuery(kinds=(CardType.MINION,),rarities=(Rarity.LEGENDARY,))),(LEGEND,))

    def test_real_brightwing_uses_remaining_complete_eligible_pool(self):
        g=self.game((BRIGHT,));self.play(g,BRIGHT)
        self.assertEqual(self.hand(g),[LEGEND]);self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def test_random_spell_and_discover_share_native_bans(self):
        g=self.game((GENERATE,DISCOVER));self.play(g,GENERATE);self.assertEqual(self.hand(g).count(SPELL),1)
        self.play(g,DISCOVER);q=g.state.pending_choice
        self.assertIsNotNone(q);self.assertTrue(all(o.card_id==SPELL for o in q.options))
        g.apply(SelectChoice(q.player_id,q.id,(q.options[0].id,)))
        self.assertEqual(self.hand(g),[SPELL,SPELL]);self.portable(g)

    def test_named_grant_and_physical_draw_keep_both_native_identities(self):
        g=self.game((NAMED,),deck=(BLOCKED[0],));original=g.state.players[1].deck[0]
        self.play(g,NAMED);self.assertEqual(set(self.hand(g)),set(BLOCKED))
        self.assertIn(original,g.state.players[1].hand)
        self.assertFalse(any(r.card_id in BLOCKED for r in g.state.play_history));self.portable(g)

    def test_blocked_missing_definition_does_not_hide_other_eligible_missing_code(self):
        r=Registry('independent-native-exclusion-test');r.register_pool_card(self.base.pool_card(BLOCKED[1]))
        r.register_generation_exclusion(BLOCKED[1])
        r.register_pool(PoolDefinition('blocked','v1',CTX.target_id,CTX.mode,(PoolMember(BLOCKED[1]),),complete=True))
        self.assertEqual(resolve_candidates(r,CTX,'blocked',PoolQuery()),())
        r.register_pool_card(self.base.pool_card(LEGEND))
        r.register_pool(PoolDefinition('unknown','v1',CTX.target_id,CTX.mode,(PoolMember(BLOCKED[1]),PoolMember(LEGEND)),complete=True))
        with self.assertRaises(UnsupportedDefinitionError):resolve_candidates(r,CTX,'unknown',PoolQuery())

    def test_real_brightwing_wait_restore_replay_finishes_original_paid_tail(self):
        g=self.game((BRIGHT,),mode='wait');self.play(g,BRIGHT)
        self.assertEqual(self.hand(g),[LEGEND]);self.assertIsNotNone(g.state.pending_choice);self.portable(g,'wait')
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertTrue(g.state.play_history[-1].completed);self.assertEqual(self.hand(g),[LEGEND]);self.portable(g,'wait')

    def test_actual_generation_fault_rolls_back_payment_rng_and_physical_cards(self):
        g=self.game((BRIGHT,),mode='fault');before=g.snapshot();history=g.history
        with self.assertRaises(ResolutionError):self.play(g,BRIGHT)
        self.assertEqual(g.snapshot(),before);self.assertEqual(g.history,history)

    def test_registry_commitment_rejects_losing_only_the_two_native_bans(self):
        g=self.game((BRIGHT,));self.play(g,BRIGHT);other=registry(old_policy=True)
        self.assertNotEqual(other.fingerprint(),g.registry.fingerprint())
        with self.assertRaises(SnapshotError):Game.from_snapshot(g.snapshot(),other)

    def test_all_current_flagged_roots_have_independent_existing_or_native_gate(self):
        raw=[r['record']for r in load_batch()['cards']if r['record']['tags'].get('DONT_PICK_FROM_SUBSETS')==1]
        self.assertEqual(len(raw),26);self.assertTrue(set(BLOCKED)<=self.base.fabled_generation_exclusions)
        self.assertFalse(set(BLOCKED)&set(self.base.fabled))
        self.assertTrue(all(r['id']in self.base.fabled_generation_exclusions or
            set(self.base.pool_card(r['id']).keywords)&SPECIAL_GENERATION_KEYWORDS for r in raw))
        partial=Registry('native-metadata-only');register_candidate_pool_metadata(partial)
        self.assertFalse(partial.cards)
        self.assertTrue(all(r['id']in partial.fabled_generation_exclusions or
            set(partial.pool_card(r['id']).keywords)&SPECIAL_GENERATION_KEYWORDS for r in raw))


if __name__=='__main__':unittest.main()
