"""Real public grants and player isolation, independent of grant-test fixtures."""
from copy import deepcopy
import json
import unittest

from hs_sim.engine import (BodyReference, GrantBattlecry, GrantCombo, ConsumeGrantedBody,
    RemoveGrantedBody, CardDefinition, CardType, Keyword, Zone, TargetSpec, TargetMode,
    Game, Scenario, PlayerSetup, PlayCard, EndTurn, SelectChoice, SnapshotError, ResolutionError)
from hs_sim.engine.effects import (GainArmor, Damage, RandomDamage, Silence, Transform,
    ReturnToHand, ChangeControl, CopyMinion, RequestChoice, ChoiceOption, RevealHandCard, Draw)
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.engine.registry import Registry
from hs_sim.engine.replay import build_replay, replay


def registry():
    r = Registry('body-view-fixtures-v1')
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30))
    r.register_behavior('private.armor3', lambda c: (GainArmor(c.player_id, 3),))
    r.register_behavior('private.armor7', lambda c: (GainArmor(c.player_id, 7),))
    r.register_behavior('private.combo2', lambda c: (GainArmor(c.player_id, 2),))
    r.register_behavior('private.strike', lambda c: (Damage(c.target_id, 1, c.source_id),))
    for name, bc, co in (('unit', None, None), ('bc3', 'private.armor3', None),
                        ('bc7', 'private.armor7', None), ('co2', None, 'private.combo2'),
                        ('printed', 'private.armor3', 'private.combo2')):
        r.register_card(CardDefinition(name, name, CardType.MINION, attack=1, health=5,
            battlecry=bc, combo=co, keywords=(Keyword.COMBO,) if co else ()))
    for name in ('target_unit', 'target_donor'):
        r.register_card(CardDefinition(name, name, CardType.MINION, attack=1, health=5,
            battlecry='private.strike' if name == 'target_donor' else None,
            targeting=TargetSpec(TargetMode.IF_AVAILABLE, (Zone.BOARD,), (CardType.MINION,), 'enemy'),
            target_condition='manathirst', manathirst=5, keywords=(Keyword.MANATHIRST,)))
    r.register_card(CardDefinition('sleep', 'Sleep', CardType.MINION, attack=1, health=5, dormant_turns=2))
    r.register_card(CardDefinition('weapon', 'Weapon', CardType.WEAPON, attack=1, durability=3, battlecry='private.armor3'))
    r.register_card(CardDefinition('power', 'Power', CardType.HERO_POWER, on_use='private.armor3'))
    r.register_card(CardDefinition('hero_card', 'Hero card', CardType.HERO, hero_card=True,
        health=30, hero_armor=5, initial_hero_power='power', battlecry='private.armor3'))

    def unit(c, player=None, zone=None):
        owner = c.player_id if player is None else player
        return next(e for e in c.state.entities.values() if e.controller == owner and
            e.card_id in ('unit', 'printed', 'target_unit', 'sleep') and
            e.zone in ((zone,) if zone is not None else (Zone.HAND, Zone.BOARD, Zone.DECK)))

    def spell(name, fn, targeted=False):
        r.register_behavior(name, fn)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, requires_target=targeted))

    def grant(c, expiry=None, chosen=None, waiting=False):
        ref = BodyReference.capture(unit(c))
        effects = (GrantBattlecry(ref, chosen or 'bc3', c.source_id, expiry),
                   GrantCombo(ref, 'co2', c.source_id, expiry))
        return (RequestChoice(c.player_id, (ChoiceOption('yes', 'Yes'),), c.source_id), *effects) if waiting else effects

    spell('grant', grant)
    spell('stack', lambda c: (*grant(c), GrantBattlecry(BodyReference.capture(unit(c)), 'bc7', c.source_id)))
    spell('temporary', lambda c: grant(c, c.state.turn))
    spell('queued', lambda c: grant(c, waiting=True))
    spell('target_grant', lambda c: (GrantBattlecry(BodyReference.capture(unit(c)), 'target_donor', c.source_id),))
    spell('enemy_grant', lambda c: (GrantBattlecry(BodyReference.capture(unit(c, 2, Zone.HAND)),
        c.state.entities[c.state.players[2].deck[0]].card_id, c.source_id),))
    spell('reveal', lambda c: (RevealHandCard(unit(c, 2, Zone.HAND).id),))
    spell('draw', lambda c: (Draw(c.player_id),))
    spell('silence', lambda c: (Silence(c.target_id),), True)
    spell('transform', lambda c: (Transform(c.target_id, 'unit'),), True)
    spell('return', lambda c: (ReturnToHand(c.target_id),), True)
    spell('control', lambda c: (ChangeControl(c.target_id, 2),), True)
    spell('copy_board', lambda c: (CopyMinion(c.target_id, c.player_id),), True)
    spell('copy_current', lambda c: (CopyCard(CardReference.capture(unit(c)), c.player_id),))
    spell('copy_base', lambda c: (CopyCard(CardReference.capture(unit(c)), c.player_id, mode='base'),))
    spell('to_deck', lambda c: (MoveCard(CardReference.capture(unit(c)), c.player_id, Zone.DECK),))
    def mutate(c, consume):
        e = unit(c)
        a = next(a for a in e.abilities if a.kind == 'battlecry' and a.origin == 'granted')
        return ((ConsumeGrantedBody if consume else RemoveGrantedBody)(BodyReference.capture(e), a.id, 'battlecry', c.source_id),)
    spell('consume', lambda c: mutate(c, True))
    spell('remove', lambda c: mutate(c, False))
    spell('invalid', lambda c: (RandomDamage((c.state.players[1].hero_id, c.state.players[2].hero_id), 1),
        GrantBattlecry(BodyReference.capture(unit(c)), 'missing', c.source_id)))
    return r


class PublicBodyViewTests(unittest.TestCase):
    def game(self, hand=(), board=(), deck=(), enemy_hand=(), enemy_deck=('bc3',), weapon=None):
        return Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, board=board, deck=deck,
            weapon_card_id=weapon, mana=10, max_mana=10), PlayerSetup('hero', hand=enemy_hand,
            deck=enemy_deck, mana=10, max_mana=10)), seed=41), registry())

    def play(self, g, name, target=None):
        s = g.state
        entity = next(s.entities[i] for i in s.players[1].hand if s.entities[i].card_id == name)
        g.apply(PlayCard(1, entity.id, target))
        return entity.id

    def find(self, g, name='unit', zone=Zone.HAND, player=1):
        return next(e.id for e in g.state.entities.values() if e.card_id == name and e.zone == zone and e.controller == player)

    def card(self, g, viewer=1, player=1, zone='hand', name='unit'):
        p = g.for_player(viewer).observe()['observation']['players'][player - 1]
        cards = p[zone] if isinstance(p[zone], list) else [p[zone]]
        return next(c for c in cards if c and c['card_id'] == name)

    def bodies(self, g, **kwargs):
        return self.card(g, **kwargs)['bodies']

    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        for other in (Game.from_snapshot(snap, registry()), g.clone(), replay(build_replay(g), registry())):
            self.assertEqual(other.snapshot(), g.snapshot())
            for viewer in (1, 2):
                self.assertEqual(other.for_player(viewer).observe(), g.for_player(viewer).observe())
                self.assertEqual(other.for_player(viewer).legal_actions(), g.for_player(viewer).legal_actions())

    def test_own_hand_describes_ordered_complete_grants_without_private_ids(self):
        g = self.game(('stack', 'unit')); self.play(g, 'stack')
        bodies = self.bodies(g)
        self.assertEqual([(b['position'], b['family'], b['card_id']) for b in bodies],
            [(1, 'battlecry', 'bc3'), (2, 'combo', 'co2'), (3, 'battlecry', 'bc7')])
        self.assertTrue(all(set(b) == {'position','family','card_id','origin','consumed','expires_turn','target'} for b in bodies))
        self.assertTrue(all(b['origin'] == 'granted' and not b['consumed'] for b in bodies))
        wire = json.dumps(g.for_player(1).observe())
        for forbidden in ('private.armor', 'private.combo', 'ability_id', 'source_id', 'zone_epoch', 'acceptance', 'rng_state'):
            self.assertNotIn(forbidden, wire)
        self.portable(g)

    def test_printed_and_granted_duplicates_preserve_separate_visible_positions(self):
        g = self.game(('grant', 'printed')); self.play(g, 'grant')
        bodies = self.bodies(g, name='printed')
        self.assertEqual([b['origin'] for b in bodies], ['printed','printed','granted','granted'])
        self.assertEqual([b['card_id'] for b in bodies], ['printed','printed','bc3','co2'])
        self.assertEqual([b['position'] for b in bodies], [1,2,3,4])

    def test_remembered_enemy_hand_identity_does_not_authorize_dynamic_bodies(self):
        games = [self.game(('reveal','enemy_grant'), enemy_hand=('unit',), enemy_deck=(d,)) for d in ('bc3','bc7')]
        for g in games:
            self.play(g, 'reveal'); self.play(g, 'enemy_grant')
            enemy = self.card(g, player=2)
            self.assertEqual(set(enemy), {'ref','card_id'})
            self.assertEqual(enemy['card_id'], 'unit')
        self.assertEqual(games[0].for_player(1).observe(), games[1].for_player(1).observe())
        self.assertEqual(games[0].for_player(1).legal_actions(), games[1].for_player(1).legal_actions())
        self.assertNotEqual(self.bodies(games[0], viewer=2, player=2), self.bodies(games[1], viewer=2, player=2))
        for g in games: self.portable(g)

    def test_unknown_enemy_hand_does_not_expose_body_count_or_declarations(self):
        g = self.game(('enemy_grant',), enemy_hand=('unit',)); self.play(g, 'enemy_grant')
        enemy = g.for_player(1).observe()['observation']['players'][1]['hand'][0]
        self.assertEqual(enemy, {'ref': enemy['ref'], 'card_id': None})
        self.assertEqual(self.bodies(g, viewer=2, player=2)[0]['card_id'], 'bc3')

    def test_public_board_bodies_are_the_same_to_both_players(self):
        g = self.game(('grant','unit')); self.play(g,'grant'); self.play(g,'unit')
        self.assertEqual(self.bodies(g,zone='board'), self.bodies(g,viewer=2,zone='board'))
        self.assertEqual([b['family'] for b in self.bodies(g,zone='board')], ['battlecry','combo'])
        self.portable(g)

    def test_consumed_stored_body_is_distinct_from_removed_body(self):
        g = self.game(('grant','consume','remove','unit')); self.play(g,'grant'); self.play(g,'consume')
        self.assertEqual([b['consumed'] for b in self.bodies(g)], [True,False])
        self.play(g,'remove')
        self.assertEqual([(b['position'],b['family']) for b in self.bodies(g)], [(1,'combo')])
        self.portable(g)

    def test_silence_and_transform_follow_actual_attachment_lifecycle(self):
        for operation in ('silence','transform'):
            with self.subTest(operation=operation):
                g = self.game(('grant',operation,'unit')); self.play(g,'grant'); unit=self.play(g,'unit')
                self.play(g,operation,unit)
                self.assertEqual(self.bodies(g,zone='board'), [])
                self.portable(g)

    def test_bounce_resets_grants_without_revealing_hidden_followup_details(self):
        g = self.game(('grant','return','unit')); self.play(g,'grant'); unit=self.play(g,'unit'); self.play(g,'return',unit)
        self.assertEqual(self.bodies(g), [])
        self.assertEqual(set(self.card(g,viewer=2)), {'ref','card_id'})
        self.portable(g)

    def test_current_copy_keeps_bodies_and_base_copy_installs_only_printed_bodies(self):
        for operation, expected in (('copy_current',2),('copy_base',0)):
            with self.subTest(operation=operation):
                g = self.game(('grant',operation,'unit')); self.play(g,'grant'); self.play(g,operation)
                cards = [c for c in g.observe(1)['players'][0]['hand'] if c['card_id']=='unit']
                self.assertEqual([len(c['bodies']) for c in cards], [2,expected])
                self.assertEqual([b['position'] for b in cards[1]['bodies']], list(range(1,expected+1)))
                self.portable(g)

    def test_control_transfer_and_board_copy_preserve_public_descriptions(self):
        g = self.game(('grant','copy_board','control','unit')); self.play(g,'grant'); unit=self.play(g,'unit')
        original=self.bodies(g,zone='board'); self.play(g,'copy_board',unit)
        self.assertEqual([c['bodies'] for c in g.observe(2)['players'][0]['board']], [original,original])
        self.play(g,'control',unit)
        self.assertEqual(self.bodies(g,player=2,zone='board'),original)
        self.portable(g)

    def test_deck_has_no_body_view_then_actual_draw_exposes_owners_bodies(self):
        g = self.game(('grant','draw'), deck=('unit',)); self.play(g,'grant')
        for viewer in (1,2):
            self.assertNotIn('deck',g.observe(viewer)['players'][0])
        self.play(g,'draw')
        self.assertEqual(len(self.bodies(g)),2)
        self.assertNotIn('bodies',g.observe(2)['players'][0]['hand'][0])
        self.portable(g)

    def test_physical_move_to_deck_retires_handle_and_does_not_publish_body_metadata(self):
        g = self.game(('grant','to_deck','draw','unit')); self.play(g,'grant')
        old_ref=self.card(g)['ref']; self.play(g,'to_deck')
        self.assertNotIn(old_ref,json.dumps(g.for_player(2).observe()))
        self.play(g,'draw')
        self.assertNotEqual(self.card(g)['ref'],old_ref)
        self.assertEqual(len(self.bodies(g)),2)
        self.portable(g)

    def test_expiration_removes_current_body_descriptions(self):
        g=self.game(('temporary','unit')); self.play(g,'temporary')
        self.assertEqual([b['expires_turn'] for b in self.bodies(g)],[1,1])
        g.apply(EndTurn(1)); self.assertEqual(self.bodies(g),[]); self.portable(g)

    def test_dormant_carrier_describes_stored_bodies_without_claiming_activation(self):
        g=self.game(('grant',),board=('sleep',)); self.play(g,'grant')
        bodies=self.bodies(g,zone='board',name='sleep')
        self.assertEqual(len(bodies),2); self.assertEqual(self.bodies(g,viewer=2,zone='board',name='sleep'),bodies)
        self.assertNotIn('active',bodies[0]); self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
        self.portable(g)

    def test_weapon_and_hero_card_public_bodies_use_declarations(self):
        g=self.game(('hero_card',),weapon='weapon')
        self.assertEqual(self.bodies(g,zone='weapon',name='weapon')[0]['card_id'],'weapon')
        self.assertEqual(self.bodies(g,name='hero_card')[0]['card_id'],'hero_card')
        self.play(g,'hero_card')
        self.assertEqual(self.bodies(g,viewer=2,zone='hero',name='hero_card')[0]['family'],'battlecry')
        self.portable(g)

    def test_target_description_uses_public_domain_and_condition_not_rule_identifiers(self):
        g=self.game(('target_grant','target_unit')); self.play(g,'target_grant')
        target=self.bodies(g,name='target_unit')[0]['target']
        self.assertEqual(target,{'mode':'if_available','zones':['board'],'kinds':['minion'],
            'relation':'enemy','exclude_source':True,'condition':'manathirst','manathirst':5})
        self.assertNotIn('target_rule',json.dumps(target)); self.portable(g)

    def test_real_queued_grant_waiting_restores_and_player_command_continues(self):
        g=self.game(('queued','unit')); self.play(g,'queued')
        self.assertEqual(self.bodies(g),[]); self.portable(g)
        port=g.for_player(1); listing=port.legal_actions()
        command=next(a for a in listing['actions'] if a['type']=='select_choice')
        self.assertTrue(port.submit({'revision':listing['revision'],'action':command})['accepted'])
        self.assertEqual(len(self.bodies(g)),2); self.portable(g)

    def test_failed_public_grant_rolls_back_players_state_and_rng(self):
        g=self.game(('invalid','unit')); before=g.snapshot(); ports=[g.for_player(v).observe() for v in (1,2)]
        with self.assertRaises(ResolutionError): self.play(g,'invalid')
        self.assertEqual(g.snapshot(),before)
        self.assertEqual([g.for_player(v).observe() for v in (1,2)],ports)

    def test_detached_projection_cannot_mutate_live_bodies_or_revision(self):
        g=self.game(('grant','unit')); self.play(g,'grant'); before=g.snapshot(); listing=g.for_player(1).observe()
        body=self.bodies(g); body[0]['card_id']='bc7'; body.append(deepcopy(body[0]))
        self.assertEqual(g.snapshot(),before); self.assertEqual(g.for_player(1).observe(),listing)

    def test_observation_and_old_snapshot_versions_are_explicit(self):
        g=self.game(('unit',)); self.assertEqual(g.observe(1)['version'],'player-view-v84')
        self.assertEqual(g.snapshot()['schema_version'],265)
        old=g.snapshot(); old['schema_version']=120
        with self.assertRaises(SnapshotError): Game.from_snapshot(old,registry())
