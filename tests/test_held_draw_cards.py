"""Real held spell families retain physical progress, payment and privacy."""
from dataclasses import replace
import json,unittest
from hs_sim.cards.held_draw_cards import load_batch
from hs_sim.engine import CardDefinition,CardType,EndTurn,Game,HandProgressSpec,PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import AddToHand,ChoiceOption,GainArmor,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.hand_upgrades import UpgradeHandCard
from hs_sim.engine.model import CostSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference,CopyCard,ModifyStoredCost
from hs_sim.targets import canonical_digest
from test_physical_draw_cards import registry as base_registry,ONE,TWO,THREE,FOUR,PLAIN,FIRE

FOREST='EDR_843';BOTH='EDR_843t1';GROVE='FIR_911';FROST='JAIL_803';ELEMENTAL='JAIL_803t'


def registry():
    r=base_registry()
    def copying(c,mode):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id in (FOREST,GROVE,FROST))
        return (CopyCard(CardReference.capture(e),c.player_id,Zone.HAND,mode=mode,source_id=c.source_id),)
    def cost(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id in (FOREST,GROVE,FROST))
        return (ModifyStoredCost(CardReference.capture(e),CostSpec(delta=-2),c.source_id),)
    def upgrade(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==FROST)
        return (UpgradeHandCard(CardReference.capture(e),ELEMENTAL,c.source_id),)
    def wait(c):
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('bad','Fail',(InvokeBehavior('h46.fail',c.source_id,c.player_id),))),c.source_id),)
    bodies=dict(copy=lambda c:copying(c,'current'),base=lambda c:copying(c,'base'),cost=cost,upgrade=upgrade,
        acquire=lambda c:(AddToHand(c.player_id,FROST,c.source_id),),
        auto=lambda c:(CastSpell(c.player_id,FIRE,c.source_id),),
        fail=lambda c:(AddToHand(c.player_id,'unknown.h46'),),wait=wait)
    for name,body in bodies.items():
        r.register_behavior('h46.'+name,body)
        r.register_card(CardDefinition('h46.'+name,name,CardType.SPELL,on_play='h46.'+name))
    def watch(c):
        e=c.state.entities[c.event.target_id]
        return wait(c)if e.card_id in (BOTH,ELEMENTAL)else ()
    r.register_behavior('h46.watch',watch)
    r.register_card(CardDefinition('h46.watch','Upgrade wait observer',CardType.MINION,health=10,
        triggers=(TriggerSpec('hand_card_upgraded','h46.watch'),)))
    return r


class HeldDrawCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand,*,deck=(PLAIN,)*12,board=(),enemy_hand=(),active=1):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,deck=deck,board=board,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=enemy_hand,deck=(PLAIN,)*12,mana=40,max_mana=40,mana_cap=40)),active_player=active,seed=946),self.r)
    def eid(self,g,cid,p=1):
        s=g.state;return next(i for i in s.players[p].hand if s.entities[i].card_id==cid)
    def play(self,g,cid,*,branch=None,target=None,p=1):
        s=g.state;eid=self.eid(g,cid,p);g.apply(PlayCard(p,eid,target,position=len(s.players[p].board)if s.entities[eid].kind==CardType.MINION else None,branch_id=branch));return eid
    def cycles(self,g,n):
        for _ in range(n):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def progress(self,g,eid):return progress_ability(g.state.entities[eid])
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return other
    def price(self,g,eid):
        s=g.state;return quote_unselected_cost(s,g.registry,s.entities[eid]).amount
    def sourced_draws(self,g,source):return [d for d in g.state.draw_history if d.source_id==source]

    def test_complete_three_roots_and_four_dependencies(self):
        data=load_batch();self.assertEqual(len(data['cards']),7)
        self.assertEqual({row['record']['id']for row in data['cards']if row['recipe']['root']},{FOREST,GROVE,FROST})
        for row in data['cards']:
            raw=row['record'];self.assertEqual(canonical_digest(raw),row['record_sha256'])
            self.assertEqual(self.r.card(raw['id']).cost,0 if row['recipe']['choice_only']else raw['cost'])
        for cid in ('EDR_843a','EDR_843b'):
            self.assertTrue(self.r.card(cid).choice_only);self.assertFalse(self.r.card(cid).hand_playable)

    def test_forest_each_native_branch_draws_only_its_type_and_pays_once(self):
        for branch,kind in (('EDR_843a',CardType.SPELL),('EDR_843b',CardType.MINION)):
            g=self.game((FOREST,),deck=(ONE,FIRE));mana=g.state.players[1].mana;source=self.play(g,FOREST,branch=branch)
            self.assertEqual(g.state.players[1].mana,mana-2);rows=self.sourced_draws(g,source);self.assertEqual(len(rows),1)
            self.assertEqual(g.registry.card(rows[0].card_id).kind,kind)
            self.assertEqual([c.card_id for c in g.state.cast_history],[FOREST]);self.portable(g)

    def test_forest_empty_matching_branch_does_not_fatigue(self):
        g=self.game((FOREST,),deck=(ONE,));before=g._rng.getstate();self.play(g,FOREST,branch='EDR_843a')
        self.assertFalse(g.state.draw_history);self.assertEqual(g._rng.getstate(),before)

    def test_forest_requires_a_real_branch_before_completion(self):
        g=self.game((FOREST,),deck=(ONE,FIRE));saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,FOREST)
        self.assertEqual(g.snapshot(),saved)
        with self.assertRaises(IllegalAction):self.play(g,FOREST,branch='not-native')
        self.assertEqual(g.snapshot(),saved)

    def test_forest_third_actual_owner_end_changes_same_physical_face(self):
        g=self.game((FOREST,),deck=(PLAIN,)*8+(FIRE,ONE));eid=self.eid(g,FOREST);self.cycles(g,2)
        self.assertEqual(g.state.entities[eid].card_id,FOREST);g.apply(EndTurn(1));s=g.state
        self.assertEqual(s.entities[eid].card_id,BOTH);self.assertEqual(s.entities[eid].kind,CardType.SPELL)
        self.assertEqual(self.price(g,eid),2);self.assertTrue(self.progress(g,eid).consumed)
        g.apply(EndTurn(2));source=self.play(g,BOTH);rows=self.sourced_draws(g,source)
        self.assertEqual([g.registry.card(d.card_id).kind for d in rows],[CardType.SPELL,CardType.MINION]);self.portable(g)

    def test_forest_opponent_end_is_not_a_held_turn(self):
        g=self.game((FOREST,),active=2);eid=self.eid(g,FOREST);g.apply(EndTurn(2))
        self.assertEqual(self.progress(g,eid).progress_value,0);g.apply(EndTurn(1));self.assertEqual(self.progress(g,eid).progress_value,1)

    def test_forest_current_copy_inherits_progress_with_independent_identity(self):
        g=self.game((FOREST,'h46.copy'));self.cycles(g,2);self.play(g,'h46.copy');ids=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==FOREST]
        self.assertEqual(len(ids),2);self.assertEqual([self.progress(g,i).progress_value for i in ids],[2,2])
        self.assertEqual(len({self.progress(g,i).id for i in ids}),2);g.apply(EndTurn(1))
        self.assertTrue(all(g.state.entities[i].card_id==BOTH for i in ids));self.portable(g)

    def test_forest_upgrade_wait_restore_rollback_and_no_second_payment(self):
        g=self.game((FOREST,),board=('h46.watch',));self.cycles(g,2);g.apply(EndTurn(1));saved=g.snapshot();other=self.portable(g)
        self.assertEqual(g.state.active_player,1)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for h in (g,other):self.choose(h)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertFalse(g.state.play_history)

    def test_grove_initial_draws_one_then_two_after_one_owner_end(self):
        g=self.game((GROVE,));source=self.play(g,GROVE);self.assertEqual(len(self.sourced_draws(g,source)),1)
        g=self.game((GROVE,));eid=self.eid(g,GROVE);self.cycles(g,1);self.assertEqual(self.progress(g,eid).progress_completions,1)
        source=self.play(g,GROVE);self.assertEqual(len(self.sourced_draws(g,source)),2);self.portable(g)

    def test_grove_draws_three_after_two_owner_ends_without_discarding_early(self):
        g=self.game((GROVE,));eid=self.eid(g,GROVE);self.cycles(g,2);self.assertIn(eid,g.state.players[1].hand)
        source=self.play(g,GROVE);self.assertEqual(len(self.sourced_draws(g,source)),3);self.assertFalse(g.state.discard_history)

    def test_grove_third_owner_end_is_actual_self_discard_not_destruction(self):
        g=self.game((GROVE,));eid=self.eid(g,GROVE);self.cycles(g,2);g.apply(EndTurn(1));s=g.state
        self.assertEqual(s.entities[eid].zone,Zone.GRAVEYARD);self.assertEqual(len(s.discard_history),1)
        self.assertEqual((s.discard_history[0].entity_id,s.discard_history[0].source_id),(eid,eid))
        self.assertFalse(s.death_history);self.portable(g)

    def test_grove_opponent_end_does_not_grow_or_expire(self):
        g=self.game((GROVE,),active=2);eid=self.eid(g,GROVE);g.apply(EndTurn(2))
        self.assertEqual(self.progress(g,eid).progress_completions,0);self.assertIn(eid,g.state.players[1].hand)

    def test_grove_current_copy_keeps_growth_and_both_have_own_discard(self):
        g=self.game((GROVE,'h46.copy'));self.cycles(g,1);self.play(g,'h46.copy')
        ids=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==GROVE]
        self.assertEqual(len(ids),2);self.cycles(g,1);g.apply(EndTurn(1))
        self.assertEqual([d.entity_id for d in g.state.discard_history],ids);self.portable(g)

    def test_grove_base_copy_starts_fresh_instead_of_inheriting_growth(self):
        g=self.game((GROVE,'h46.base'));original=self.eid(g,GROVE);self.cycles(g,1);self.play(g,'h46.base')
        ids=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==GROVE]
        self.assertEqual([self.progress(g,i).progress_completions for i in ids],[1,0]);self.cycles(g,1);g.apply(EndTurn(1))
        self.assertEqual([d.entity_id for d in g.state.discard_history],[original])

    def test_frost_base_spell_freezes_enemy_hero_then_draws_two(self):
        g=self.game((FROST,));target=g.state.players[2].hero_id;source=self.play(g,FROST,target=target)
        self.assertTrue(g.state.entities[target].frozen);self.assertEqual(len(self.sourced_draws(g,source)),2);self.portable(g)

    def test_frost_only_own_accepted_spells_advance_and_third_changes_type(self):
        g=self.game((FROST,FIRE,FIRE,FIRE),enemy_hand=(FIRE,));eid=self.eid(g,FROST)
        g.apply(EndTurn(1));self.play(g,FIRE,p=2);self.assertEqual(self.progress(g,eid).progress_value,0);g.apply(EndTurn(2))
        self.play(g,FIRE);self.play(g,FIRE);self.assertEqual(self.progress(g,eid).progress_value,2);self.play(g,FIRE);s=g.state
        self.assertEqual((s.entities[eid].card_id,s.entities[eid].kind,s.entities[eid].attack,s.entities[eid].health),(ELEMENTAL,CardType.MINION,5,5))
        self.assertIn(eid,s.players[1].hand);self.portable(g)

    def test_frost_acquired_mid_payload_does_not_retroactively_count_it(self):
        g=self.game(('h46.acquire',FIRE,FIRE,FIRE));self.play(g,'h46.acquire');eid=self.eid(g,FROST)
        self.assertEqual(self.progress(g,eid).progress_value,0);self.play(g,FIRE);self.play(g,FIRE)
        self.assertEqual(g.state.entities[eid].card_id,FROST);self.play(g,FIRE);self.assertEqual(g.state.entities[eid].card_id,ELEMENTAL)

    def test_frost_nested_automatic_payload_is_an_independent_real_cast(self):
        g=self.game((FROST,'h46.auto',FIRE));eid=self.eid(g,FROST);self.play(g,'h46.auto')
        self.assertEqual(self.progress(g,eid).progress_value,2);self.assertEqual(len(self.progress(g,eid).progress_keys),2)
        self.play(g,FIRE);self.assertEqual(g.state.entities[eid].card_id,ELEMENTAL);self.portable(g)

    def test_frost_current_cost_survives_change_and_actual_minion_payment(self):
        g=self.game((FROST,'h46.cost',FIRE,FIRE));eid=self.eid(g,FROST);self.play(g,'h46.cost');self.play(g,FIRE);self.play(g,FIRE)
        self.assertEqual(g.state.entities[eid].card_id,ELEMENTAL);self.assertEqual(self.price(g,eid),3)
        target=g.state.players[2].hero_id;mana=g.state.players[1].mana;source=self.play(g,ELEMENTAL,target=target)
        self.assertEqual(g.state.players[1].mana,mana-3);self.assertEqual(g.state.entities[eid].zone,Zone.BOARD)
        self.assertTrue(g.state.entities[target].frozen);self.assertEqual(len(self.sourced_draws(g,source)),2);self.portable(g)

    def test_frost_current_copy_inherits_two_casts_but_base_copy_starts_fresh(self):
        for copying,expected in (('h46.copy',ELEMENTAL),('h46.base',FROST)):
            g=self.game((FROST,FIRE,FIRE,copying));original=self.eid(g,FROST);self.play(g,FIRE);self.play(g,copying)
            ids=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==FROST];self.assertEqual(len(ids),2)
            self.play(g,FIRE);self.assertEqual(g.state.entities[original].card_id,ELEMENTAL)
            self.assertEqual(g.state.entities[ids[1]].card_id,expected);self.portable(g)

    def test_frost_third_failed_payload_rolls_back_face_progress_and_payment(self):
        g=self.game((FROST,FIRE,FIRE,'h46.fail'));eid=self.eid(g,FROST);self.play(g,FIRE);self.play(g,FIRE);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'h46.fail')
        self.assertEqual(g.snapshot(),saved);self.assertEqual(g.state.entities[eid].card_id,FROST)
        self.assertEqual(self.progress(g,eid).progress_value,2)

    def test_frost_upgrade_wait_preserves_current_cast_and_original_face_change(self):
        g=self.game((FROST,FIRE,FIRE,FIRE),board=('h46.watch',));eid=self.eid(g,FROST)
        self.play(g,FIRE);self.play(g,FIRE);self.play(g,FIRE);saved=g.snapshot();other=self.portable(g)
        self.assertEqual(g.state.entities[eid].card_id,ELEMENTAL)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for h in (g,other):self.choose(h)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.cast_history),3)

    def test_other_progress_cross_type_and_plain_upgrade_stay_rejected(self):
        with self.assertRaises(ValueError):self.r.validate_hand_progress(HandProgressSpec('event',3,ELEMENTAL,event='turn_ended'),CardType.SPELL)
        g=self.game((FROST,'h46.upgrade'));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'h46.upgrade')
        self.assertEqual(g.snapshot(),saved)

    def test_private_progress_and_choice_only_descriptions_stay_out_of_opponent_view(self):
        g=self.game((FOREST,GROVE,FROST,FIRE));self.play(g,FIRE);other=g.for_player(2).observe();text=json.dumps(other,ensure_ascii=False)
        for key in (FOREST,GROVE,FROST,'progress_keys'):self.assertNotIn(key,text)
        hidden=next(p for p in other['observation']['players']if p['id']==1)['hand']
        self.assertTrue(all(set(row)=={'ref','card_id'}and row['card_id']is None for row in hidden))
        listing=g.for_player(1).legal_actions();player=listing['observation']['players'][0]
        ref=next(c['ref']for c in player['hand']if c['card_id']==FOREST)
        branches={a['branch']for a in listing['actions']if a['type']=='play_card'and a['card']==ref}
        self.assertEqual(branches,{'EDR_843a','EDR_843b'})

    def test_actual_old_content_and_old_core_snapshot_are_rejected(self):
        from pathlib import Path
        from hs_sim.cards import build_registry
        from hs_sim.engine.representative import build_registry as representative
        path=Path(__file__).resolve().parents[1]/'tests/fixtures/history/card-integration-20261014/k46-before'
        with self.assertRaises(SnapshotError):Game.from_snapshot(json.loads((path/'constructed-v54-core346-schema276.json').read_text(encoding='utf-8')),build_registry())
        with self.assertRaises(SnapshotError):Game.from_snapshot(json.loads((path/'default-v65-core346-schema276.json').read_text(encoding='utf-8')),representative())


if __name__=='__main__':unittest.main()
