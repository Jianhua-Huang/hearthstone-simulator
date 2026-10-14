"""Independent installed powers across actions, state, payment and player boundaries."""
import json
import unittest

from hs_sim.engine import (AddHeroPower, CardDefinition, CardType, CostSpec, DamageKind,
    EndTurn, Game, IllegalAction, PaymentType, PlayCard, PlayerSetup, Registry, Resource,
    ResolutionError, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, UseHeroPower)
from hs_sim.engine.effects import (AddCostModifier, ChoiceOption, Damage, GainArmor,
    InvokeBehavior, ModifyCost, RefreshHeroPower, ReplaceHeroPower, RequestChoice, SetHeroPowerUses)
from hs_sim.engine.hero_powers import TriggerHeroPower
from hs_sim.engine.player_api import visible_entities
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


class MultiplePowerTests(unittest.TestCase):
    def setUp(self):
        self.r = Registry('multiple-powers-tests-v1')
        self.r.register_card(CardDefinition('hero', 'hero', CardType.HERO, health=30))
        self.r.register_card(CardDefinition('minion', 'minion', CardType.MINION, attack=1, health=4))
        self.power('one', lambda c: [GainArmor(c.player_id, 1)])
        self.power('two', lambda c: [GainArmor(c.player_id, 2)], cost=3)
        self.power('target', lambda c: [Damage(c.target_id, 2, c.source_id, DamageKind.HERO_POWER)],
                   targeting=TargetSpec(relation='enemy'))
        self.script('add', lambda c: [AddHeroPower(c.player_id, 'two', c.source_id)])
        self.script('replace', lambda c: [ReplaceHeroPower(c.player_id, 'two')])
        self.script('refresh', lambda c: [RefreshHeroPower(c.player_id)])
        self.script('trigger', lambda c: [TriggerHeroPower(c.player_id, c.source_id)])

    def power(self, cid, fn, cost=2, **kw):
        self.r.register_behavior(cid, fn)
        self.r.register_card(CardDefinition(cid, cid, CardType.HERO_POWER, cost=cost, on_use=cid, **kw))

    def script(self, cid, fn):
        self.r.register_behavior(cid, fn)
        self.r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid))

    def game(self, extras=('two',), primary='one', hand=(), mana=10, enemy_extras=(), board=()):
        return Game.from_scenario(Scenario((PlayerSetup('hero', hero_power_card_id=primary,
            additional_hero_power_card_ids=extras, hand=hand, board=board, deck=('minion',)*4,
            max_mana=10, mana=mana, corpses=6), PlayerSetup('hero', hero_power_card_id='one',
            additional_hero_power_card_ids=enemy_extras, hand=('minion',), deck=('minion',)*4,
            max_mana=10, mana=10)), seed=67), self.r)

    def ids(self, g, p=1): return g.state.players[p].hero_power_ids
    def use(self, g, index=1, target=None): g.apply(UseHeroPower(1, self.ids(g)[index], target))
    def play(self, g, cid):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, eid))
    def armor(self, g): return g.state.entities[g.state.players[1].hero_id].armor
    def check(self, g):
        s=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(s, self.r).snapshot(), s)
        self.assertEqual(g.clone().snapshot(), s)
        self.assertEqual(replay(build_replay(g), self.r).snapshot(), s)
    def reject(self, s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as error: Game.from_snapshot(s, self.r)
        self.assertNotIn('digest mismatch', str(error.exception))
    def choose(self, g):
        c=g.state.pending_choice
        g.apply(SelectChoice(c.player_id, c.id, (c.options[0].id,)))
    def choice_power(self):
        self.power('choice', lambda c: [RequestChoice(c.player_id,
            (ChoiceOption('go','go',(GainArmor(c.player_id,4),)),), source_id=c.source_id)])

    def test_two_powers_pay_and_exhaust_independently(self):
        g=self.game(); self.use(g); self.use(g,0)
        self.assertEqual((g.state.players[1].mana,self.armor(g)),(5,3))
        self.assertEqual([g.state.entities[i].uses_this_turn for i in self.ids(g)],[1,1])
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn,2)
        for i in (0,1):
            with self.assertRaises(IllegalAction): self.use(g,i)
        self.check(g)

    def test_same_definition_has_distinct_identity_and_history(self):
        g=self.game(extras=('one',)); self.use(g); self.use(g,0)
        a,b=g.state.hero_power_history
        self.assertNotEqual(a.source_id,b.source_id)
        self.assertEqual((a.card_id,b.card_id,a.uses_before,b.uses_before),('one','one',0,0))
        self.assertEqual((a.player_uses_before,b.player_uses_before),(0,1)); self.check(g)

    def test_no_primary_does_not_promote_additional_power(self):
        g=self.game(primary=None); self.use(g,0)
        self.assertIsNone(g.state.players[1].hero_power_id)
        self.assertIsNone(g.observe(1)['players'][0]['hero_power']); self.check(g)

    def test_ordered_collection_supports_more_than_one_extra_without_aliases(self):
        g=self.game(extras=('two','one'))
        self.assertEqual([g.state.entities[i].card_id for i in self.ids(g)],['one','two','one'])
        for i in range(3): self.use(g,i)
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn,3); self.check(g)

    def test_turn_boundary_refreshes_both_players_installed_powers(self):
        g=self.game(enemy_extras=('two',)); self.use(g); self.use(g,0); g.apply(EndTurn(1))
        g.apply(UseHeroPower(2,self.ids(g,2)[1])); g.apply(EndTurn(2))
        for p in (1,2):
            self.assertEqual(g.state.players[p].hero_power_uses_this_turn,0)
            self.assertTrue(all(g.state.entities[i].uses_this_turn==0 for i in self.ids(g,p)))
        self.use(g); self.check(g)

    def test_declaration_use_limits_are_per_entity(self):
        self.power('twice',lambda c:[GainArmor(1,1)],cost=1,uses_per_turn=2)
        g=self.game(extras=('twice',)); self.use(g); self.use(g); self.use(g,0)
        with self.assertRaises(IllegalAction): self.use(g)
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn,3)

    def test_primary_refresh_preserves_extra_exhaustion(self):
        g=self.game(hand=('refresh',)); self.use(g); self.use(g,0); self.play(g,'refresh')
        self.assertEqual([g.state.entities[i].uses_this_turn for i in self.ids(g)],[0,1]); self.check(g)

    def test_primary_limit_effect_does_not_modify_extra(self):
        self.script('limit',lambda c:[SetHeroPowerUses(1,3)])
        g=self.game(hand=('limit',)); self.play(g,'limit')
        self.assertEqual([g.state.entities[i].use_limit for i in self.ids(g)],[3,1])

    def test_local_cost_change_does_not_modify_other_power(self):
        self.script('cost',lambda c:[ModifyCost(c.state.players[1].additional_hero_power_ids[0],CostSpec(delta=-2,card_types=(CardType.HERO_POWER,)))])
        g=self.game(hand=('cost',)); self.play(g,'cost')
        self.assertEqual([g.quote_cost(i).amount for i in self.ids(g)],[2,1]); self.use(g); self.check(g)

    def test_next_power_discount_is_consumed_by_selected_extra(self):
        self.script('discount',lambda c:[AddCostModifier(1,CostSpec(delta=-1,card_types=(CardType.HERO_POWER,)),1)])
        g=self.game(hand=('discount',)); self.play(g,'discount')
        self.assertEqual([g.quote_cost(i).amount for i in self.ids(g)],[1,2])
        self.use(g); self.assertEqual(g.quote_cost(self.ids(g)[0]).amount,2)
        self.assertEqual(g.state.hero_power_history[0].cost,2); self.check(g)

    def test_extra_can_pay_corpses_without_changing_primary_payment(self):
        self.script('corpses',lambda c:[ModifyCost(c.state.players[1].additional_hero_power_ids[0],
            CostSpec(payment=PaymentType.CORPSES,card_types=(CardType.HERO_POWER,)))])
        g=self.game(hand=('corpses',),mana=2); self.play(g,'corpses'); self.use(g); self.use(g,0)
        self.assertEqual((g.state.players[1].resources[Resource.CORPSES],g.state.players[1].mana),(3,0))
        self.assertEqual([p.payment for p in g.state.hero_power_history],[PaymentType.CORPSES,PaymentType.MANA]); self.check(g)

    def test_affordability_controls_each_action_independently(self):
        g=self.game(mana=2); actions=[a for a in g.legal_actions() if isinstance(a,UseHeroPower)]
        self.assertEqual([a.entity_id for a in actions],[self.ids(g)[0]])
        before=g.snapshot()
        with self.assertRaises(IllegalAction): self.use(g)
        self.assertEqual(g.snapshot(),before)

    def test_extra_target_query_and_action_share_validation(self):
        g=self.game(extras=('target',)); target=g.state.players[2].hero_id
        self.assertEqual(g.legal_targets(self.ids(g)[1]),(target,))
        with self.assertRaises(IllegalAction): self.use(g,target=g.state.players[1].hero_id)
        self.use(g,target=target); self.assertEqual(g.state.entities[target].health,28); self.check(g)

    def test_queries_are_pure(self):
        g=self.game(extras=('target',)); before=g.snapshot()
        for i in self.ids(g): g.quote_cost(i); g.legal_targets(i)
        g.legal_actions(); g.for_player(1).legal_actions(); g.observe(2)
        self.assertEqual(g.snapshot(),before)

    def test_add_effect_preserves_primary_and_exhausted_extra(self):
        g=self.game(hand=('add',)); ids=self.ids(g); self.use(g); self.play(g,'add')
        self.assertEqual(self.ids(g)[:2],ids); self.assertEqual(len(self.ids(g)),3)
        self.assertEqual(g.state.entities[ids[1]].uses_this_turn,1); self.use(g,2); self.check(g)

    def test_replacing_primary_preserves_extra_identity_and_history(self):
        g=self.game(hand=('replace',)); old,extra=self.ids(g); self.use(g); self.play(g,'replace')
        self.assertEqual(self.ids(g)[1],extra); self.assertIn(old,g.state.players[1].graveyard)
        self.assertEqual(g.state.hero_power_history[0].source_id,extra); self.check(g)

    def test_legacy_indirect_entry_only_activates_primary(self):
        g=self.game(hand=('trigger',)); self.play(g,'trigger')
        self.assertEqual(self.armor(g),1); self.assertEqual(g.state.hero_power_history[0].source_id,self.ids(g)[0])
        self.assertEqual([g.state.entities[i].uses_this_turn for i in self.ids(g)],[0,0]); self.check(g)

    def test_missing_primary_indirect_entry_fails_instead_of_picking_extra(self):
        g=self.game(primary=None,hand=('trigger',)); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'trigger')
        self.assertEqual(g.snapshot(),before)

    def test_add_wrong_kind_unknown_card_and_missing_source_roll_back(self):
        for cid,effect in [('badkind',AddHeroPower(1,'minion')),('missing',AddHeroPower(1,'missing')),
                           ('source',AddHeroPower(1,'two',999999))]:
            self.script(cid,lambda c,e=effect:[e])
        for cid in ('badkind','missing','source'):
            g=self.game(hand=(cid,)); before=g.snapshot()
            with self.assertRaises((ResolutionError,ValueError)): self.play(g,cid)
            self.assertEqual(g.snapshot(),before)

    def test_late_failure_restores_payment_new_slot_and_history(self):
        def fail(c): raise ValueError('expected failure')
        self.r.register_behavior('fail',fail)
        self.power('failure',lambda c:[AddHeroPower(1,'two',c.source_id),InvokeBehavior('fail',c.source_id,1)])
        g=self.game(extras=('failure',)); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.use(g)
        self.assertEqual(g.snapshot(),before)

    def test_extra_choice_retains_source_across_save_restore(self):
        self.choice_power(); g=self.game(extras=('choice',)); self.use(g)
        self.assertEqual(g.state.pending_choice.source_id,self.ids(g)[1]); self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored): self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot()); self.assertEqual(self.armor(g),4); self.check(g)

    def test_pending_choice_can_install_extra_after_restore(self):
        self.script('offer',lambda c:[RequestChoice(1,(ChoiceOption('add','add',(AddHeroPower(1,'two',c.source_id),)),))])
        g=self.game(extras=(),hand=('offer',)); self.play(g,'offer'); self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored): self.choose(match); self.use(match)
        self.assertEqual(g.snapshot(),restored.snapshot()); self.check(g)

    def test_extra_passive_listens_and_cannot_be_used(self):
        self.r.register_behavior('listen',lambda c:[GainArmor(c.player_id,2)])
        self.r.register_card(CardDefinition('passive','passive',CardType.HERO_POWER,passive_hero_power=True,
            triggers=(TriggerSpec('card_played','listen'),)))
        g=self.game(extras=('passive',),hand=('minion',)); self.play(g,'minion')
        self.assertEqual(self.armor(g),2)
        with self.assertRaises(IllegalAction): self.use(g)
        self.assertFalse(any(isinstance(a,UseHeroPower) and a.entity_id==self.ids(g)[1] for a in g.legal_actions()))
        self.check(g)

    def test_primary_and_extra_passive_listeners_run_in_installation_order(self):
        self.r.register_behavior('listen',lambda c:[GainArmor(1,c.source_id)])
        self.r.register_card(CardDefinition('passive','passive',CardType.HERO_POWER,passive_hero_power=True,
            triggers=(TriggerSpec('card_played','listen'),)))
        g=self.game(primary='passive',extras=('passive',),hand=('minion',)); self.play(g,'minion')
        self.assertEqual([e.amount for e in g.events if e.kind=='armor_gained'],list(self.ids(g))); self.check(g)

    def test_extra_is_public_but_opponent_hand_stays_hidden(self):
        g=self.game(enemy_extras=('two',)); view=g.observe(1)
        self.assertEqual(view['players'][1]['additional_hero_powers'][0]['card_id'],'two')
        self.assertIsNone(view['players'][1]['hand'][0]['card_id'])
        extra=view['players'][0]['additional_hero_powers'][0]
        self.assertEqual(visible_entities(view)[extra['ref']]['zone'],'hero_power')
        self.assertNotIn('entity_id',extra)

    def test_player_port_uses_selected_extra_and_rejects_enemy_ref(self):
        g=self.game(enemy_extras=('two',)); port=g.for_player(1); listing=port.legal_actions()
        extra=listing['observation']['players'][0]['additional_hero_powers'][0]['ref']
        action=next(a for a in listing['actions'] if a.get('power')==extra)
        self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted'])
        before=g.snapshot(); view=port.observe()
        enemy=view['observation']['players'][1]['additional_hero_powers'][0]['ref']
        result=port.submit({'revision':view['revision'],'action':{'type':'use_hero_power','power':enemy}})
        self.assertFalse(result['accepted']); self.assertEqual(g.snapshot(),before); self.check(g)

    def test_player_predicate_receives_extra_source_view(self):
        self.r.register_use_rule('known',lambda c:c.source['card_id']=='restricted', visibility='player')
        self.power('restricted',lambda c:[GainArmor(1,3)],use_rule='known')
        g=self.game(extras=('restricted',)); listing=g.for_player(1).legal_actions()
        self.assertIsNone(listing['error']); self.use(g); self.assertEqual(self.armor(g),3)

    def test_trusted_only_extra_predicate_is_rejected_at_player_boundary(self):
        self.r.register_use_rule('private',lambda c:bool(c.state.players[2].hand))
        self.power('restricted',lambda c:[],use_rule='private')
        g=self.game(extras=('restricted',)); before=g.snapshot()
        self.assertEqual(g.for_player(1).legal_actions()['error'],'unsupported_rule')
        self.assertEqual(g.snapshot(),before)

    def test_added_event_public_identity_survives_restore(self):
        g=self.game(extras=(),hand=('add',)); self.play(g,'add')
        for p in (1,2):
            event=next(e for e in g.player_events(p) if e['kind']=='hero_power_added')
            self.assertEqual(event['target']['card_id'],'two')
        self.check(g)

    def test_scenario_json_roundtrip_and_invalid_shapes(self):
        s=Scenario((PlayerSetup('hero',additional_hero_power_card_ids=('one','two')),PlayerSetup('hero')))
        self.assertEqual(Scenario.from_dict(json.loads(json.dumps(s.to_dict()))),s)
        for value in (['two'],'two',(None,),('',),(True,)):
            with self.assertRaises(ValueError): PlayerSetup('hero',additional_hero_power_card_ids=value)
        with self.assertRaises(ResolutionError): self.game(extras=('minion',))

    def test_snapshot_rejects_wrong_extra_collection_or_entity_references(self):
        g=self.game(); ids=self.ids(g)
        for value in (None,{},'two',[True],[0],[9999],[ids[0]],[ids[1],ids[1]],[g.state.players[2].hero_power_id]):
            with self.subTest(value=value):
                s=g.snapshot(); s['state']['players']['1']['additional_hero_power_ids']=value; self.reject(s)

    def test_snapshot_rejects_orphaned_extra(self):
        g=self.game(); s=g.snapshot(); s['state']['players']['1']['additional_hero_power_ids']=[]; self.reject(s)

    def test_old_schema_is_explicitly_rejected(self):
        g=self.game(); s=g.snapshot(); s['schema_version']=66
        with self.assertRaisesRegex(SnapshotError,'schema'): Game.from_snapshot(s,self.r)

    def test_state_copy_cannot_modify_live_extra_slots(self):
        g=self.game(); before=g.snapshot(); state=g.state
        state.players[1].additional_hero_power_ids.clear()
        self.assertEqual(g.snapshot(),before)

    def test_paused_extra_blocks_using_primary_until_choice_finishes(self):
        self.choice_power(); g=self.game(extras=('choice',)); self.use(g); before=g.snapshot()
        with self.assertRaises(IllegalAction): self.use(g,0)
        self.assertEqual(g.snapshot(),before); self.choose(g); self.use(g,0); self.check(g)

    def test_extra_passive_pending_frame_survives_primary_replacement(self):
        self.r.register_behavior('listen',lambda c:[GainArmor(1,2)])
        self.r.register_card(CardDefinition('passive','passive',CardType.HERO_POWER,passive_hero_power=True,
            triggers=(TriggerSpec('card_played','listen'),)))
        self.r.register_behavior('wait',lambda c:[RequestChoice(1,
            (ChoiceOption('go','go',(ReplaceHeroPower(1,'two'),)),))])
        self.r.register_card(CardDefinition('wait','wait',CardType.MINION,health=4,
            triggers=(TriggerSpec('card_played','wait'),)))
        # Install passive after the watcher so its check remains in the frame.
        self.script('install',lambda c:[AddHeroPower(1,'passive')])
        g=self.game(extras=(),hand=('install',),board=('wait',)); self.play(g,'install'); self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored): self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot()); self.assertEqual(self.armor(g),2); self.check(g)

    def test_failed_choice_keeps_paid_and_pending_extra(self):
        def fail(c): raise ValueError('expected failure')
        self.r.register_behavior('fail',fail)
        self.power('choice',lambda c:[RequestChoice(1,(ChoiceOption('fail','fail',
            (AddHeroPower(1,'two'),InvokeBehavior('fail',c.source_id,1))),),source_id=c.source_id)])
        g=self.game(extras=('choice',)); self.use(g); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g)
        self.assertEqual(g.snapshot(),before); self.check(g)

    def test_full_board_restriction_is_specific_to_selected_power(self):
        self.power('space',lambda c:[GainArmor(1,3)],requires_board_space=True)
        g=self.game(extras=('space',),board=('minion',)*7)
        with self.assertRaises(IllegalAction): self.use(g)
        self.use(g,0); self.assertEqual(self.armor(g),1)

    def test_stale_player_revision_after_other_power_use_is_rejected(self):
        g=self.game(); port=g.for_player(1); listing=port.legal_actions()
        extra=listing['observation']['players'][0]['additional_hero_powers'][0]['ref']
        self.use(g,0); before=g.snapshot()
        result=port.submit({'revision':listing['revision'],'action':{'type':'use_hero_power','power':extra}})
        self.assertEqual(result['error'],'stale_observation'); self.assertEqual(g.snapshot(),before)

    def test_add_without_primary_still_creates_only_extra(self):
        g=self.game(primary=None,extras=(),hand=('add',)); self.play(g,'add')
        self.assertIsNone(g.state.players[1].hero_power_id); self.use(g,0); self.check(g)

    def test_add_effect_validates_declared_types(self):
        for args in ((True,'one'),(3,'one'),(1,''),(1,4),(1,'one',False)):
            with self.subTest(args=args):
                with self.assertRaises(ValueError): AddHeroPower(*args)

    def test_snapshot_requires_new_extra_field_even_when_empty(self):
        g=self.game(extras=()); s=g.snapshot()
        del s['state']['players']['1']['additional_hero_power_ids']; self.reject(s)


if __name__ == '__main__': unittest.main()
