"""Ordinary root selection cannot become a body-storage side effect."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from hs_sim.engine import (BodyReference, BodyRootTargetBinding, BodyTargetBinding,
    BodyTargetProfile, CardDefinition, CardType, Game, GrantBattlecry, PlayCard,
    PlayerSetup, Registry, Scenario, TargetMode, TargetSpec, Zone)
from hs_sim.engine.body_grant_authority import authorize_grant
from hs_sim.engine.body_target_authority import body_target_authorities
from hs_sim.engine.effects import GainArmor
from hs_sim.engine.model import AbilityInstance
from hs_sim.engine.paid_body_targets import _selection
from hs_sim.engine.replay import build_replay, replay


def fixture(visibility='player'):
    calls=[]
    r=Registry('root-predicate-storage-'+visibility)
    r.register_body_target_profile(BodyTargetProfile('paid','paid_hand','manual','pre_payment'))
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=30))
    domain=TargetSpec(TargetMode.REQUIRED,(Zone.BOARD,),(CardType.MINION,),'friendly')
    r.register_behavior('body',lambda c:[GainArmor(c.player_id,1)])
    r.register_card(CardDefinition('target','Target',CardType.MINION,health=10))
    r.register_card(CardDefinition('unit','Unit',CardType.MINION,cost=2,health=10,
        on_play='body',battlecry='body',targeting=domain))
    r.register_card(CardDefinition('donor','Donor',CardType.MINION,health=10,
        battlecry='body',targeting=replace(domain,relation='enemy')))
    def predicate(context):
        calls.append(context)
        raise AssertionError('Ordinary predicate invoked during storage or unsupported execution')
    r.register_target_rule('ordinary.custom',predicate,visibility=visibility)
    for name in ('unit','donor'):
        r.register_body_target_binding(BodyTargetBinding(name,'battlecry','paid',carrier_card_ids=('unit',)))
    r.register_body_root_target_binding(BodyRootTargetBinding('unit','paid','explicit_root',
        replace(domain,relation='enemy'),'ordinary.custom'))
    def setup(c):
        source=next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id=='unit')
        return [GrantBattlecry(BodyReference.capture(source),'donor',c.source_id)]
    r.register_behavior('setup',setup)
    r.register_card(CardDefinition('setup','Setup',CardType.SPELL,on_play='setup'))
    return r,calls


def game(visibility='player'):
    r,calls=fixture(visibility)
    g=Game.from_scenario(Scenario((PlayerSetup('hero',hand=('setup','unit'),board=('target',),mana=6,max_mana=6),
        PlayerSetup('hero',board=('target',),mana=6,max_mana=6))),r)
    return g,calls


class RootPredicateGrantStorageTests(unittest.TestCase):
    def setup(self,g):g.apply(PlayCard(1,g.state.players[1].hand[0]))

    def test_player_and_omniscient_root_storage_restore_clone_and_real_setup_replay(self):
        for visibility in ('player','omniscient'):
            with self.subTest(visibility=visibility):
                g,calls=game(visibility); self.setup(g)
                source=g.state.entities[g.state.players[1].hand[0]]
                self.assertEqual(len([a for a in source.abilities if a.kind=='battlecry']),2)
                self.assertEqual(calls,[]); snapshot=g.snapshot()
                for other in (Game.from_snapshot(snapshot,fixture(visibility)[0]),g.clone(),replay(build_replay(g),fixture(visibility)[0])):
                    self.assertEqual(other.snapshot(),snapshot)
                    for viewer in (1,2):self.assertEqual(other.for_player(viewer).observe(),g.for_player(viewer).observe())
                self.assertEqual(calls,[])

    def test_prospective_storage_authority_has_no_quote_target_query_allocation_or_rng(self):
        g,calls=game(); source=g._state.entities[g.state.players[1].hand[1]]
        ability=AbilityInstance(g.state.next_attachment_id,'battlecry',behavior_id='body',
            source_id=source.id,battlecry_card_id='donor')
        snapshot=g.snapshot(); rng=g._rng.getstate()
        with (patch('hs_sim.engine.costs.quote_cost',side_effect=AssertionError('quote')),
            patch('hs_sim.engine.targeting.target_choices',side_effect=AssertionError('target query'))):
            self.assertEqual(authorize_grant(g._state,g.registry,source,ability),'paid')
        self.assertEqual(g.snapshot(),snapshot); self.assertEqual(g._rng.getstate(),rng); self.assertEqual(calls,[])

    def test_actual_paid_and_player_consumers_reject_custom_root_before_callback_or_payment(self):
        for visibility in ('player','omniscient'):
            with self.subTest(visibility=visibility):
                g,calls=game(visibility); self.setup(g)
                source=g._state.entities[g.state.players[1].hand[0]]
                authorities=body_target_authorities(g._state,g.registry,BodyReference.capture(source),'paid')
                action=PlayCard(1,source.id,g.state.players[2].board[0],body_target_profile_id='paid',
                    body_targets=tuple(_selection(a.declaration.reference,g.state.players[i].board[0]) for i,a in enumerate(authorities,1)))
                snapshot=g.snapshot(); rng=g._rng.getstate(); history=g.history
                with self.assertRaisesRegex(ValueError,'audited built-in'):g.apply(action)
                own=g.for_player(1).observe()['observation']['players'][0]['hand'][0]['ref']
                self.assertEqual(g.for_player(1).independent_targets(own)['error'],'unsupported_rule')
                self.assertEqual(g.snapshot(),snapshot); self.assertEqual(g._rng.getstate(),rng)
                self.assertEqual(g.history,history); self.assertEqual(calls,[])


if __name__=='__main__':unittest.main()
