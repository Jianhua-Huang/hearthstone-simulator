"""Kong Zo keeps one original spell discovery through its destination decision."""
from dataclasses import replace
from functools import lru_cache
import json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.discovered_spell_destination_card import CARD,load_batch
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,
    PlayerSetup,PlayCard,Rarity,Scenario,SelectChoice,SnapshotError,Zone)
from hs_sim.engine.effects import AddToHand,ChangeControl,ChoiceOption,Destroy,Draw,GainArmor,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.battlecry_sources import RepeatBattlecry
from hs_sim.engine.hand_capacity import SetHandCapacity
from hs_sim.engine.model import ChoicePurpose,LimitedTriggerSpec
from hs_sim.engine.pools import DiscoverFromPool,GenerateFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.discovery_destinations import MODE,OPTIONS,QUERY
from hs_sim.engine.discovery_delivery import COMPLETED
from hs_sim.engine.card_discoveries import discovered_cards
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest

P='kong.zo.test.';FILL,SPELL,OTHER,THIRD,FOREIGN,WATCH,UNKNOWN=(P+x for x in (
    'fill','spell','other','third','foreign','watch','unknown'))
CTX=GenerationContext('kong-zo-explicit-experiment','experimental');POOL='constructed.cards'
MEMBERS=(SPELL,OTHER,THIRD,FOREIGN)
CAP=P+'cap';REPEAT=P+'repeat'


@lru_cache(maxsize=None)
def registry(mode,members,role):
    assert role in ('writer','reader')
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON)
    r.register_card(CardDefinition(FILL,FILL,CardType.MINION,health=30,metadata=meta))
    r.register_behavior(P+'noop',lambda c:())
    r.register_behavior(CAP,lambda c:(SetHandCapacity(c.player_id,1),))
    r.register_card(CardDefinition(CAP,CAP,CardType.SPELL,on_play=CAP,metadata=meta))
    def repeat(c):
        original=next(x for x in c.state.battlecry_history if x.card_id==CARD and x.origin=='hand')
        return (RepeatBattlecry(c.player_id,c.source_id,original.id),)
    r.register_behavior(REPEAT,repeat);r.register_card(CardDefinition(REPEAT,REPEAT,CardType.MINION,health=3,battlecry=REPEAT,metadata=meta))
    for cid,klass in ((SPELL,CardClass.MAGE),(OTHER,CardClass.MAGE),(THIRD,CardClass.MAGE),(FOREIGN,CardClass.WARRIOR)):
        card=CardDefinition(cid,cid,CardType.SPELL,cost=4,on_play=P+'noop',metadata=replace(meta,collectible=True,classes=(klass,)))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    if UNKNOWN in members:r.register_pool_card(PoolCard(UNKNOWN,CardType.SPELL,4,replace(meta,collectible=True,classes=(CardClass.MAGE,))))
    if mode:
        def fail(c):raise ResolutionError('Kong Zo deliberate post-creation failure')
        r.register_behavior(P+'fail',fail)
        event='choice_selected'if mode in ('kill','take')else'card_created'if mode=='created'else COMPLETED
        def eligible(c):
            return c.event.source_id in c.state.entities and c.state.entities[c.event.source_id].card_id==CARD
        def watch(c):
            if mode=='kill':return (Destroy(c.event.source_id),)
            if mode=='take':return (ChangeControl(c.event.source_id,2),)
            return (RequestChoice(1,(ChoiceOption('ok','Continue'),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(P+'watch',watch);r.register_trigger_condition(P+'eligible',eligible)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,metadata=meta,
            limited_triggers=(LimitedTriggerSpec(event,P+'watch',condition_id=P+'eligible'),)))
    r.register_pool(PoolDefinition(POOL,'kong-zo-explicit-v1',CTX.target_id,CTX.mode,tuple(PoolMember(c)for c in members),complete=True))
    r.validate();r.freeze();return r


class DiscoveredSpellDestinationTests(unittest.TestCase):
    def game(self,members=MEMBERS,mode=None,hand=(CARD,),pid=1):
        self.config=(mode,members)
        self.pid=pid
        players=tuple(PlayerSetup('HERO_08',hand=hand if p==pid else(),board=(WATCH,)if mode and p==1 else(),
            deck=(FILL,)*8,mana=50,max_mana=50,mana_cap=50)for p in (1,2))
        g=Game.from_scenario(Scenario(players,seed=224517,generation_context=CTX),registry(mode,members,'writer'))
        if pid==2:g.apply(EndTurn(1))
        return g
    def play(self,g,cid=CARD):
        eid=next(i for i in g.state.players[self.pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(self.pid,eid,position=0 if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def first(self,g):
        q=g.state.pending_choice;o=q.options[0];self.choose(g,o.id);return o.card_id
    def portable(self,g):
        r=registry(*self.config,'reader');self.assertIsNot(r,g.registry)
        self.assertEqual(r.fingerprint(),g.registry.fingerprint());s=json.loads(json.dumps(g.snapshot()))
        other=Game.from_snapshot(s,r);self.assertEqual(other.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),r).snapshot(),s)
        for pid in (1,2):
            public=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for key in ('resolution_frame','rng_state','source_allocation','behavior_id'):
                self.assertNotIn('"'+key+'"',public)
        return other
    def test_a00_real_paid_discovery_then_keep_same_selected_spell(self):
        g=self.game();self.play(g);self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.POOL_DISCOVERY)
        self.portable(g);selected=self.first(g)
        self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.EFFECT);self.assertFalse(g.state.players[1].hand)
        self.assertEqual(tuple(o.id for o in g.state.pending_choice.options),OPTIONS);self.portable(g)
        self.choose(g,OPTIONS[0]);self.assertEqual(g.state.entities[g.state.players[1].hand[-1]].card_id,selected)
        self.assertEqual(g.state.players[1].mana,47);self.assertEqual(len(g.state.card_discovery_history),1);self.portable(g)
    def test_a01_original_selection_goes_to_opponent_top_without_entering_own_hand(self):
        g=self.game();self.play(g);selected=self.first(g);old=list(g.state.players[2].deck);self.choose(g,OPTIONS[1])
        self.assertFalse(g.state.players[1].hand);self.assertEqual(g.state.players[2].deck[1:],old)
        eid=g.state.players[2].deck[0];self.assertEqual((g.state.entities[eid].card_id,g.state.entities[eid].owner),(selected,2))
        self.assertEqual(len(g.state.card_discovery_history),1);self.portable(g)
    def test_a02_complete_three_original_faces_preserve_printed_option_cost_without_playability(self):
        d=load_batch();r=registry(None,MEMBERS,'writer');self.assertEqual(len(d['official_observations']),6)
        for row in d['cards']+d['dependencies']:
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
            self.assertEqual(r.card(row['record']['id']).cost,row['record']['cost'])
        self.assertEqual((r.card(CARD).cost,r.card(CARD).attack,r.card(CARD).health),(3,3,4))
        for cid in OPTIONS:
            self.assertTrue(r.card(cid).choice_only);self.assertFalse(r.card(cid).hand_playable)
            with self.assertRaises((ResolutionError,ValueError)):
                Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(cid,)),PlayerSetup('HERO_08'))),r)
    def test_a03_discovery_uses_current_class_complete_candidates_and_destination_has_no_rng(self):
        g=self.game();self.play(g);offered=tuple(o.card_id for o in g.state.pending_choice.options)
        self.assertEqual(set(offered),{SPELL,OTHER,THIRD});self.assertNotIn(FOREIGN,offered)
        selected=self.first(g);rng=g._rng.getstate();self.choose(g,OPTIONS[1])
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.entities[g.state.players[2].deck[0]].card_id,selected);self.portable(g)
    def test_a04_opponent_top_is_the_next_actual_opponent_draw(self):
        g=self.game();self.play(g);selected=self.first(g);self.choose(g,OPTIONS[1]);original=g.state.players[2].deck[0]
        g.apply(EndTurn(1));self.assertEqual((g.state.draw_history[-1].entity_id,g.state.draw_history[-1].card_id),(original,selected));self.portable(g)
    def test_b00_destination_wait_independent_restore_and_same_branch_resume(self):
        g=self.game();self.play(g);self.first(g);other=self.portable(g)
        for game in (g,other):self.choose(game,OPTIONS[1])
        self.assertEqual(g.snapshot(),other.snapshot());self.portable(g)
    def test_b01_post_creation_wait_has_one_actual_recipient_and_late_failure_rolls_back(self):
        g=self.game(mode='created');self.play(g);selected=self.first(g);self.choose(g,OPTIONS[0])
        self.assertEqual(g.state.entities[g.state.players[1].hand[-1]].card_id,selected)
        self.assertFalse(any(e.kind==COMPLETED for e in g.events));other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved)
        for game in (g,other):self.choose(game,'ok')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(sum(e.kind==COMPLETED for e in g.events),1);self.portable(g)
    def test_b02_discovery_completion_observer_fires_once_after_final_deck_delivery(self):
        g=self.game(mode='completion');self.play(g);selected=self.first(g);self.choose(g,OPTIONS[1])
        self.assertEqual(g.state.entities[g.state.players[2].deck[0]].card_id,selected)
        self.assertEqual(sum(e.kind==COMPLETED for e in g.events),1);self.portable(g);self.choose(g,'ok');self.portable(g)
    def test_c00_source_death_before_original_selection_executes_keeps_accepted_discoverer(self):
        g=self.game(mode='kill');source=self.play(g);selected=self.first(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(g.state.pending_choice.player_id,1)
        self.choose(g,OPTIONS[0]);self.assertEqual(g.state.entities[g.state.players[1].hand[-1]].card_id,selected);self.portable(g)
    def test_c01_source_control_change_does_not_move_destination_decision_to_new_controller(self):
        g=self.game(mode='take');source=self.play(g);selected=self.first(g)
        self.assertEqual(g.state.entities[source].controller,2);self.assertEqual(g.state.pending_choice.player_id,1)
        self.choose(g,OPTIONS[0]);self.assertEqual(g.state.entities[g.state.players[1].hand[-1]].card_id,selected)
        self.assertEqual(len(discovered_cards(g.state,1)),1);self.assertFalse(discovered_cards(g.state,2));self.portable(g)
    def test_c02_historical_battlecry_automatically_selects_both_menus_once(self):
        g=self.game(hand=(CARD,REPEAT));self.play(g);self.first(g);self.choose(g,OPTIONS[0]);self.play(g,REPEAT)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(g.state.card_discovery_history),2)
        self.assertEqual(sum(e.kind==COMPLETED for e in g.events),2);self.portable(g)
    def test_c03_full_hand_keep_burns_but_opponent_top_never_enters_own_hand(self):
        for keep in (True,False):
            with self.subTest(keep=keep):
                g=self.game(hand=(CAP,CARD,FILL));self.play(g,CAP);self.play(g);selected=self.first(g)
                self.choose(g,OPTIONS[0 if keep else 1]);self.assertEqual(len(g.state.players[1].hand),1)
                if not keep:self.assertEqual(g.state.entities[g.state.players[2].deck[0]].card_id,selected)
                else:self.assertTrue(any(e.card_id==selected and e.zone==Zone.GRAVEYARD for e in g.state.entities.values()))
                self.assertEqual(len(g.state.card_discovery_history),1);self.portable(g)
    def test_d00_unknown_eligible_spell_rejects_paid_play_without_pruning(self):
        g=self.game(members=(SPELL,UNKNOWN));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),saved);self.portable(g)
    def test_d01_empty_current_class_pool_has_no_discovery_choice_or_rng(self):
        g=self.game(members=(FOREIGN,));rng=g._rng.getstate();self.play(g)
        self.assertIsNone(g.state.pending_choice);self.assertFalse(g.state.card_discovery_history)
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.players[1].mana,47);self.portable(g)
    def test_d02_other_seat_puts_selected_spell_on_original_opponents_deck(self):
        g=self.game(pid=2);self.play(g);selected=self.first(g);self.choose(g,OPTIONS[1])
        self.assertEqual(g.state.entities[g.state.players[1].deck[0]].card_id,selected)
        self.assertEqual(g.state.players[2].mana,47);self.assertEqual(len(discovered_cards(g.state,2)),1);self.assertFalse(discovered_cards(g.state,1));self.portable(g)
    def test_d03_unselected_and_selected_discovery_information_is_private_before_delivery(self):
        g=self.game();self.play(g)
        for stage in ('offer','destination'):
            public=json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2))
            for cid in (SPELL,OTHER,THIRD):self.assertNotIn(cid,public)
            if stage=='offer':self.first(g)
        self.portable(g)
    def test_d04_limited_destination_rejects_generation_minions_repetition_and_other_materials(self):
        from hs_sim.engine.model import CostSpec
        good=DiscoverFromPool(1,POOL,QUERY,source_id=1,destination=MODE)
        for changes in (dict(count=2),dict(discoveries=2),dict(cost=CostSpec(delta=-1)),
                dict(query=PoolQuery(kinds=(CardType.MINION,),collectible=True,class_mode='current')),dict(position='top')):
            with self.assertRaises(ValueError):replace(good,**changes)
        with self.assertRaises(ValueError):GenerateFromPool(1,POOL,QUERY,source_id=1,destination=MODE)
    def test_d05_rehashed_changed_destination_branch_cannot_restore(self):
        g=self.game();self.play(g);self.first(g);saved=json.loads(json.dumps(g.snapshot()))
        def rehash(s):
            s['events_hash']=canonical_hash(s['events'])
            s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')})
            return s
        def rewrite(value):
            if isinstance(value,dict):
                if value.get('type')=='hs_sim.engine.discovery_destinations.DeliverDiscoveredSpell':value['fields']['keep']=False
                else:
                    for child in value.values():rewrite(child)
            elif isinstance(value,list):
                for child in value:rewrite(child)
        rewrite(saved)
        with self.assertRaises((SnapshotError,ValueError)):Game.from_snapshot(rehash(saved),registry(*self.config,'reader'))
