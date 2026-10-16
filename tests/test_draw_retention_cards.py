"""Six native draw consumers and the shared finite hand-play gate."""
from dataclasses import replace
import json,unittest
from hs_sim.cards.draw_retention_cards import load_batch
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,
    SelectChoice,SnapshotError,TargetMode,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.copy_materials import CapturedCardCopyMaterial
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import AddToHand,ChoiceOption,Draw,GainArmor,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.hand_play_locks import LockHandCard,play_error
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CostSpec,Enchantment,HandPlayLock
from hs_sim.engine.physical_draw_groups import DrawGroupArrival,DrawGroupReward,DrawGroupSlot
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.resolver import PlayFromHand
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference,CopyCard,ModifyStoredCost,MoveCard
from hs_sim.targets import canonical_digest
from test_physical_draw_cards import registry as base_registry,ONE,TWO,THREE,FOUR,PLAIN,FIRE

GODS='BE_EVENT_100';TITANS='BE_EVENT_101';BOUNTY='EDR_234';MIMIC='EDR_522';LADDER='TIME_031';DIVINE='EDR_804'
ROOTS=(GODS,TITANS,BOUNTY,MIMIC,LADDER,DIVINE);WISP='EDR_851t'


def registry():
    r=base_registry()
    r.register_behavior('k45.fail',lambda c:(AddToHand(c.player_id,'unknown.k45'),))
    def watch(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id not in ROOTS or c.state.entities[c.state.players[c.player_id].hero_id].armor:return ()
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('bad','Fail',(InvokeBehavior('k45.fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior('k45.watch',watch)
    r.register_card(CardDefinition('k45.watch','Draw wait fixture',CardType.MINION,health=8,
        triggers=(TriggerSpec('card_drawn','k45.watch'),)))
    def copy_locked(c,mode):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if any(x.hand_play_lock is not None for x in c.state.entities[i].enchantments))
        return (CopyCard(CardReference.capture(e),c.player_id,Zone.HAND,mode=mode,source_id=c.source_id),)
    def reprice(c):
        e=c.state.entities[c.state.players[2].deck[0]]
        return (BuffStoredCard(CardReference.capture(e),attack=3,health=4,source_id=c.source_id,cost=CostSpec(delta=-1)),)
    def reset(c):
        e=next(c.state.entities[i]for i in c.state.players[1].hand if any(x.hand_play_lock is not None for x in c.state.entities[i].enchantments))
        return (MoveCard(CardReference.capture(e),1,Zone.DECK,'top',reset=True,source_id=c.source_id),Draw(1,1,c.source_id))
    bodies=dict(copy=lambda c:copy_locked(c,'current'),base=lambda c:copy_locked(c,'base'),reprice=reprice,reset=reset,
        auto=lambda c:(CastSpell(c.player_id,FIRE,c.source_id),),
        bypass=lambda c:(PlayFromHand(PlayCard(c.player_id,next(i for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==FIRE))),),
        badlock=lambda c:(LockHandCard(CardReference(c.source_id,1,Zone.HAND,c.source.card_id,999999),2,c.source_id),))
    for name,body in bodies.items():
        r.register_behavior('k45.'+name,body)
        r.register_card(CardDefinition('k45.'+name,name,CardType.SPELL,on_play='k45.'+name))
    r.register_card(CardDefinition('k45.autominion','Auto spell minion',CardType.MINION,health=2,battlecry='k45.auto'))
    r.register_card(CardDefinition('k45.fake_wisp','小精灵',CardType.MINION,health=1))
    return r


class DrawRetentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand,*,deck=(ONE,TWO,THREE,FOUR),board=(),enemy_hand=(),enemy_board=(),enemy_deck=(THREE,FOUR,PLAIN,ONE),mana=20):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,deck=deck,board=board,mana=mana,max_mana=20,mana_cap=20),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy_board,deck=enemy_deck,mana=20,max_mana=20,mana_cap=20)),seed=945),self.r)
    def eid(self,g,cid,p=1,zone='hand'):
        s=g.state;return next(i for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid)
    def play(self,g,cid,target=None,p=1):
        s=g.state;eid=self.eid(g,cid,p);g.apply(PlayCard(p,eid,target,position=len(s.players[p].board)if s.entities[eid].kind==CardType.MINION else None));return eid
    def hand(self,g,p=1):
        s=g.state;return [s.entities[i]for i in s.players[p].hand]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return other
    def price(self,g,eid):
        s=g.state;return quote_unselected_cost(s,g.registry,s.entities[eid]).amount
    def locked(self,g,eid):
        s=g.state;return play_error(s,s.entities[eid])is not None

    def test_six_complete_raw_faces_and_seven_named_wisp_evidence_rows(self):
        data=load_batch();self.assertEqual({r['record']['id']for r in data['cards']},set(ROOTS))
        for row in data['cards']:
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
            self.assertEqual(self.r.card(row['record']['id']).cost,row['record']['cost'])
        self.assertEqual(len(data['named_target_evidence']),7)
        self.assertEqual(sum(r['registered_definition_present']for r in data['named_target_evidence']),2)

    def test_gods_tutors_only_minions_refreshes_five_then_blocks_other_types(self):
        g=self.game((GODS,FIRE,PLAIN),deck=(FIRE,ONE,TWO,FIRE),mana=8);source=self.play(g,GODS);s=g.state
        self.assertEqual(s.players[1].mana,8);self.assertEqual({d.card_id for d in s.draw_history},{ONE,TWO})
        self.assertTrue(all(d.source_id==source for d in s.draw_history))
        before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,FIRE)
        self.assertEqual(g.snapshot(),before);self.play(g,ONE)

    def test_titans_tutors_spells_and_only_spells_can_be_played(self):
        g=self.game((TITANS,ONE),deck=(ONE,FIRE,FIRE,TWO),mana=9);self.play(g,TITANS)
        self.assertEqual(g.state.players[1].mana,9);self.assertEqual([d.card_id for d in g.state.draw_history],[FIRE,FIRE])
        with self.assertRaises(IllegalAction):self.play(g,ONE)
        self.play(g,FIRE)

    def test_arrival_empty_match_skips_fatigue_but_refresh_and_rule_still_apply(self):
        g=self.game((GODS,FIRE),deck=(),mana=5);before=g._rng.getstate();self.play(g,GODS)
        self.assertEqual(g.state.players[1].mana,5);self.assertFalse(g.state.draw_history);self.assertEqual(g._rng.getstate(),before)
        with self.assertRaises(IllegalAction):self.play(g,FIRE)

    def test_arrival_expiry_restores_permissions_and_does_not_gate_automatic_casts(self):
        g=self.game((GODS,'k45.autominion',FIRE));self.play(g,GODS);self.play(g,'k45.autominion')
        self.assertTrue(any(c.card_id==FIRE and c.origin=='effect'for c in g.state.cast_history))
        g.apply(EndTurn(1));self.assertFalse(g.state.players[1].player_effects);g.apply(EndTurn(2));self.play(g,FIRE)

    def test_arrival_draw_wait_does_not_install_rule_or_refresh_early(self):
        g=self.game((GODS,),board=('k45.watch',),mana=8);self.play(g,GODS)
        self.assertEqual(g.state.players[1].mana,3);self.assertFalse(g.state.players[1].player_effects)
        saved=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for h in (g,other):self.choose(h)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.players[1].mana,8)

    def test_bounty_locks_exact_draws_at_unchanged_prices_before_payment(self):
        g=self.game((BOUNTY,PLAIN),deck=(ONE,TWO));source=self.play(g,BOUNTY);ids=[d.entity_id for d in g.state.draw_history]
        self.assertEqual([self.price(g,i)for i in ids],[1,2]);self.assertTrue(all(self.locked(g,i)for i in ids))
        self.assertFalse(self.locked(g,self.eid(g,PLAIN)));before=g.snapshot();mana=g.state.players[1].mana
        with self.assertRaises(IllegalAction):g.apply(PlayCard(1,ids[0],position=0))
        self.assertEqual(g.snapshot(),before);self.assertEqual(g.state.players[1].mana,mana)
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.portable(g)

    def test_bounty_unlocks_on_second_subsequent_genuine_owner_start(self):
        g=self.game((BOUNTY,),deck=(ONE,TWO,THREE,FOUR,PLAIN));self.play(g,BOUNTY);eid=self.eid(g,ONE)
        for p in (1,2):g.apply(EndTurn(p))
        self.assertTrue(self.locked(g,eid));g.apply(EndTurn(1));self.assertTrue(self.locked(g,eid));g.apply(EndTurn(2))
        self.assertFalse(self.locked(g,eid));g.apply(PlayCard(1,eid,position=0));self.portable(g)

    def test_zero_cost_locked_spell_and_internal_manual_entry_cannot_bypass_gate(self):
        g=self.game((BOUNTY,'k45.bypass'),deck=(FIRE,ONE));self.play(g,BOUNTY);eid=self.eid(g,FIRE)
        self.assertEqual(self.price(g,eid),0);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,FIRE)
        self.assertEqual(g.snapshot(),before)
        with self.assertRaises(ResolutionError):self.play(g,'k45.bypass')
        self.assertEqual(g.snapshot(),before)

    def test_bounty_wait_restores_exact_group_and_failed_choice_rolls_back(self):
        g=self.game((BOUNTY,),board=('k45.watch',));self.play(g,BOUNTY);saved=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for h in (g,other):self.choose(h)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertTrue(all(self.locked(g,e.id)for e in self.hand(g)))

    def test_bounty_burn_and_fatigue_have_no_lock_beneficiary(self):
        g=self.game((BOUNTY,)+(PLAIN,)*9,deck=(ONE,TWO));self.play(g,BOUNTY)
        self.assertEqual([d.outcome for d in g.state.draw_history],['hand','burned'])
        self.assertEqual(sum(self.locked(g,e.id)for e in self.hand(g)),1)
        g=self.game((BOUNTY,),deck=());self.play(g,BOUNTY);self.assertFalse(self.hand(g))
        self.assertEqual([d.outcome for d in g.state.draw_history],['fatigue','fatigue'])

    def test_bounty_replacement_chain_locks_hand_leaves_not_cast_portal(self):
        g=self.game((BOUNTY,),deck=('k44.portal',ONE,TWO));self.play(g,BOUNTY)
        self.assertEqual([e.card_id for e in self.hand(g)],[ONE,TWO]);self.assertTrue(all(self.locked(g,e.id)for e in self.hand(g)))
        self.assertEqual([d.outcome for d in g.state.draw_history],['cast','hand','hand']);self.portable(g)

    def test_current_copy_inherits_lock_clock_but_printed_copy_does_not(self):
        for spell,expected in (('k45.copy',True),('k45.base',False)):
            g=self.game((BOUNTY,spell),deck=(ONE,TWO));self.play(g,BOUNTY);old={e.id for e in self.hand(g)};self.play(g,spell)
            copies=[e for e in self.hand(g)if e.id not in old];self.assertEqual(len(copies),1)
            self.assertEqual(self.locked(g,copies[0].id),expected);self.portable(g)

    def test_reset_to_definition_removes_lock_and_reentry_does_not_reinstall(self):
        g=self.game((BOUNTY,'k45.reset'),deck=(ONE,TWO));self.play(g,BOUNTY);eid=self.eid(g,ONE);self.play(g,'k45.reset')
        self.assertIn(eid,g.state.players[1].hand);self.assertFalse(self.locked(g,eid));g.apply(PlayCard(1,eid,position=0))

    def test_forged_lock_deadline_and_missing_schema_field_are_rejected(self):
        g=self.game((BOUNTY,),deck=(ONE,TWO));self.play(g,BOUNTY);saved=g.snapshot();eid=self.eid(g,ONE)
        altered=json.loads(json.dumps(saved));row=altered['state']['entities'][str(eid)]['enchantments'][0]
        row['hand_play_lock']['deadline']['owner_turn_index']+=1;altered['state_hash']=canonical_hash(altered['state'])
        with self.assertRaises(SnapshotError):Game.from_snapshot(altered,registry())
        altered=json.loads(json.dumps(saved));altered['state']['entities'][str(eid)]['enchantments'][0].pop('hand_play_lock');altered['state_hash']=canonical_hash(altered['state'])
        with self.assertRaises(SnapshotError):Game.from_snapshot(altered,registry())

    def test_lock_requires_typed_pure_gate_and_original_hand_reference(self):
        with self.assertRaises(ValueError):LockHandCard(CardReference(1,1,Zone.DECK,ONE,0),2,1)
        with self.assertRaises(ValueError):DrawGroupReward('lock_all',0)
        with self.assertRaises(ValueError):Enchantment(1,label='hand_play_lock')
        g=self.game((BOUNTY,),deck=(ONE,TWO));self.play(g,BOUNTY);s=g.state;lock=s.entities[self.eid(g,ONE)].enchantments[0].hand_play_lock
        with self.assertRaises(ValueError):Enchantment(99,source_id=s.players[1].hero_id,label='hand_play_lock',hand_play_lock=lock,cost=1)

    def test_mimicry_copies_original_physical_draws_without_redrawing(self):
        g=self.game((MIMIC,),enemy_deck=(THREE,FOUR));original=g.state.players[2].deck[:];source=self.play(g,MIMIC);s=g.state
        self.assertEqual(s.players[2].hand,original);copies=self.hand(g)
        self.assertEqual([e.card_id for e in copies],[THREE,FOUR]);self.assertEqual([e.origin_entity_id for e in copies],original)
        self.assertTrue(all(e.owner==e.controller==1 for e in copies));self.assertEqual([d.source_id for d in s.draw_history],[source,source])
        self.assertEqual(len(s.draw_history),2);self.portable(g)

    def test_mimicry_captures_current_local_stats_and_cost_before_actual_draw(self):
        g=self.game(('k45.reprice',MIMIC),enemy_deck=(THREE,FOUR));self.play(g,'k45.reprice');self.play(g,MIMIC)
        first=self.hand(g)[0];self.assertEqual((first.attack,first.max_health),(6,8));self.assertEqual(self.price(g,first.id),2)

    def test_mimicry_opponent_burns_still_produce_original_draw_copies(self):
        g=self.game((MIMIC,),enemy_hand=(PLAIN,)*10,enemy_deck=(THREE,FOUR));self.play(g,MIMIC)
        self.assertEqual([d.outcome for d in g.state.draw_history],['burned','burned'])
        self.assertEqual([e.card_id for e in self.hand(g)],[THREE,FOUR]);self.assertEqual(len(g.state.players[2].hand),10)

    def test_mimicry_copy_overflow_is_separate_from_opponent_draws(self):
        g=self.game((MIMIC,)+(PLAIN,)*9,enemy_deck=(THREE,FOUR));self.play(g,MIMIC);s=g.state
        self.assertEqual(len(s.players[1].hand),10);self.assertEqual(len(s.players[2].hand),2)
        self.assertEqual(len(s.draw_history),2);self.assertEqual([d.outcome for d in s.draw_history],['hand','hand'])
        self.assertTrue(any(s.entities[i].card_id==FOUR for i in s.players[1].graveyard))

    def test_mimicry_fatigue_has_no_copy_and_root_cast_copies_original_root(self):
        g=self.game((MIMIC,),enemy_deck=());self.play(g,MIMIC);self.assertFalse(self.hand(g))
        self.assertEqual([d.outcome for d in g.state.draw_history],['fatigue','fatigue'])
        g=self.game((MIMIC,),enemy_deck=('k44.portal',THREE,FOUR));self.play(g,MIMIC)
        self.assertEqual([e.card_id for e in self.hand(g)],['k44.portal',FOUR]);self.portable(g)

    def test_mimicry_wait_and_rollback_preserve_pre_draw_copy_material(self):
        g=self.game((MIMIC,),enemy_board=('k45.watch',),enemy_deck=(THREE,FOUR));self.play(g,MIMIC)
        saved=g.snapshot();other=self.portable(g);self.assertFalse(self.hand(g))
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for h in (g,other):self.choose(h)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual([e.card_id for e in self.hand(g)],[THREE,FOUR])

    def test_ladder_current_costs_are_unique_and_missing_classes_skip_fatigue(self):
        g=self.game((LADDER,),deck=(ONE,ONE,TWO,THREE,THREE));self.play(g,LADDER)
        costs=[g.registry.card(d.card_id).cost for d in g.state.draw_history];self.assertEqual(set(costs),{1,2,3})
        self.assertEqual(len(costs),3);self.portable(g)
        g=self.game((LADDER,),deck=(ONE,ONE));self.play(g,LADDER)
        self.assertEqual(len(g.state.draw_history),1);self.assertEqual(g.state.players[1].fatigue,0)

    def test_ladder_matches_current_local_costs_not_printed_costs(self):
        g=self.game(('k45.reprice',LADDER),enemy_deck=(THREE,FOUR),deck=(ONE,TWO,THREE))
        # A trusted prepared deck price is created through the ordinary effect.
        r=registry();r.register_behavior('k45.ownprice',lambda c:(ModifyStoredCost(CardReference.capture(c.state.entities[c.state.players[1].deck[1]]),CostSpec(set_to=1),c.source_id),))
        r.register_card(CardDefinition('k45.ownprice','own price',CardType.SPELL,on_play='k45.ownprice'))
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=('k45.ownprice',LADDER),deck=(ONE,TWO,THREE),mana=20,max_mana=20,mana_cap=20),PlayerSetup('HERO_08')),seed=946),r)
        self.play(g,'k45.ownprice');self.play(g,LADDER);self.assertEqual(len(g.state.draw_history),2)
        self.assertEqual(sorted(self.price(g,e.id)for e in self.hand(g)),[1,3])

    def test_ladder_burned_cost_is_still_excluded_from_later_slots(self):
        g=self.game((LADDER,)+(PLAIN,)*9,deck=(ONE,ONE,TWO,THREE));self.play(g,LADDER)
        rows=g.state.draw_history;self.assertEqual(len(rows),3);self.assertEqual(len({self.r.card(d.card_id).cost for d in rows}),3)
        self.assertEqual([d.outcome for d in rows],['hand','burned','burned'])

    def test_divination_only_actual_friendly_wisp_identities_are_legal(self):
        for wisp in (WISP,'CORE_CS2_231'):
            g=self.game((DIVINE,),board=(wisp,ONE,'k45.fake_wisp'),enemy_board=(WISP,));target=self.eid(g,wisp,zone='board');before=g.snapshot()
            for invalid in (self.eid(g,ONE,zone='board'),self.eid(g,'k45.fake_wisp',zone='board'),self.eid(g,WISP,p=2,zone='board')):
                with self.assertRaises(IllegalAction):self.play(g,DIVINE,invalid)
                self.assertEqual(g.snapshot(),before)
            self.play(g,DIVINE,target);self.assertEqual(len(g.state.draw_history),3)
            self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.portable(g)

    def test_divination_requires_wisp_before_mana_and_player_dto_uses_public_identity(self):
        g=self.game((DIVINE,),board=(ONE,));saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,DIVINE)
        self.assertEqual(g.snapshot(),saved)
        g=self.game((DIVINE,),board=(WISP,ONE));listing=g.for_player(1).legal_actions();player=listing['observation']['players'][0]
        card=next(c['ref']for c in player['hand']if c['card_id']==DIVINE);wisp=next(c['ref']for c in player['board']if c['card_id']==WISP)
        plays=[a for a in listing['actions']if a['type']=='play_card'and a['card']==card]
        self.assertEqual([a['target']for a in plays],[wisp]);reply=g.for_player(1).submit(dict(revision=listing['revision'],action=plays[0]));self.assertTrue(reply['accepted'])

    def test_private_materials_and_lock_deadlines_do_not_leak_to_opponent(self):
        g=self.game((BOUNTY,),deck=(ONE,TWO));self.play(g,BOUNTY);other=json.dumps(g.for_player(2).observe(),ensure_ascii=False)
        for key in ('hand_play_lock','created_owner_turn_id','owner_starts','hand_cursor',ONE,TWO):self.assertNotIn(key,other)
        own=g.for_player(1).legal_actions();refs={c['ref']for c in own['observation']['players'][0]['hand']}
        self.assertFalse(any(a['type']=='play_card'and a['card']in refs for a in own['actions']))

    def test_previous_actual_schema275_snapshot_is_rejected(self):
        from pathlib import Path
        from hs_sim.engine.representative import build_registry as representative
        path=Path(__file__).resolve().parents[1]/'outputs/card-integration-20261014/k45-before/default-snapshot-core345-schema275.json'
        with self.assertRaises(SnapshotError):Game.from_snapshot(json.loads(path.read_text(encoding='utf-8')),representative())


if __name__=='__main__':unittest.main()
