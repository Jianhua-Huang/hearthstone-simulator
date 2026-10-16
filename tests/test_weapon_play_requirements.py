"""Equipment prerequisites protect real manual routes without locking storage/casts."""
from dataclasses import replace
from copy import deepcopy
import unittest

from hs_sim.engine import (CardDefinition,CardType,Game,PlayCard,PlayerSetup,Registry,
    Scenario,SelectChoice,TriggerSpec)
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Destroy,GainArmor,InvokeBehavior,
    ModifyWeapon,RequestChoice)
from hs_sim.engine.errors import IllegalAction,ResolutionError,SnapshotError
from hs_sim.engine.hand_upgrades import UpgradeHandCard
from hs_sim.engine.model import Zone
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.resolver import PlayFromHand
from hs_sim.engine.resolver import Resolution
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.play_history import prepare_play
from hs_sim.engine.spell_cost_proof import capture_hand_cost_proof,validate_hand_cost_proof
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference


def registry(wait=False):
    r=Registry('weapon-prerequisite-tests-v1')
    r.register_card(CardDefinition('wp.hero','Hero',CardType.HERO,health=30))
    r.register_card(CardDefinition('wp.weapon','Zero attack weapon',CardType.WEAPON,durability=2))
    r.register_behavior('wp.body',lambda c:() if c.state.players[c.player_id].weapon_id is None else (
        ModifyWeapon(c.state.players[c.player_id].weapon_id,attack=2,source_id=c.source_id),))
    r.register_card(CardDefinition('wp.poison','Diagnostic requirement',CardType.SPELL,cost=1,
        requires_weapon=True,on_play='wp.body'))
    r.register_card(CardDefinition('wp.open','Open face',CardType.SPELL,cost=1))
    def poison(c):return next(e for e in c.state.players[c.player_id].hand if c.state.entities[e].card_id=='wp.poison')
    def fail(c):raise ResolutionError('late failure')
    for name,body in {
        'create':lambda c:(AddToHand(c.player_id,'wp.poison',c.source_id),),
        'upgrade':lambda c:(UpgradeHandCard(CardReference.capture(c.state.entities[poison(c)]),'wp.open',c.source_id),),
        'bypass':lambda c:(PlayFromHand(PlayCard(c.player_id,poison(c))),),
        'cast':lambda c:(CastSpell(c.player_id,'wp.poison',c.source_id),),
        'fail':fail,
        'pay_then_fail':lambda c:(PlayFromHand(PlayCard(c.player_id,poison(c))),InvokeBehavior('wp.fail',c.source_id,c.player_id)),
    }.items():
        r.register_behavior('wp.'+name,body)
        r.register_card(CardDefinition('wp.'+name,name,CardType.SPELL,on_play='wp.'+name))
    if wait:
        def watch(c):
            if c.state.entities[c.event.source_id].card_id!='wp.poison':return ()
            return (RequestChoice(c.player_id,(ChoiceOption('break','Break accepted weapon',(
                Destroy(c.state.players[c.player_id].weapon_id,c.source_id),)),),c.source_id),)
        r.register_behavior('wp.watch',watch)
        r.register_card(CardDefinition('wp.watch','Observer',CardType.MINION,health=4,
            triggers=(TriggerSpec('card_committed','wp.watch'),)))
    return r


class WeaponPlayRequirementTests(unittest.TestCase):
    def game(self,hand=('wp.poison',),weapon=None,enemy_weapon=None,wait=False):
        return Game.from_scenario(Scenario((
            PlayerSetup('wp.hero',hand=hand,mana=10,max_mana=10,weapon_card_id=weapon,
                board=('wp.watch',) if wait else ()),
            PlayerSetup('wp.hero',weapon_card_id=enemy_weapon),)),registry(wait))

    def card(self,g,cid='wp.poison'):
        return next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)

    def play(self,g,cid):g.apply(PlayCard(1,self.card(g,cid)))

    def portable(self,g,wait=False):
        for other in (g.clone(),Game.from_snapshot(g.snapshot(),registry(wait)),replay(build_replay(g),registry(wait))):
            self.assertEqual(other.snapshot(),g.snapshot())

    def test_no_weapon_rejects_before_payment_without_changing_state(self):
        g=self.game();eid=self.card(g);before=g.snapshot()
        self.assertFalse(any(isinstance(a,PlayCard) and a.entity_id==eid for a in g.legal_actions()))
        with self.assertRaisesRegex(IllegalAction,'equipped weapon'):g.apply(PlayCard(1,eid))
        self.assertEqual(before,g.snapshot());self.assertEqual(g.state.players[1].mana,10)

    def test_opponent_weapon_does_not_meet_the_requirement(self):
        g=self.game(enemy_weapon='wp.weapon')
        with self.assertRaises(IllegalAction):self.play(g,'wp.poison')
        self.assertEqual(g.state.players[1].hand,[self.card(g)])

    def test_zero_attack_live_weapon_allows_untargeted_play_once(self):
        g=self.game(weapon='wp.weapon');eid=self.card(g)
        actions=[a for a in g.legal_actions() if isinstance(a,PlayCard) and a.entity_id==eid]
        self.assertEqual(len(actions),1);self.assertIsNone(actions[0].target_id)
        g.apply(actions[0]);self.assertEqual(g.state.players[1].mana,9)
        self.assertEqual(g.state.entities[g.state.players[1].weapon_id].attack,2)
        self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def test_extra_selected_weapon_target_is_rejected_before_payment(self):
        g=self.game(weapon='wp.weapon');before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(PlayCard(1,self.card(g),g.state.players[1].weapon_id))
        self.assertEqual(before,g.snapshot())

    def test_internal_manual_hand_route_has_the_same_gate_and_rolls_back(self):
        g=self.game(hand=('wp.bypass','wp.poison'));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'equipped weapon'):self.play(g,'wp.bypass')
        self.assertEqual(before,g.snapshot())

    def test_storage_and_current_face_upgrade_remain_independent(self):
        g=self.game(hand=('wp.create','wp.upgrade'))
        self.play(g,'wp.create');eid=self.card(g)
        with self.assertRaises(IllegalAction):g.apply(PlayCard(1,eid))
        self.play(g,'wp.upgrade');self.assertEqual(g.state.entities[eid].card_id,'wp.open')
        g.apply(PlayCard(1,eid));self.portable(g)

    def test_automatic_effect_cast_without_weapon_is_not_a_manual_play(self):
        g=self.game(hand=('wp.cast',));self.play(g,'wp.cast')
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(len(g.state.cast_history),2)
        self.assertIsNone(g.state.players[1].weapon_id);self.portable(g)

    def test_requirement_is_checked_at_acceptance_and_not_after_commit_reactions(self):
        g=self.game(weapon='wp.weapon',wait=True);self.play(g,'wp.poison')
        self.assertEqual(g.state.players[1].mana,9);self.assertIsNotNone(g.state.pending_choice)
        self.portable(g,True)
        others=(g.clone(),Game.from_snapshot(g.snapshot(),registry(True)),replay(build_replay(g),registry(True)))
        for current in (g,*others):
            choice=current.state.pending_choice;current.apply(SelectChoice(1,choice.id,('break',)))
            self.assertIsNone(current.state.players[1].weapon_id)
            self.assertEqual(current.state.players[1].mana,9)
        for current in others:self.assertEqual(current.snapshot(),g.snapshot())
        self.portable(g,True)

    def test_late_failure_reverts_nested_payment_and_weapon_growth(self):
        g=self.game(hand=('wp.pay_then_fail','wp.poison'),weapon='wp.weapon');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'late failure'):self.play(g,'wp.pay_then_fail')
        self.assertEqual(before,g.snapshot())

    def test_player_commands_share_gate_and_do_not_reveal_hidden_cards(self):
        g=self.game();port=g.for_player(1);listing=port.legal_actions()
        self.assertFalse(any(a['type']=='play_card' for a in listing['actions']))
        observation=g.for_player(2).observe()
        self.assertNotIn('wp.poison',str(observation))

    def test_typed_declaration_and_fingerprint_default_are_strict(self):
        base=CardDefinition('f.spell','Spell',CardType.SPELL)
        def fingerprint(card):
            r=Registry('fp');r.register_card(card);return r.fingerprint()
        self.assertEqual(fingerprint(base),fingerprint(replace(base,requires_weapon=False)))
        self.assertNotEqual(fingerprint(base),fingerprint(replace(base,requires_weapon=True)))
        for value in (1,0,None,'yes'):
            with self.assertRaises(ValueError):fingerprint(replace(base,requires_weapon=value))
        with self.assertRaises(ValueError):fingerprint(CardDefinition('hero','Hero',CardType.HERO,health=30,requires_weapon=True))

    def test_complete_original_payment_proof_requires_its_original_live_weapon(self):
        g=self.game(weapon='wp.weapon');g._state.action_number=1
        r=Resolution(g);source=r.state.entities[self.card(g)]
        quote=quote_cost(r.state,r.registry,source);prepared=prepare_play(r.state,r.registry,source,None,quote)
        _,proof=capture_hand_cost_proof(r,prepared,quote);validate_hand_cost_proof(proof,r.registry)
        before=deepcopy(proof.payment_state)
        before.entities[before.players[1].weapon_id].zone=Zone.GRAVEYARD
        before.players[1].weapon_id=None
        with self.assertRaisesRegex(ValueError,'original equipped weapon prerequisite'):
            validate_hand_cost_proof(replace(proof,payment_state=before),r.registry)

