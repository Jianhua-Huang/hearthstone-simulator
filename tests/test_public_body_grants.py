"""Public-body grants, real actions, lifecycle, choices and strict identities."""
import unittest

from hs_sim.engine import (BodyReference, GrantBattlecry, GrantCombo,
    RemoveGrantedBody, ConsumeGrantedBody)
from hs_sim.engine.actions import PlayCard, EndTurn, SelectChoice
from hs_sim.engine.effects import (GainArmor, Damage, RandomDamage, Draw, Silence,
    Transform, ReturnToHand, ChangeControl, CopyMinion, RequestChoice, ChoiceOption)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.game import Game, Scenario, PlayerSetup
from hs_sim.engine.model import CardDefinition, CardType, Keyword, Zone
from hs_sim.engine.registry import Registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard


def carrier(ctx):
    return next(e for e in ctx.state.entities.values() if e.card_id in (
        'unit', 'printed', 'target_unit', 'self_grant') and e.controller == ctx.player_id
        and e.zone in (Zone.HAND, Zone.DECK, Zone.BOARD))


def registry():
    r = Registry('public-body-grants-v1')
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30))
    for amount in (1, 2, 3, 4, 5):
        r.register_behavior('armor'+str(amount), lambda ctx, n=amount: (GainArmor(ctx.player_id, n),))
    r.register_behavior('strike', lambda ctx: (Damage(ctx.target_id, 2, ctx.source_id),))
    for name, bc, combo, targeted in (
        ('unit', None, None, False), ('printed', 'armor1', 'armor1', False),
        ('donor3', 'armor3', None, False), ('donor4', 'armor4', None, False),
        ('combo2', None, 'armor2', False), ('combo5', None, 'armor5', False),
        ('target_unit', None, None, True), ('target_donor', 'strike', None, True),
        ('other', None, None, False)):
        r.register_card(CardDefinition(name, name, CardType.MINION, cost=0, attack=1, health=3,
            battlecry=bc, combo=combo, requires_target=targeted,
            keywords=(Keyword.COMBO,) if combo else ()))
    def spell(name, fn, targeted=False):
        r.register_behavior(name, fn)
        r.register_card(CardDefinition(name, name, CardType.SPELL, cost=0, on_play=name,
            requires_target=targeted))
    def both(ctx):
        ref = BodyReference.capture(carrier(ctx))
        return (GrantBattlecry(ref, 'donor3', ctx.source_id), GrantCombo(ref, 'combo2', ctx.source_id))
    spell('grant', both)
    spell('stack', lambda ctx: (*both(ctx), GrantBattlecry(BodyReference.capture(carrier(ctx)), 'donor4', ctx.source_id),
        GrantCombo(BodyReference.capture(carrier(ctx)), 'combo5', ctx.source_id)))
    spell('temporary', lambda ctx: (GrantBattlecry(BodyReference.capture(carrier(ctx)), 'donor3', ctx.source_id, ctx.state.turn),
        GrantCombo(BodyReference.capture(carrier(ctx)), 'combo2', ctx.source_id, ctx.state.turn)))
    spell('target_grant', lambda ctx: (GrantBattlecry(BodyReference.capture(carrier(ctx)), 'target_donor', ctx.source_id),))
    spell('draw', lambda ctx: (Draw(ctx.player_id),))
    spell('copy_current', lambda ctx: (CopyCard(CardReference.capture(carrier(ctx)), ctx.player_id),))
    spell('copy_base', lambda ctx: (CopyCard(CardReference.capture(carrier(ctx)), ctx.player_id, mode='base'),))
    spell('board_copy', lambda ctx: (CopyMinion(ctx.target_id, ctx.player_id),), True)
    spell('silence', lambda ctx: (Silence(ctx.target_id),), True)
    spell('transform', lambda ctx: (Transform(ctx.target_id, 'other'),), True)
    spell('return', lambda ctx: (ReturnToHand(ctx.target_id),), True)
    spell('control', lambda ctx: (ChangeControl(ctx.target_id, 2),), True)
    def mutation(ctx, consume=False, wrong=False):
        entity = carrier(ctx)
        ability = next(a for a in entity.abilities if a.kind == 'battlecry' and a.origin == 'granted')
        kind = ConsumeGrantedBody if consume else RemoveGrantedBody
        return (kind(BodyReference.capture(entity), ability.id, 'combo' if wrong else 'battlecry', ctx.source_id),)
    spell('remove', mutation)
    spell('consume', lambda ctx: mutation(ctx, True))
    spell('wrong_family', lambda ctx: mutation(ctx, wrong=True))
    def queued(ctx):
        ref = BodyReference.capture(carrier(ctx))
        return (RequestChoice(ctx.player_id, (ChoiceOption('go', 'Go'),), ctx.source_id),
            GrantBattlecry(ref, 'donor3', ctx.source_id), GrantCombo(ref, 'combo2', ctx.source_id))
    spell('queued', queued)
    def stale(ctx):
        entity = carrier(ctx); ref = BodyReference.capture(entity)
        return (MoveCard(CardReference.capture(entity), ctx.player_id, Zone.DECK),
            GrantBattlecry(ref, 'donor3', ctx.source_id), GrantCombo(ref, 'combo2', ctx.source_id))
    spell('stale', stale)
    for name, declaration, family in (
        ('unknown', 'missing', GrantBattlecry), ('no_family', 'unit', GrantBattlecry),
        ('wrong_declaration', 'donor3', GrantCombo)):
        spell(name, lambda ctx, d=declaration, f=family: (RandomDamage((ctx.state.players[1].hero_id, ctx.state.players[2].hero_id), 1, source_id=ctx.source_id),
            f(BodyReference.capture(carrier(ctx)), d, ctx.source_id)))
    r.register_behavior('self_grant', lambda ctx: (GrantBattlecry(BodyReference.capture(ctx.source), 'donor3', ctx.source_id),
        GrantCombo(BodyReference.capture(ctx.source), 'combo2', ctx.source_id)))
    r.register_card(CardDefinition('self_grant', 'Self grant', CardType.MINION, attack=1, health=3,
        battlecry='self_grant'))
    return r


class PublicBodyGrantTests(unittest.TestCase):
    def game(self, hand=(), board=(), deck=()):
        return Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, board=board, deck=deck, mana=10, max_mana=10),
            PlayerSetup('hero', mana=10, max_mana=10)), seed=37), registry())

    def play(self, game, name, target=None):
        s=game.state; i=next(i for i in s.players[1].hand if s.entities[i].card_id==name)
        game.apply(PlayCard(1,i,target)); return i

    def bodies(self, game, entity_id):
        return [a for a in game.state.entities[entity_id].abilities if a.kind in ('battlecry','combo')]

    def unit(self, game, zone=Zone.HAND):
        return next(e.id for e in game.state.entities.values()if e.card_id in ('unit','printed','target_unit')and e.zone==zone)

    def armor(self, game, player=1):
        s=game.state; return s.entities[s.players[player].hero_id].armor

    def test_hand_grants_execute_complete_bodies_without_combo_label(self):
        g=self.game(('grant','unit')); unit=self.unit(g); source=self.play(g,'grant')
        bodies=self.bodies(g,unit); self.assertEqual([a.kind for a in bodies],['battlecry','combo'])
        self.assertEqual([a.source_id for a in bodies],[source,source])
        self.assertEqual([a.origin for a in bodies],['granted','granted'])
        self.assertNotIn(Keyword.COMBO,g.state.entities[unit].keywords)
        self.play(g,'unit'); self.assertEqual(self.armor(g),5)
        self.assertEqual([b.payload.ability_id for b in g.state.battlecry_history],[bodies[0].id])
        self.assertEqual([b.payload.ability_id for b in g.state.combo_history],[bodies[1].id])

    def test_stacked_declarations_preserve_order_and_independent_ids(self):
        g=self.game(('stack','unit')); unit=self.unit(g);self.play(g,'stack')
        bodies=self.bodies(g,unit); self.assertEqual(len({a.id for a in bodies}),4)
        self.play(g,'unit');self.assertEqual(self.armor(g),14)
        self.assertEqual([b.payload.card_id for b in g.state.battlecry_history],['donor3','donor4'])
        self.assertEqual([b.payload.card_id for b in g.state.combo_history],['combo2','combo5'])

    def test_printed_and_granted_bodies_share_existing_dispatcher(self):
        g=self.game(('grant','printed'));unit=self.unit(g);self.play(g,'grant')
        self.assertEqual([a.origin for a in self.bodies(g,unit)],['printed','printed','granted','granted'])
        self.play(g,'printed');self.assertEqual(self.armor(g),7)

    def test_deck_grants_survive_draw_and_real_hand_play(self):
        g=self.game(('grant','draw'),deck=('unit',));unit=self.unit(g,Zone.DECK)
        self.play(g,'grant');ids=[a.id for a in self.bodies(g,unit)]
        self.play(g,'draw');self.assertEqual([a.id for a in self.bodies(g,unit)],ids)
        self.play(g,'unit');self.assertEqual(self.armor(g),5)

    def test_compatible_targeted_body_uses_legal_real_action_target(self):
        g=self.game(('target_grant','target_unit'));self.play(g,'target_grant')
        enemy=g.state.players[2].hero_id;self.play(g,'target_unit',enemy)
        self.assertEqual(g.state.entities[enemy].health,28)

    def test_distinct_target_contract_is_explicit_error_and_rolls_back(self):
        g=self.game(('target_grant','unit'));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'heterogeneous target dispatcher'):self.play(g,'target_grant')
        self.assertEqual(g.snapshot(),before)

    def test_current_copy_has_independent_ids_and_base_copy_has_no_grants(self):
        g=self.game(('grant','copy_current','copy_base','unit'));unit=self.unit(g);self.play(g,'grant')
        original=self.bodies(g,unit);self.play(g,'copy_current');self.play(g,'copy_base')
        units=[e.id for e in g.state.entities.values()if e.card_id=='unit'and e.zone==Zone.HAND]
        self.assertEqual([len(self.bodies(g,i))for i in units],[2,2,0])
        copied=self.bodies(g,units[1]);self.assertTrue(set(a.id for a in original).isdisjoint(a.id for a in copied))
        self.assertEqual([(a.behavior_id,a.source_id)for a in copied],[(a.behavior_id,a.source_id)for a in original])

    def test_board_grant_copy_and_transfer_do_not_invoke_bodies(self):
        g=self.game(('grant','board_copy','control'),board=('unit',));unit=self.unit(g,Zone.BOARD)
        source=self.play(g,'grant');self.play(g,'board_copy',unit);self.play(g,'control',unit)
        self.assertEqual(self.armor(g),0);self.assertEqual(len(g.state.battlecry_history),0)
        copy=g.state.players[1].board[0];self.assertEqual(len(self.bodies(g,copy)),2)
        self.assertEqual(g.state.entities[unit].controller,2)
        self.assertEqual([a.source_id for a in self.bodies(g,unit)],[source,source])

    def test_silence_removes_granted_and_printed_bodies(self):
        g=self.game(('grant','silence'),board=('printed',));unit=self.unit(g,Zone.BOARD)
        self.play(g,'grant');self.play(g,'silence',unit);self.assertEqual(self.bodies(g,unit),[])

    def test_transform_resets_declaration_and_granted_identity(self):
        g=self.game(('grant','transform'),board=('unit',));unit=self.unit(g,Zone.BOARD)
        self.play(g,'grant');self.play(g,'transform',unit)
        self.assertEqual(self.bodies(g,unit),[]);self.assertEqual(g.state.entities[unit].card_id,'other')

    def test_return_to_hand_uses_existing_reset_policy(self):
        g=self.game(('grant','return'),board=('unit',));unit=self.unit(g,Zone.BOARD)
        self.play(g,'grant');self.play(g,'return',unit)
        self.assertEqual(self.bodies(g,unit),[]);self.play(g,'unit');self.assertEqual(self.armor(g),0)

    def test_expiry_cleans_stored_and_board_grants(self):
        for zone in ('hand','board','deck'):
            with self.subTest(zone=zone):
                kwargs={zone:('unit',)};kwargs['hand']=('temporary',)+kwargs.get('hand',())
                g=self.game(**kwargs);unit=next(e.id for e in g.state.entities.values()if e.card_id=='unit')
                self.play(g,'temporary');self.assertEqual(len(self.bodies(g,unit)),2)
                g.apply(EndTurn(1));self.assertEqual(self.bodies(g,unit),[])

    def test_consumption_and_removal_affect_only_exact_granted_family(self):
        g=self.game(('grant','consume','remove','unit'));unit=self.unit(g);self.play(g,'grant')
        self.play(g,'consume');self.assertEqual([a.consumed for a in self.bodies(g,unit)],[True,False])
        self.play(g,'remove');self.assertEqual([a.kind for a in self.bodies(g,unit)],['combo'])
        self.play(g,'unit');self.assertEqual(self.armor(g),2)

    def test_cross_family_identity_mutation_rejects_and_rolls_back(self):
        g=self.game(('grant','wrong_family','unit'));self.play(g,'grant');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'exact family'):self.play(g,'wrong_family')
        self.assertEqual(g.snapshot(),before)

    def test_captured_reference_cannot_follow_card_across_zones(self):
        g=self.game(('stale','unit'));unit=self.unit(g);self.play(g,'stale')
        self.assertEqual(g.state.entities[unit].zone,Zone.DECK);self.assertEqual(self.bodies(g,unit),[])
        self.assertEqual(sum(e.kind=='zone_target_skipped'for e in g.events),2)

    def test_waiting_queued_grants_restore_clone_and_independent_replay(self):
        g=self.game(('queued','unit'));initial=g.snapshot();actions=[]
        s=g.state;eid=next(i for i in s.players[1].hand if s.entities[i].card_id=='queued')
        action=PlayCard(1,eid);g.apply(action);actions.append(action);snap=g.snapshot()
        self.assertIsNotNone(g.state.pending_choice)
        restored=Game.from_snapshot(snap,registry());cloned=g.clone();rerun=replay(build_replay(g),registry())
        for other in (restored,cloned,rerun):self.assertEqual(other.snapshot(),snap)
        action=SelectChoice(1,g.state.pending_choice.id,('go',));g.apply(action);actions.append(action)
        for other in (restored,cloned,rerun):other.apply(action);self.assertEqual(other.snapshot(),g.snapshot())
        unit=self.unit(g);action=PlayCard(1,unit);g.apply(action);actions.append(action)
        self.assertEqual(self.armor(g),5)
        final=replay(build_replay(g),registry());self.assertEqual(final.snapshot(),g.snapshot())

    def test_unknown_or_wrong_declaration_after_random_damage_rolls_back(self):
        for name in ('unknown','no_family','wrong_declaration'):
            with self.subTest(name=name):
                g=self.game((name,'unit'));before=g.snapshot()
                with self.assertRaises((ResolutionError,KeyError,ValueError)):self.play(g,name)
                self.assertEqual(g.snapshot(),before)

    def test_late_self_grant_does_not_modify_accepted_original_batch(self):
        g=self.game(('self_grant',));unit=self.play(g,'self_grant')
        self.assertEqual(self.armor(g),0);self.assertEqual(len(self.bodies(g,unit)),3)
        self.assertEqual([b.payload.card_id for b in g.state.battlecry_history],['self_grant'])
        self.assertEqual(g.state.combo_history,[])

    def test_strict_references_and_mutation_identity_values(self):
        g=self.game(('unit',));ref=BodyReference.capture(g.state.entities[self.unit(g)])
        for operation in (lambda: GrantBattlecry(None,'donor3'), lambda: GrantCombo(ref,''),
                lambda: ConsumeGrantedBody(ref,True,'combo'), lambda: RemoveGrantedBody(ref,1,'deathrattle'),
                lambda: BodyReference(ref.entity_id,1,Zone.GRAVEYARD,'unit',0)):
            with self.assertRaises(ValueError):operation()

    def test_new_snapshot_schema_rejects_prior_wire(self):
        g=self.game(('grant','unit'));self.play(g,'grant');snapshot=g.snapshot()
        self.assertEqual(snapshot['schema_version'],266)
        self.assertEqual(Game.from_snapshot(snapshot,registry()).snapshot(),snapshot)
        snapshot['schema_version']=119
        with self.assertRaises(SnapshotError):Game.from_snapshot(snapshot,registry())
