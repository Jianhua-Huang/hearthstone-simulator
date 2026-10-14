"""Health debits shared by damage, payments and explicit loss, through actions."""
import json
import unittest

from hs_sim.engine import (AbilityInstance, CardDefinition, CardType, CostSpec, DamageKind,
    EndTurn, Game, GenerationContext, HealthFlow, HealthLayer, HealthLossKind,
    HealthLossReplacementSpec, HealthOp, HealthRule, IllegalAction, Keyword, PaymentType,
    PlayCard, PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone,
    GainMaxHealth, GrantHealthLossReplacement, LoseHealth)
from hs_sim.engine.effects import (AddCostModifier, ChangeControl, ChoiceOption, CopyMinion,
    Damage, DamageBatch, Destroy, GainArmor, GrantKeyword, Heal, ModifyCost, ReplaceHero,
    RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.dormancy import MakeDormant, AwakenMinion
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay


class HealthLossTests(unittest.TestCase):
    def setUp(self):
        self.r = build_registry()
        self.minion('plain', attack=2, health=8)
        self.minion('guard', health=5, health_loss_replacements=(HealthLossReplacementSpec(),))
        self.spell('hit', lambda c: [Damage(c.target_id, 3, c.source_id, DamageKind.SPELL)], requires_target=True)
        self.spell('loss', lambda c: [LoseHealth(c.target_id, 3, c.source_id)], requires_target=True)
        self.spell('gain', lambda c: [GainMaxHealth(c.player_id, 3, c.source_id)])
        self.spell('convert', lambda c: [AddCostModifier(c.player_id, CostSpec(payment=PaymentType.HEALTH), 1)])
        self.spell('expensive', lambda c: [], cost=40)
        for name, fn in (
            ('silence', lambda c: [Silence(c.target_id)]),
            ('bounce', lambda c: [ReturnToHand(c.target_id)]),
            ('kill', lambda c: [Destroy(c.target_id)]),
            ('transform', lambda c: [Transform(c.target_id, 'plain')]),
            ('sleep', lambda c: [MakeDormant(c.target_id, None)]),
            ('wake', lambda c: [AwakenMinion(c.target_id)]),
            ('steal', lambda c: [ChangeControl(c.target_id, 2)]),
            ('copy', lambda c: [CopyMinion(c.target_id, c.player_id)]),
        ): self.spell(name, fn, requires_target=True)

    def minion(self, name, **kw):
        self.r.register_card(CardDefinition(name, name, CardType.MINION, **kw))

    def spell(self, name, fn, **kw):
        self.r.register_behavior(name, fn)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, **kw))

    def game(self, hand=(), board=('guard',), enemy=(), enemy_hand=(), armor=0, mana=10, context=True):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_01', hand=hand, board=board, armor=armor, deck=('plain',)*12, max_mana=10, mana=mana),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=('plain',)*12, max_mana=10, mana=10)),
            seed=173, generation_context=GenerationContext('local-2026-09-23', 'experimental') if context else None), self.r)

    def play(self, g, name, target=None):
        p=g.state.active_player
        card=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==name)
        g.apply(PlayCard(p, card, target)); return card

    def hero(self, g, p=1): return g.state.entities[g.state.players[p].hero_id]
    def board(self, g, p=1): return [g.state.entities[i] for i in g.state.players[p].board]
    def events(self, g, kind): return [e for e in g.events if e.kind==kind]
    def check(self, g):
        snapshot=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snapshot,self.r).snapshot(),snapshot)
        self.assertEqual(g.clone().snapshot(),snapshot)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),snapshot)

    def test_own_turn_damage_grows_current_and_max_health(self):
        g=self.game(hand=('hit',)); self.play(g,'hit',self.hero(g).id)
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(33,33))
        event=self.events(g,'damage_dealt')[0]
        self.assertEqual((event.amount,dict(event.data)['health_lost'],dict(event.data)['health_replaced']),(3,0,3))
        self.assertEqual(len(self.events(g,'max_health_gained')),1); self.check(g)

    def test_growth_preserves_missing_health(self):
        self.spell('setup',lambda c:[Damage(c.state.players[1].hero_id,7),Summon(1,'guard')])
        g=self.game(hand=('setup','hit'),board=()); self.play(g,'setup');self.play(g,'hit',self.hero(g).id)
        self.assertEqual((self.hero(g).health,self.hero(g).max_health,self.hero(g).damage),(26,33,7))
        self.assertFalse(self.events(g,'healed')); self.check(g)

    def test_partial_armor_only_replaces_remainder(self):
        g=self.game(hand=('hit',),armor=2);self.play(g,'hit',self.hero(g).id)
        self.assertEqual((self.hero(g).health,self.hero(g).armor),(31,0))
        self.assertEqual(self.events(g,'health_loss_replaced')[0].amount,1)

    def test_full_armor_prevents_any_growth(self):
        g=self.game(hand=('hit',),armor=5);self.play(g,'hit',self.hero(g).id)
        self.assertEqual((self.hero(g).health,self.hero(g).armor),(30,2))
        self.assertFalse(self.events(g,'max_health_gained'))

    def test_zero_loss_is_inert(self):
        self.spell('zero',lambda c:[Damage(c.state.players[1].hero_id,0),LoseHealth(c.state.players[1].hero_id,0),GainMaxHealth(1,0)])
        g=self.game(hand=('zero',)); self.play(g,'zero')
        self.assertEqual(self.hero(g).max_health,30);self.assertFalse(self.events(g,'max_health_gained'))

    def test_immunity_prevents_before_replacement(self):
        self.spell('protect',lambda c:[GrantKeyword(c.state.players[1].hero_id,Keyword.IMMUNE)])
        g=self.game(hand=('protect','hit'));self.play(g,'protect');self.play(g,'hit',self.hero(g).id)
        self.assertEqual(self.hero(g).health,30);self.assertFalse(self.events(g,'health_loss_replaced'))

    def test_divine_shield_is_consumed_before_replacement(self):
        self.spell('protect',lambda c:[GrantKeyword(c.state.players[1].hero_id,Keyword.DIVINE_SHIELD)])
        g=self.game(hand=('protect','hit','hit'));self.play(g,'protect')
        self.play(g,'hit',self.hero(g).id);self.assertEqual(self.hero(g).health,30)
        self.play(g,'hit',self.hero(g).id);self.assertEqual(self.hero(g).health,33)
        self.assertEqual(len(self.events(g,'shield_lost')),1)

    def test_health_rule_prevention_runs_first(self):
        self.minion('prevent',health=2,health_rules=(HealthRule(HealthFlow.DAMAGE,HealthOp.PREVENT,0),))
        g=self.game(hand=('hit',),board=('guard','prevent'));self.play(g,'hit',self.hero(g).id)
        self.assertEqual(self.hero(g).health,30)

    def test_spell_power_and_multiplier_precede_loss_replacement(self):
        self.minion('power',health=2,spell_damage=1,health_rules=(HealthRule(HealthFlow.DAMAGE,HealthOp.SCALE,2),))
        g=self.game(hand=('hit',),board=('guard','power'));self.play(g,'hit',self.hero(g).id)
        self.assertEqual(self.hero(g).health,38)

    def test_incoming_cap_precedes_replacement(self):
        self.minion('cap',health=2,health_rules=(HealthRule(HealthFlow.DAMAGE,HealthOp.CAP,1,layer=HealthLayer.TARGET),))
        g=self.game(hand=('hit',),board=('guard','cap'));self.play(g,'hit',self.hero(g).id)
        self.assertEqual(self.hero(g).health,31)

    def test_fatigue_enters_same_loss_path(self):
        self.spell('fatigue',lambda c:[Damage(c.state.players[1].hero_id,4,kind=DamageKind.FATIGUE)])
        g=self.game(hand=('fatigue',));self.play(g,'fatigue');self.assertEqual(self.hero(g).health,34)

    def test_opponent_turn_disables_replacement(self):
        g=self.game(enemy_hand=('hit',));g.apply(EndTurn(1));self.play(g,'hit',self.hero(g).id)
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(27,30)); self.check(g)

    def test_enemy_hero_not_protected_by_friendly_source(self):
        g=self.game(hand=('hit',));self.play(g,'hit',self.hero(g,2).id)
        self.assertEqual(self.hero(g,2).health,27)

    def test_replacement_does_not_protect_minions(self):
        g=self.game(hand=('hit','loss'));guard=self.board(g)[0]
        self.play(g,'hit',guard.id);self.play(g,'loss',guard.id)
        self.assertEqual(g.state.entities[guard.id].zone,Zone.GRAVEYARD)
        self.assertFalse(self.events(g,'health_loss_replaced'))

    def test_multiple_sources_consume_loss_only_once(self):
        g=self.game(hand=('hit',),board=('guard','guard'));self.play(g,'hit',self.hero(g).id)
        self.assertEqual(self.hero(g).health,33);self.assertEqual(len(self.events(g,'health_loss_replaced')),1)
        self.assertEqual(dict(self.events(g,'health_loss_replaced')[0].data)['replacement_source_id'],self.board(g)[0].id)

    def test_source_leaving_preserves_existing_growth(self):
        g=self.game(hand=('hit','kill','hit'));source=self.board(g)[0].id
        self.play(g,'hit',self.hero(g).id);self.play(g,'kill',source);self.play(g,'hit',self.hero(g).id)
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(30,33));self.check(g)

    def test_silence_bounce_transform_and_dormancy_revoke_aura(self):
        for action in ('silence','bounce','transform','sleep'):
            with self.subTest(action=action):
                self.setUp();g=self.game(hand=(action,'hit'))
                self.play(g,action,self.board(g)[0].id);self.play(g,'hit',self.hero(g).id)
                self.assertEqual(self.hero(g).health,27)

    def test_dormant_source_stays_out_of_ordinary_target_actions(self):
        g=self.game(hand=('sleep','wake','hit'));source=self.board(g)[0].id
        self.play(g,'sleep',source)
        # Ordinary target validation excludes dormant minions; use an explicit effect.
        self.assertNotIn(source,[a.target_id for a in g.legal_actions() if isinstance(a,PlayCard) and a.target_id])
        # A different active source can awaken via a non-targeted behavior (tested below).
        self.assertTrue(g.state.entities[source].dormancy)

    def test_untargeted_awaken_restores_source(self):
        self.spell('awaken',lambda c:[AwakenMinion(c.state.players[1].board[0])])
        g=self.game(hand=('sleep','awaken','hit'));self.play(g,'sleep',self.board(g)[0].id)
        self.play(g,'awaken');self.play(g,'hit',self.hero(g).id);self.assertEqual(self.hero(g).health,33)

    def test_control_change_tracks_current_controller_and_turn(self):
        g=self.game(hand=('steal','hit'),enemy_hand=('hit',));source=self.board(g)[0].id
        self.play(g,'steal',source);self.play(g,'hit',self.hero(g).id)
        g.apply(EndTurn(1));self.play(g,'hit',self.hero(g,2).id)
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(27,33));self.check(g)

    def test_copy_has_independent_ability_identity(self):
        g=self.game(hand=('copy','silence','hit'));source=self.board(g)[0].id
        self.play(g,'copy',source);self.play(g,'silence',source);self.play(g,'hit',self.hero(g).id)
        self.assertEqual(self.hero(g).health,33)
        self.assertEqual(dict(self.events(g,'health_loss_replaced')[0].data)['replacement_source_id'],self.board(g)[1].id)
        self.check(g)

    def test_same_batch_captures_source_before_it_dies(self):
        self.spell('batch',lambda c:[DamageBatch((Damage(c.state.players[1].board[0],99),Damage(c.state.players[1].hero_id,40)))])
        g=self.game(hand=('batch',));self.play(g,'batch')
        self.assertEqual(self.hero(g).health,70);self.assertFalse(self.board(g));self.assertEqual(g.state.status,'playing')
        self.check(g)

    def test_separate_effects_requery_after_source_dies(self):
        self.spell('sequence',lambda c:[Damage(c.state.players[1].board[0],99),Damage(c.state.players[1].hero_id,40)])
        g=self.game(hand=('sequence',));self.play(g,'sequence')
        self.assertEqual((g.state.status,g.state.winner),('finished',2));self.check(g)

    def test_repeated_packets_use_updated_armor(self):
        self.spell('batch',lambda c:[DamageBatch((Damage(c.state.players[1].hero_id,3),Damage(c.state.players[1].hero_id,3)))])
        g=self.game(hand=('batch',),armor=4);self.play(g,'batch')
        self.assertEqual((self.hero(g).health,self.hero(g).armor),(32,0))

    def test_direct_loss_bypasses_armor_and_protections(self):
        self.spell('protect',lambda c:[GrantKeyword(c.state.players[1].hero_id,Keyword.IMMUNE),GrantKeyword(c.state.players[1].hero_id,Keyword.DIVINE_SHIELD)])
        g=self.game(hand=('protect','loss'),armor=9);self.play(g,'protect');self.play(g,'loss',self.hero(g).id)
        self.assertEqual((self.hero(g).health,self.hero(g).armor),(33,9))
        self.assertIn(Keyword.DIVINE_SHIELD,self.hero(g).keywords);self.assertFalse(self.events(g,'damage_dealt'))

    def test_direct_loss_without_replacement_bypasses_armor(self):
        g=self.game(hand=('loss',),board=(),armor=9);self.play(g,'loss',self.hero(g).id)
        self.assertEqual((self.hero(g).health,self.hero(g).armor),(27,9))
        self.assertEqual(self.events(g,'health_lost')[0].amount,3)

    def test_direct_loss_can_kill_hero(self):
        self.spell('lethal',lambda c:[LoseHealth(c.state.players[1].hero_id,30)])
        g=self.game(hand=('lethal',),board=(),armor=99);self.play(g,'lethal')
        self.assertEqual(g.state.winner,2);self.check(g)

    def test_destroy_bypasses_replacement(self):
        g=self.game(hand=('kill',));self.play(g,'kill',self.hero(g).id)
        self.assertEqual(g.state.winner,2);self.assertFalse(self.events(g,'max_health_gained'))

    def test_max_health_gain_is_not_healing(self):
        self.spell('hurt',lambda c:[Damage(c.state.players[1].hero_id,7)])
        g=self.game(hand=('hurt','gain'),board=());self.play(g,'hurt');self.play(g,'gain')
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(26,33));self.assertFalse(self.events(g,'healed'))
        self.check(g)

    def test_healing_after_growth_restores_only_missing_health(self):
        self.spell('setup',lambda c:[Damage(c.state.players[1].hero_id,7),Summon(1,'guard')])
        self.spell('heal',lambda c:[Heal(c.state.players[1].hero_id,99)])
        g=self.game(hand=('setup','hit','heal'),board=());self.play(g,'setup');self.play(g,'hit',self.hero(g).id);self.play(g,'heal')
        self.assertEqual(self.hero(g).health,33);self.assertEqual(self.events(g,'healed')[0].amount,7)

    def test_lifesteal_uses_nominal_damage_under_provisional_contract(self):
        self.spell('setup',lambda c:[Damage(c.state.players[1].hero_id,10),Summon(1,'guard')])
        self.spell('drain',lambda c:[Damage(c.state.players[1].hero_id,3,c.source_id,DamageKind.SPELL)],keywords=(Keyword.LIFESTEAL,))
        g=self.game(hand=('setup','drain'),board=());self.play(g,'setup');self.play(g,'drain')
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(26,33))
        self.assertEqual(self.events(g,'lifesteal')[0].amount,3);self.check(g)

    def test_gain_event_can_trigger_without_healing_event(self):
        self.r.register_behavior('watch_gain',lambda c:[GainArmor(c.player_id,1)])
        self.r.register_behavior('watch_heal',lambda c:[GainArmor(c.player_id,10)])
        self.minion('watcher',health=2,triggers=(TriggerSpec('max_health_gained','watch_gain'),TriggerSpec('healed','watch_heal')))
        g=self.game(hand=('hit',),board=('guard','watcher'));self.play(g,'hit',self.hero(g).id)
        self.assertEqual(self.hero(g).armor,1)

    def test_payment_above_remaining_health_is_legal_and_grows(self):
        g=self.game(hand=('convert','expensive'),mana=0);self.play(g,'convert')
        card=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id=='expensive')
        self.assertIn(PlayCard(1,card),g.legal_actions());self.play(g,'expensive')
        self.assertEqual((self.hero(g).health,g.state.players[1].mana),(70,0))
        self.assertEqual(self.events(g,'health_spent')[0].amount,40)
        self.assertFalse(self.events(g,'damage_dealt'));self.assertEqual(len(g.state.play_history),2);self.check(g)

    def test_payment_uses_armor_before_growing(self):
        g=self.game(hand=('convert','expensive'),armor=11);self.play(g,'convert');self.play(g,'expensive')
        self.assertEqual((self.hero(g).health,self.hero(g).armor),(59,0))

    def test_payment_exact_or_above_life_rejected_without_aura(self):
        for amount in (30,40):
            with self.subTest(amount=amount):
                self.setUp();self.spell('cost',lambda c:[AddCostModifier(1,CostSpec(payment=PaymentType.HEALTH,set_to=amount),1)])
                g=self.game(hand=('cost','expensive'),board=());self.play(g,'cost');before=g.snapshot()
                with self.assertRaises(IllegalAction):self.play(g,'expensive')
                self.assertEqual(g.snapshot(),before)

    def test_payment_ignores_immunity_but_honors_loss_replacement(self):
        self.spell('protect',lambda c:[GrantKeyword(c.state.players[1].hero_id,Keyword.IMMUNE),AddCostModifier(1,CostSpec(payment=PaymentType.HEALTH),1)])
        g=self.game(hand=('protect','expensive'));self.play(g,'protect');self.play(g,'expensive')
        self.assertEqual(self.hero(g).health,70)

    def test_armor_payment_is_never_replaced(self):
        self.spell('armor_cost',lambda c:[AddCostModifier(1,CostSpec(payment=PaymentType.ARMOR),1)])
        g=self.game(hand=('armor_cost','expensive'),armor=40);self.play(g,'armor_cost');self.play(g,'expensive')
        self.assertEqual((self.hero(g).health,self.hero(g).armor),(30,0));self.assertFalse(self.events(g,'max_health_gained'))

    def test_guard_in_hand_cannot_protect_its_own_payment(self):
        self.spell('setup',lambda c:[Damage(c.state.players[1].hero_id,25),AddCostModifier(1,CostSpec(payment=PaymentType.HEALTH),1)])
        g=self.game(hand=('setup','CATA_155'),board=());self.play(g,'setup');before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'CATA_155')
        self.assertEqual(g.snapshot(),before)

    def test_filtered_dynamic_replacement_only_affects_payment(self):
        spec=HealthLossReplacementSpec(kinds=(HealthLossKind.PAYMENT,))
        self.spell('grant',lambda c:[GrantHealthLossReplacement(c.state.players[1].board[0],spec,c.source_id)])
        g=self.game(hand=('grant','hit','loss','convert','expensive'),board=('plain',));self.play(g,'grant')
        self.play(g,'hit',self.hero(g).id);self.play(g,'loss',self.hero(g).id)
        self.play(g,'convert');self.play(g,'expensive')
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(64,70));self.check(g)

    def test_unrestricted_spec_works_on_opponent_turn(self):
        self.minion('all_turns',health=3,health_loss_replacements=(HealthLossReplacementSpec(own_turn_only=False),))
        g=self.game(board=('all_turns',),enemy_hand=('hit',));g.apply(EndTurn(1));self.play(g,'hit',self.hero(g).id)
        self.assertEqual(self.hero(g).health,33)

    def test_dynamic_grant_expires_at_turn_end(self):
        self.spell('grant',lambda c:[GrantHealthLossReplacement(c.state.players[1].board[0],HealthLossReplacementSpec(),c.source_id,c.state.turn)])
        g=self.game(hand=('grant','hit','hit'),board=('plain',));self.play(g,'grant');self.play(g,'hit',self.hero(g).id)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,'hit',self.hero(g).id)
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(30,33));self.check(g)

    def test_hero_replacement_preserves_growth(self):
        self.spell('replace',lambda c:[ReplaceHero(1,'HERO_08')])
        g=self.game(hand=('hit','replace'));self.play(g,'hit',self.hero(g).id);self.play(g,'replace')
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(33,33));self.check(g)

    def test_pending_choice_restores_typed_loss_gain_and_grant(self):
        self.spell('choose',lambda c:[RequestChoice(1,(ChoiceOption('a','Grow',(
            GrantHealthLossReplacement(c.state.players[1].board[0],HealthLossReplacementSpec(),c.source_id),
            LoseHealth(c.state.players[1].hero_id,40,c.source_id),GainMaxHealth(1,2,c.source_id))),),c.source_id)])
        g=self.game(hand=('choose',),board=('plain',));self.play(g,'choose');self.check(g)
        restored=Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r)
        for game in (g,restored):
            choice=game.state.pending_choice;game.apply(SelectChoice(1,choice.id,('a',)))
            self.assertEqual(self.hero(game).health,72)
        self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)

    def test_invalid_attachment_source_rolls_back_growth_and_play(self):
        self.spell('bad',lambda c:[GainMaxHealth(1,2,c.source_id),LoseHealth(c.state.players[1].hero_id,2,999999)])
        g=self.game(hand=('bad',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)

    def test_invalid_specs_and_definition_holders_rejected(self):
        for fn in (lambda:HealthLossReplacementSpec(own_turn_only=1),lambda:HealthLossReplacementSpec(kinds=()),
                   lambda:HealthLossReplacementSpec(kinds=('payment',)),lambda:HealthLossReplacementSpec(kinds=(HealthLossKind.DAMAGE,)*2),
                   lambda:LoseHealth(1,True),lambda:GainMaxHealth(1,-1),
                   lambda:AbilityInstance(1,'keyword',health_loss_replacement=HealthLossReplacementSpec())):
            with self.subTest(fn=fn),self.assertRaises(ValueError):fn()
        with self.assertRaises(ValueError):
            self.r.register_card(CardDefinition('bad','bad',CardType.SPELL,health_loss_replacements=(HealthLossReplacementSpec(),)))

    def test_corrupted_snapshot_spec_rejected(self):
        g=self.game();snapshot=g.snapshot();guard=self.board(g)[0].id
        for field,value in (('own_turn_only',1),('kinds',['unknown']),('kinds',[])):
            data=json.loads(json.dumps(snapshot));data['state']['entities'][str(guard)]['abilities'][0]['health_loss_replacement'][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_old_snapshot_rejected(self):
        g=self.game();snapshot=g.snapshot();self.assertEqual(snapshot['schema_version'],266);snapshot['schema_version']=41
        with self.assertRaises(SnapshotError):Game.from_snapshot(snapshot,self.r)

    def test_real_body_generates_independent_limbs_and_health_cards(self):
        g=self.game(hand=('CATA_155',),board=());self.play(g,'CATA_155')
        self.assertEqual([e.card_id for e in self.board(g)],['CATA_155t','CATA_155','CATA_155t1'])
        self.assertEqual(len(g.state.players[1].hand),2)
        from hs_sim.engine.costs import quote_cost
        self.assertTrue(all(quote_cost(g.state,self.r,g.state.entities[i]).payment==PaymentType.HEALTH for i in g.state.players[1].hand))
        self.assertEqual(self.r.card('CATA_155').metadata.runes.blood,2);self.check(g)

    def test_real_body_without_generation_context_rolls_back(self):
        g=self.game(hand=('CATA_155',),board=(),context=False);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'CATA_155')
        self.assertEqual(g.snapshot(),before)

    def test_damage_converted_to_healing_never_becomes_loss(self):
        self.minion('converter',health=2,health_rules=(HealthRule(HealthFlow.DAMAGE,HealthOp.CONVERT),))
        self.spell('setup',lambda c:[LoseHealth(c.state.players[1].hero_id,7),Summon(1,'guard'),Summon(1,'converter')])
        g=self.game(hand=('setup','hit'),board=());self.play(g,'setup');self.play(g,'hit',self.hero(g).id)
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(26,30))
        self.assertFalse(self.events(g,'health_loss_replaced'))

    def test_healing_converted_to_damage_can_be_replaced(self):
        self.minion('converter',health=2,health_rules=(HealthRule(HealthFlow.HEALING,HealthOp.CONVERT),))
        self.spell('heal',lambda c:[Heal(c.state.players[1].hero_id,4,c.source_id)])
        g=self.game(hand=('heal',),board=('guard','converter'));self.play(g,'heal')
        self.assertEqual(self.hero(g).health,34);self.assertFalse(self.events(g,'healed'));self.check(g)

    def test_redirection_away_from_hero_runs_before_loss_replacement(self):
        self.minion('redirector',health=8,health_rules=(HealthRule(HealthFlow.DAMAGE,HealthOp.REDIRECT,
            layer=HealthLayer.TARGET,target_kinds=(CardType.HERO,),target_relation='friendly',redirect_to='self'),))
        g=self.game(hand=('hit',),board=('guard','redirector'));self.play(g,'hit',self.hero(g).id)
        self.assertEqual(self.hero(g).health,30);self.assertEqual(self.board(g)[1].health,5)
        self.assertFalse(self.events(g,'health_loss_replaced'))

    def test_redirection_to_protected_hero_replaces_final_loss(self):
        self.minion('redirector',health=8,health_rules=(HealthRule(HealthFlow.DAMAGE,HealthOp.REDIRECT,
            layer=HealthLayer.TARGET,target_kinds=(CardType.MINION,),target_relation='self',redirect_to='friendly_hero'),))
        g=self.game(hand=('hit',),board=('guard','redirector'));self.play(g,'hit',self.board(g)[1].id)
        self.assertEqual(self.hero(g).health,33);self.assertEqual(self.board(g)[1].health,8)

    def test_real_body_at_last_board_slot_keeps_aura_without_limbs(self):
        g=self.game(hand=('CATA_155','hit'),board=('plain',)*6);self.play(g,'CATA_155')
        self.assertEqual(len(self.board(g)),7);self.assertEqual(len(g.state.players[1].hand),1)
        self.play(g,'hit',self.hero(g).id);self.assertEqual(self.hero(g).health,33);self.check(g)

    def test_health_payment_is_available_through_player_port(self):
        g=self.game(hand=('convert','expensive'),mana=0);self.play(g,'convert')
        port=g.for_player(1);listing=port.legal_actions()
        own=next(p for p in listing['observation']['players'] if p['id']==1)
        ref=next(e['ref'] for e in own['hand'] if e['card_id']=='expensive')
        action=next(a for a in listing['actions'] if a['type']=='play_card' and a['card']==ref)
        self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted'])
        self.assertEqual(self.hero(g).health,70);self.check(g)

    def test_public_growth_events_exclude_internal_ability_and_attachment_ids(self):
        g=self.game(hand=('hit',),enemy_hand=('expensive',));self.play(g,'hit',self.hero(g).id)
        for viewer in (1,2):
            events=g.player_events(viewer)
            growth=[e for e in events if e['kind']=='max_health_gained']
            self.assertEqual([e['amount'] for e in growth],[3])
            serialized=json.dumps(events)
            for private in ('replacement_ability_id','enchantment_id','replacement_source_id','health_loss_replacement'):
                self.assertNotIn(private,serialized)
        self.assertNotIn('expensive',json.dumps(g.observe(1)))

    def test_snapshot_rejects_replacement_ability_on_hero(self):
        g=self.game();snapshot=g.snapshot();guard=self.board(g)[0].id;hero=self.hero(g).id
        entities=snapshot['state']['entities']
        ability=entities[str(guard)]['abilities'].pop(0)
        entities[str(hero)]['abilities'].append(ability)
        with self.assertRaises(SnapshotError):Game.from_snapshot(snapshot,self.r)

    def test_real_example_save_and_player_replay(self):
        from examples.onyxia_health_loss import run
        game,snapshot=run();self.assertEqual(snapshot['schema_version'],266)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].max_health,40)


if __name__=='__main__':unittest.main()
