"""Real original acquisition, stealth attack, commitment and target boundaries."""
from dataclasses import asdict,replace
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards import assemble_entry_commit_target_followups as cards
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.native_assemble_entry_cards import POOL_ID as ASSEMBLE_POOL
from hs_sim.engine import (Attack,CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,
    PlayerSetup,Scenario,SelectChoice,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Damage,Destroy,GainArmor,InvokeBehavior,
    RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_history import from_event
from hs_sim.engine.model import CardClass,DamageKind,Rarity
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.play_history import played_cards
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import TargetValidationError,canonical_digest
from tools.card_batch import check_face,sha
from test_assemble_damage_health_followups import fixture as base_fixture
from test_assemble_attack_finished_followups import DUMMY
from test_assemble_card_play_followups import META,N,KILL,MUTE,COIN,WAR,CURATOR,LOOT

PANDA,SHAW,WEB,FRAGMENT=cards.SOURCES
AUCTIONEER='JAIL_718'
P='k430.'
SPELL,NOOP,ADD,HELD,STEALTHY,PING,SLAY,PROBE,WATCH,FAIL,UNKNOWN=(
    P+x for x in ('spell','noop','add','held','stealthy','ping','slay','probe','watch','fail','unknown'))
CTX=GenerationContext('k430-explicit-source-and-spell-domain','experimental')
DECK=(COIN,)*24


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=base_fixture.__wrapped__('normal',role);r._version+='.k430.'+mode
    r.register_behavior(NOOP,lambda c:())
    r.register_card(CardDefinition(NOOP,NOOP,CardType.SPELL,on_play=NOOP,metadata=META))
    r.register_card(CardDefinition(SPELL,SPELL,CardType.SPELL,cost=1,on_play=NOOP,
        metadata=replace(META,collectible=True,rarity=Rarity.COMMON,deck_identity=SPELL)))
    r.register_pool_card(PoolCard.from_definition(r.card(SPELL)))
    r.register_card(CardDefinition(HELD,HELD,CardType.MINION,cost=5,health=12,metadata=META))
    r.register_card(CardDefinition(STEALTHY,STEALTHY,CardType.MINION,attack=1,health=12,
        keywords=(Keyword.STEALTH,),metadata=META))
    r.register_behavior(ADD,lambda c:(AddToHand(c.player_id,HELD,c.source_id),))
    r.register_card(CardDefinition(ADD,ADD,CardType.SPELL,on_play=ADD,metadata=META))
    for cid,body in ((PING,lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),)),
            (SLAY,lambda c:(Destroy(c.target_id,c.source_id),))):
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=TargetSpec(),metadata=META))
    def probe(c):
        if not any(row.player_id==c.player_id for row in c.state.draw_history):
            raise ResolutionError('K430 repeat commitment reward must precede the new battlecry')
        return ()
    r.register_behavior(PROBE,probe)
    r.register_card(CardDefinition(PROBE,PROBE,CardType.MINION,health=12,battlecry=PROBE,
        metadata=replace(META,deck_identity=N)))
    def fail(c):raise ResolutionError('K430 deliberate hand-acquisition continuation failure')
    def watch(c):
        row=from_event(c.state,c.event)
        if row.player_id!=1 or row.card_id!=SPELL:return ()
        return (RequestChoice(1,(ChoiceOption('go','Continue'),ChoiceOption('bad','Fail',
            (GainArmor(1,1),InvokeBehavior(FAIL,c.source_id,1)))),c.source_id),)
    r.register_behavior(FAIL,fail);r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=40,metadata=META,
        triggers=(TriggerSpec('hand_card_entered',WATCH),)))
    members=(SPELL,)
    if mode=='unknown':
        missing=CardDefinition(UNKNOWN,UNKNOWN,CardType.SPELL,cost=1,
            metadata=replace(META,collectible=True,rarity=Rarity.COMMON,deck_identity=UNKNOWN))
        r.register_pool_card(PoolCard.from_definition(missing));members+=(UNKNOWN,)
    if mode!='no_pool':
        r.register_pool(PoolDefinition(cards.native_panda.POOL,'k430-complete-explicit-spell-domain',CTX.target_id,
            CTX.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    if mode=='assemble':
        r.register_pool(PoolDefinition(ASSEMBLE_POOL,'k430-low-neutral-primary-two-known-high-donors',CTX.target_id,
            CTX.mode,tuple(PoolMember(cid)for cid in (PANDA,AUCTIONEER,WAR)),complete=True))
    r.validate();return r


class AssembleEntryCommitTargetTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),mode='normal',active=1,cap=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_03',hand=hand,board=board,deck=DECK,mana=40,max_mana=40,mana_cap=40,hand_cap=cap),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=DECK,mana=40,max_mana=40,mana_cap=40)),
            active_player=active,seed=430,generation_context=CTX),fixture(mode))

    def eid(self,g,cid,player=1,zone='board'):
        return next(i for i in getattr(g.state.players[player],zone)if g.state.entities[i].card_id==cid)

    def play(self,g,cid,target=None):
        p=g.state.active_player;e=self.eid(g,cid,p,'hand');g.apply(PlayCard(p,e,target));return e

    def count(self,g,cid,player=1,zone='hand'):
        return sum(g.state.entities[i].card_id==cid for i in getattr(g.state.players[player],zone))

    def pick(self,g,key):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(key,)))

    def attack(self,g,cid,player=1):
        source=self.eid(g,cid,player);g.apply(Attack(player,source,g.state.players[3-player].hero_id));return source

    def portable(self,g,mode='normal'):
        saved=json.loads(json.dumps(g.snapshot()));r=fixture(mode,'reader')
        self.assertIsNot(r,g.registry);other=Game.from_snapshot(saved,r)
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),r).snapshot(),saved)
        for p in (1,2):
            text=json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for key in ('rng_state','resolution_frame','condition_id','accepted_card_id'):
                self.assertNotIn('"'+key+'"',text)
        return other

    def test_a_four_full_rows_eight_faces_original_bridges_and_exact_self_reconstruction(self):
        d=cards.load_batch();r=fixture();rows={x['record']['id']:x for x in d['existing_dependencies']}
        self.assertEqual(len(rows),4);self.assertEqual(len(d['official_observations']),8)
        for o in d['official_observations']:
            self.assertEqual(sha(o['response_file']),o['response_sha256'])
            check_face(rows[o['card_id']]['record'],o['face'],o['locale'],d['display_normalizations'].get(o['card_id']))
        for cid,row in rows.items():
            old=r.card(cid);new=r.card(AssembleRecipe(cid,cid,'bottom').card_id)
            self.assertEqual(canonical_digest(asdict(old)),row['definition_sha256'])
            self.assertEqual((new.cost,new.attack,new.health,new.metadata,new.keywords),
                (old.cost,old.attack,old.health,old.metadata,old.keywords))
            self.assertEqual(r.assemble_reaction_sources[cid].original_behavior_id,old.triggers[0].behavior_id)

    def test_b_pandaren_original_and_self_give_both_once_and_exclude_own_generated_entries(self):
        for cid in (PANDA,AssembleRecipe(PANDA,PANDA,'bottom').card_id):
            g=self.game((ADD,),(cid,));source=self.eid(g,cid);self.play(g,ADD)
            self.assertEqual(self.count(g,SPELL),1);self.assertEqual(self.count(g,SPELL,2),1)
            entries=[from_event(g.state,e)for e in g.events if e.kind=='hand_card_entered']
            self.assertEqual([r.player_id for r in entries if r.source_id==source],[1,2])

    def test_c_second_player_pandaren_keeps_owner_first_delivery_order(self):
        cid=AssembleRecipe(PANDA,PANDA,'bottom').card_id
        g=self.game(enemy=(cid,),enemy_hand=(ADD,),active=2);source=self.eid(g,cid,2);self.play(g,ADD)
        entries=[from_event(g.state,e)for e in g.events if e.kind=='hand_card_entered']
        self.assertEqual([r.player_id for r in entries if r.source_id==source],[2,1])

    def test_d_full_owner_hand_does_not_suppress_requested_opponent_delivery(self):
        cid=AssembleRecipe(PANDA,PANDA,'bottom').card_id
        g=self.game((ADD,),(cid,),cap=1);self.play(g,ADD)
        self.assertEqual(self.count(g,HELD),1);self.assertEqual(self.count(g,SPELL),0)
        self.assertEqual(self.count(g,SPELL,2),1)

    def test_e_missing_or_unknown_eligible_spell_domain_rolls_back_entire_external_entry(self):
        for mode in ('no_pool','unknown'):
            cid=AssembleRecipe(PANDA,PANDA,'bottom').card_id
            g=self.game((ADD,),(cid,),mode=mode);saved=g.snapshot()
            with self.assertRaisesRegex(ResolutionError,'pool|domain|unsupported|unimplemented'):self.play(g,ADD)
            self.assertEqual(g.snapshot(),saved)

    def test_f_shaw_original_and_self_attack_discount_one_original_hand_card(self):
        for cid in (SHAW,AssembleRecipe(SHAW,SHAW,'bottom').card_id):
            g=self.game((HELD,),(cid,));held=self.eid(g,HELD,zone='hand')
            self.assertEqual(g.quote_cost(held).amount,5);self.attack(g,cid)
            self.assertEqual(g.quote_cost(held).amount,2)
            mana=g.state.players[1].mana;self.play(g,HELD);self.assertEqual(g.state.players[1].mana,mana-2)

    def test_g_shaw_other_friendly_stealth_counts_but_nonattack_loss_and_enemy_do_not(self):
        cid=AssembleRecipe(SHAW,SHAW,'bottom').card_id
        g=self.game((HELD,),(cid,STEALTHY));held=self.eid(g,HELD,zone='hand');self.attack(g,STEALTHY)
        self.assertEqual(g.quote_cost(held).amount,2)
        g=self.game((HELD,MUTE),(cid,STEALTHY));held=self.eid(g,HELD,zone='hand')
        self.play(g,MUTE,self.eid(g,STEALTHY));self.assertEqual(g.quote_cost(held).amount,5)
        g=self.game((HELD,),(cid,),enemy=(STEALTHY,));held=self.eid(g,HELD,zone='hand')
        g.apply(EndTurn(1));self.attack(g,STEALTHY,2);g.apply(EndTurn(2))
        self.assertEqual(g.quote_cost(held).amount,5)

    def test_h_shaw_independent_battlecry_reduces_hand_without_an_attack_event(self):
        cid=AssembleRecipe(CURATOR,SHAW,'bottom').card_id
        g=self.game((cid,HELD));held=self.eid(g,HELD,zone='hand');self.play(g,cid)
        self.assertEqual(g.quote_cost(held).amount,2)
        self.assertFalse(any(e.kind=='attack_declared'for e in g.events))

    def test_i_webweaver_original_and_self_use_frozen_identity_before_new_battlecry(self):
        for cid in (WEB,AssembleRecipe(WEB,WEB,'bottom').card_id):
            g=self.game((N,PROBE),(cid,));self.play(g,N);self.assertEqual(len(g.state.draw_history),0)
            self.play(g,PROBE);self.assertEqual(len(g.state.draw_history),1)
            self.assertTrue(any(row.played_face.card_id==PROBE for row in played_cards(g.state,1,completed=True)))

    def test_j_webweaver_does_not_count_first_identity_or_spells_as_repeat_minions(self):
        cid=AssembleRecipe(WEB,WEB,'bottom').card_id
        g=self.game((N,N,NOOP),(cid,));self.play(g,NOOP);self.play(g,N)
        self.assertEqual(len(g.state.draw_history),0);self.play(g,N);self.assertEqual(len(g.state.draw_history),1)

    def test_k_fragment_original_and_self_read_accepted_minion_target_even_after_death(self):
        for cid in (FRAGMENT,AssembleRecipe(FRAGMENT,FRAGMENT,'bottom').card_id):
            g=self.game((SLAY,PING,NOOP),(cid,),enemy=(N,));target=self.eid(g,N,2)
            self.play(g,SLAY,target);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
            self.assertEqual(len(g.state.draw_history),1)
            self.play(g,PING,g.state.players[2].hero_id);self.play(g,NOOP)
            self.assertEqual(len(g.state.draw_history),1)

    def test_l_fragment_opponent_spell_or_removed_source_does_not_reward(self):
        cid=AssembleRecipe(FRAGMENT,FRAGMENT,'bottom').card_id
        g=self.game(board=(cid,N),enemy_hand=(PING,));g.apply(EndTurn(1));self.play(g,PING,self.eid(g,N))
        self.assertEqual(len([r for r in g.state.draw_history if r.player_id==1]),0)
        g=self.game((SLAY,),(cid,));source=self.eid(g,cid);self.play(g,SLAY,source)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.draw_history),0)

    def test_m_borrowed_pandaren_and_shaw_prefixes_omit_their_original_subject(self):
        cid=AssembleRecipe(PANDA,SHAW,'bottom').card_id
        g=self.game((ADD,),(cid,));self.play(g,ADD);held=self.eid(g,HELD,zone='hand')
        self.assertEqual(g.quote_cost(held).amount,2);self.assertEqual(self.count(g,SPELL,2),0)
        cid=AssembleRecipe(SHAW,PANDA,'bottom').card_id
        g=self.game((HELD,),(cid,));held=self.eid(g,HELD,zone='hand');self.attack(g,cid)
        self.assertEqual(g.quote_cost(held).amount,5);self.assertEqual(self.count(g,SPELL),1)
        self.assertEqual(self.count(g,SPELL,2),1)

    def test_n_three_independent_subjects_work_in_battlecry_and_after_natural_death(self):
        for prefix in (CURATOR,LOOT):
            for suffix in (PANDA,SHAW,WEB):
                cid=AssembleRecipe(prefix,suffix,'bottom').card_id
                g=self.game((cid,HELD,KILL)if prefix==LOOT else (cid,HELD))
                held=self.eid(g,HELD,zone='hand');source=self.play(g,cid)
                if prefix==LOOT:self.play(g,KILL,source);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
                if suffix==PANDA:self.assertEqual(self.count(g,SPELL),1);self.assertEqual(self.count(g,SPELL,2),1)
                elif suffix==SHAW:
                    # The kill driver has already left the hand before the death subject.
                    self.assertEqual(g.quote_cost(held).amount,2)
                else:self.assertEqual(len(g.state.draw_history),1)

    def test_o_two_player_generation_wait_restores_clones_replays_and_preserves_original_tail(self):
        cid=AssembleRecipe(PANDA,PANDA,'bottom').card_id
        g=self.game((ADD,),(cid,WATCH));self.play(g,ADD)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.count(g,SPELL,2),0)
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K430 deliberate'):self.pick(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        self.pick(g,'go');self.pick(other,'go');self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(self.count(g,SPELL),1);self.assertEqual(self.count(g,SPELL,2),1)

    def test_p_missing_or_forged_original_entry_attack_play_and_cast_events_are_rejected(self):
        g=self.game((PING,),(FRAGMENT,),enemy=(N,));source=self.eid(g,FRAGMENT)
        for key in ('external_own_hand_entry','friendly_stealth_attack','repeated_committed_minion','own_minion_target_spell'):
            with self.assertRaises((ValueError,ResolutionError)):
                g.registry.trigger_condition(cards.PREFIX+key)(RuleContext(g.state,source,1))
        self.play(g,PING,self.eid(g,N,2));event=next(e for e in g.events if e.kind=='spell_cast_finished')
        with self.assertRaises(ResolutionError):
            g.registry.trigger_condition(cards.PREFIX+'own_minion_target_spell')(RuleContext(g.state,source,1,event=replace(event,source_id=source)))

    def test_q_complete_original_query_and_shaw_continuation_preflight_before_partial_installation(self):
        with patch('hs_sim.cards.assemble_entry_commit_target_followups.register_assemble_entry_commit_target_followups',lambda r:None):r=build_registry()
        old=r._cards[PANDA];r._cards[PANDA]=replace(old,health=old.health+1)
        with self.assertRaises(TargetValidationError):cards.register_assemble_entry_commit_target_followups(r)
        self.assertFalse(any(cid in r.assemble_templates for cid in cards.SOURCES));r._cards[PANDA]=old
        with patch.object(cards.native_panda,'QUERY',replace(cards.native_panda.QUERY,collectible=False)):
            with self.assertRaisesRegex(TargetValidationError,'spell domain'):cards.register_assemble_entry_commit_target_followups(r)
        callback=r._behaviors.pop(cards.SHAW_CALLBACK)
        with self.assertRaises(ValueError):cards.register_assemble_entry_commit_target_followups(r)
        r._behaviors[cards.SHAW_CALLBACK]=callback

    def test_r_real_rogue_offer_replaces_low_neutral_prefix_with_prepare_and_spell_start(self):
        cid=AssembleRecipe(PANDA,AUCTIONEER,'top').card_id
        g=self.game((MISMATCH,NOOP),mode='assemble');self.play(g,MISMATCH)
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(next(o.id for o in c.options if o.card_id==cid),)))
        held=self.eid(g,cid,zone='hand');self.assertEqual(g.quote_hand_action(held,'prepare').amount,1)
        mana=g.state.players[1].mana;self.play(g,cid);self.assertEqual(g.state.players[1].mana,mana-2)
        self.play(g,NOOP);self.assertEqual(self.count(g,SPELL),1);self.assertEqual(self.count(g,SPELL,2),1)
