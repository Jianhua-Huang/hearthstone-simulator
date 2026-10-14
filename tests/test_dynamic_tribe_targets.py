"""Current tribe candidates, original proofs, magnetic hosts and weapon windows."""
from copy import deepcopy
from dataclasses import replace
import unittest

from hs_sim.engine import (Attack, BodyReference, BodyRootTargetBinding, BodyTargetBinding,
    BodyTargetSelection, CardDefinition, CardType, ChangeMinionTribes, Game, GrantCombo,
    PaidBodyTargetRequest, PlayCard, PlayerSetup, Scenario, SelectChoice, TargetPredicateSpec,
    TribeChangeSpec, TribeState, Zone, paid_body_root_target_plan, play_with_body_targets,
    preflight_paid_body_root_targets, tribe_state)
from hs_sim.engine.effects import ChoiceOption, GainArmor, RequestChoice, Silence
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.targeting import target_choices
from test_target_predicates import registry as base_registry, FRIEND
from test_dynamic_tribes import registry as basic_registry, game as basic_game, change, play_work, rehash
import test_v149_weapon_wear as wear_tests
from test_v149_weapon_wear import WeaponWearPredicate, HealthRule, HealthFlow, HealthOp, HealthLayer, DamageKind


def registry(mode='remove', *, requested=('naga',)):
    r=base_registry()
    r.register_target_predicate(TargetPredicateSpec('current.tribe',current_tribes_any=requested))
    def first(c):
        e=c.state.entities[c.target_id]
        effects=[GainArmor(c.player_id,1)]
        if mode in ('remove','wait'): effects.append(change(e,'set',('dragon',),c.source_id))
        if mode=='wait': return [RequestChoice(c.player_id,(ChoiceOption('ok','Go',tuple(effects)),),c.source_id)]
        return effects
    r.register_behavior('tribe.first',first)
    r.register_card(replace(r.card('unit'),id='tribe.actor',name='Tribe actor',
        battlecry='tribe.first',target_rule='current.tribe'))
    r.register_card(replace(r.card('combo.body'),id='tribe.combo',name='Tribe combo',target_rule='current.tribe'))
    r.register_body_target_binding(BodyTargetBinding('tribe.actor','battlecry','paid',carrier_card_ids=('tribe.actor',)))
    r.register_body_target_binding(BodyTargetBinding('tribe.combo','combo','paid',carrier_card_ids=('tribe.actor',)))
    r.register_body_root_target_binding(BodyRootTargetBinding('tribe.actor','paid','explicit_root',FRIEND,'current.tribe'))
    def setup(c):
        e=c.state.entities[c.state.players[1].board[0]]
        actor=next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id=='tribe.actor')
        return [change(e,'add',('naga',),c.source_id),GrantCombo(BodyReference.capture(actor),'tribe.combo',c.source_id)]
    r.register_behavior('tribe.setup',setup)
    r.register_card(CardDefinition('tribe.setup','Tribe setup',CardType.SPELL,on_play='tribe.setup'))
    return r


def game(mode='remove'):
    g=Game.from_scenario(Scenario((PlayerSetup('hero',hand=('tribe.setup','tribe.actor'),board=('beast','dragon.unit'),mana=6,max_mana=6),
                                   PlayerSetup('hero'))),registry(mode))
    g.apply(PlayCard(1,g.state.players[1].hand[0]))
    return g


def action(g):
    raw=PlayCard(1,g.state.players[1].hand[0],g.state.players[1].board[0])
    plan=paid_body_root_target_plan(g,raw,'paid')
    request=PaidBodyTargetRequest(raw,'paid',tuple(BodyTargetSelection(row.declaration.reference,row.target_choices[0])
        for row in plan.bodies.requirements))
    return play_with_body_targets(preflight_paid_body_root_targets(g,request)),plan


def rehash_origin(snapshot):
    receipt=snapshot['state']['play_history'][-1]['body_targets']
    receipt['origin_hash']=canonical_hash(receipt['origin'])
    return rehash(snapshot)


class DynamicTribeTargetTests(unittest.TestCase):
    def roundtrip(self,g,mode):
        snapshot=g.snapshot()
        for other in (Game.from_snapshot(snapshot,registry(mode)),g.clone(),replay(build_replay(g),registry(mode))):
            self.assertEqual(other.snapshot(),snapshot)
            for viewer in (1,2):self.assertEqual(other.for_player(viewer).observe(),g.for_player(viewer).observe())

    def test_real_independent_root_and_each_body_select_current_tribes_and_pay_once(self):
        g=game('keep'); selected,plan=action(g); target=g.state.players[1].board[0]
        self.assertEqual([row.target_choices for row in plan.bodies.requirements],[(target,),(target,)])
        g.apply(selected); self.assertEqual(g.state.players[1].mana,4)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,4)
        self.assertEqual(g.state.entities[target].damage,2)
        origin=g.state.play_history[-1].body_targets.origin
        fact=next(f for f in origin.entities if f.id==target)
        self.assertEqual(fact.tribe_changes[0].tribe_change,TribeChangeSpec('add',('naga',)))
        self.roundtrip(g,'keep')

    def test_type_changes_after_acceptance_skip_later_body_and_preserve_original_candidates(self):
        g=game(); selected,_=action(g); target=g.state.players[1].board[0]; g.apply(selected)
        self.assertEqual(tribe_state(g.registry,g.state.entities[target]),TribeState(('dragon',)))
        self.assertIsNotNone(g.state.combo_history[-1].failure)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)
        self.assertEqual(g.state.players[1].mana,4)
        self.roundtrip(g,'remove')

    def test_original_changed_type_cannot_be_omitted_or_replaced_after_full_rehash(self):
        g=game(); selected,_=action(g); g.apply(selected)
        for mutation in ('missing','erase','different','future','duplicate'):
            snapshot=g.snapshot(); receipt=snapshot['state']['play_history'][-1]['body_targets']
            fact=next(f for f in receipt['origin']['entities'] if f['id']==selected.target_id)
            if mutation=='missing':fact.pop('tribe_changes')
            elif mutation=='erase':fact['tribe_changes']=[]
            elif mutation=='different':fact['tribe_changes'][0]['tribe_change']['tribes']=['mech']
            elif mutation=='future':fact['tribe_changes'][0]['id']=receipt['origin']['next_attachment_id']
            else:
                other=next(f for f in receipt['origin']['entities'] if f['card_id']=='dragon.unit')
                other['tribe_changes']=deepcopy(fact['tribe_changes'])
            with self.subTest(mutation=mutation),self.assertRaises(SnapshotError):Game.from_snapshot(rehash_origin(snapshot),registry())

    def test_current_and_printed_conditions_can_intersect_without_rewriting_metadata(self):
        g=game('keep'); r=registry('keep')
        r.register_target_predicate(TargetPredicateSpec('both',printed_tribes_any=('beast',),current_tribes_any=('naga',)))
        definition=replace(r.card('tribe.actor'),target_rule='both')
        source=g.state.entities[g.state.players[1].hand[0]]
        self.assertEqual(target_choices(g.state,r,source,definition),(g.state.players[1].board[0],))
        self.assertNotEqual(r.fingerprint,registry('keep',requested=('mech',)).fingerprint)

    def test_real_waiting_current_tribe_target_restores_and_resumes_all_branches(self):
        g=game('wait'); selected,_=action(g); g.apply(selected); snapshot=g.snapshot()
        branches=[g,Game.from_snapshot(snapshot,registry('wait')),g.clone(),replay(build_replay(g),registry('wait'))]
        for branch in branches:
            pending=branch.state.pending_choice;branch.apply(SelectChoice(1,pending.id,('ok',)))
            self.assertEqual(branch.state.players[1].mana,4)
            self.assertIsNotNone(branch.state.combo_history[-1].failure)
        for branch in branches:self.assertEqual(branch.snapshot(),g.snapshot())

    def test_player_json_uses_current_type_candidates_without_exporting_original_changes(self):
        g=game('keep');port=g.for_player(1)
        own=next(p for p in port.observe()['observation']['players'] if p['id']==1)
        card=next(c['ref'] for c in own['hand'] if c['card_id']=='tribe.actor')
        self.assertEqual(own['board'][0]['tribes'],['beast','naga'])
        options=port.independent_targets(card); row=options['choices'][0]
        command={'revision':options['revision'],'action':{'type':'play_card','card':card,'target':row['root_targets'][0],
            'body_targets':[{'body':b['body'],'target':b['targets'][0]} for b in row['bodies']]}}
        self.assertTrue(port.submit(command)['accepted']);self.assertEqual(g.state.players[1].mana,4)
        import json
        text=json.dumps([port.observe(),options])
        self.assertNotIn('tribe_changes',text);self.assertNotIn('tribe_change',text)


class DynamicTribeMagneticTests(unittest.TestCase):
    def check(self,g,work):
        snapshot=g.snapshot()
        for other in (Game.from_snapshot(snapshot,basic_registry(work)),g.clone(),replay(build_replay(g),basic_registry(work))):
            self.assertEqual(other.snapshot(),snapshot)

    def test_current_mech_grant_enables_magnetic_and_history_survives_host_silence(self):
        def work(c):
            e=c.state.entities[c.state.players[1].board[0]]
            return [change(e,'add',('mech',),c.source_id)] if not c.state.magnetic_history else [Silence(e.id)]
        g=basic_game(work,hand=('work','magnet','work'));target=g.state.players[1].board[0];play_work(g)
        magnet=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id=='magnet')
        g.apply(PlayCard(1,magnet,position=0));self.assertEqual(len(g.state.magnetic_history),1)
        self.assertEqual(g.state.magnetic_history[0].host_tribe_changes[0].tribe_change,TribeChangeSpec('add',('mech',)))
        play_work(g);self.assertEqual(tribe_state(g.registry,g.state.entities[target]),TribeState(('beast',)))
        self.check(g,work)

    def test_known_set_can_enable_an_unknown_printed_host_without_guessing_static_metadata(self):
        def work(c):return [change(c.state.entities[c.state.players[1].board[0]],'set',('mech',),c.source_id)]
        g=basic_game(work,board=('unknown',),hand=('work','magnet'));play_work(g)
        g.apply(PlayCard(1,g.state.players[1].hand[0],position=0));self.assertEqual(len(g.state.magnetic_history),1);self.check(g,work)

    def test_excluded_mech_in_all_tribes_uses_the_normal_entry_path(self):
        def work(c):return [change(c.state.entities[c.state.players[1].board[0]],'remove',('mech',),c.source_id)]
        g=basic_game(work,board=('all',),hand=('work','magnet'));play_work(g)
        g.apply(PlayCard(1,g.state.players[1].hand[0],position=0));self.assertFalse(g.state.magnetic_history)
        self.assertEqual(len(g.state.players[1].board),2);self.check(g,work)

    def test_cropped_or_future_original_magnetic_host_changes_reject_after_rehash(self):
        def work(c):return [change(c.state.entities[c.state.players[1].board[0]],'add',('mech',),c.source_id)]
        g=basic_game(work,hand=('work','magnet'));play_work(g);g.apply(PlayCard(1,g.state.players[1].hand[0],position=0))
        for mutation in ('missing','erase','future'):
            snapshot=g.snapshot();row=snapshot['state']['magnetic_history'][0]
            if mutation=='missing':row.pop('host_tribe_changes')
            elif mutation=='erase':row['host_tribe_changes']=[]
            else:row['host_tribe_changes'][0]['id']=row['enchantment_id']
            with self.subTest(mutation=mutation),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(snapshot),basic_registry(work))


class DynamicTribeWearTests(unittest.TestCase):
    def fixture(self):
        f=wear_tests.WeaponWearTests('test_current_dragon_metadata_sleep_and_opponent_scope');f.setUp();return f

    def test_weapon_current_condition_uses_granted_type_and_keeps_original_after_later_silence(self):
        f=self.fixture()
        def work(c):return [change(c.state.entities[c.state.players[1].board[0]],'add',('dragon',),c.source_id)]
        f.spell('change',work);f.spell('silence',lambda c:[Silence(c.state.players[1].board[0])])
        g=f.game(weapon='storm',board=('plain',),hand=('change','silence'));f.cast(g,'change');f.attack(g)
        self.assertEqual(f.row(g).wear_receipt.plan.amount,0)
        original=f.row(g).wear_acceptance.board[0]
        self.assertEqual(original.tribes,('dragon',));self.assertEqual(len(original.tribe_changes),1)
        f.cast(g,'silence');self.assertEqual(tribe_state(g.registry,g.state.entities[g.state.players[1].board[0]]),TribeState(()));f.check(g)

    def test_dynamic_type_at_accepted_window_survives_same_batch_death_only_in_original_profile(self):
        rule=HealthRule(HealthFlow.DAMAGE,HealthOp.REDIRECT,layer=HealthLayer.TARGET,target_relation='friendly',
            target_kinds=(CardType.HERO,),damage_kinds=(DamageKind.COMBAT,),redirect_to='self')
        for window,amount in (('pre_wear_current',1),('combat_accept_original',0)):
            f=self.fixture();f.card('lost',CardType.MINION,health=1,health_rules=(rule,))
            spec=f.spec('prevent_durability',window=window,preds=(WeaponWearPredicate('friendly_tribe_present','dragon'),))
            f.card('conditional',CardType.WEAPON,attack=2,durability=3,weapon_wear_policies=(spec,))
            def work(c):return [change(c.state.entities[c.state.players[1].board[0]],'add',('dragon',),c.source_id)]
            f.spell('change',work);g=f.game(weapon='conditional',board=('lost',),hand=('change',));f.cast(g,'change');f.attack(g)
            self.assertEqual(f.row(g).wear_receipt.plan.amount,amount)
            self.assertEqual(tribe_state(g.registry,g.state.death_history[0]),TribeState(('dragon',)));f.check(g)

    def test_all_tribe_exclusion_does_not_satisfy_weapon_dragon_condition(self):
        f=self.fixture();f.card('all',CardType.MINION,health=30,tribes=('all',))
        def work(c):return [change(c.state.entities[c.state.players[1].board[0]],'remove',('dragon',),c.source_id)]
        f.spell('change',work);g=f.game(weapon='storm',board=('all',),hand=('change',));f.cast(g,'change');f.attack(g)
        self.assertEqual(f.row(g).wear_receipt.plan.amount,1)
        self.assertEqual(f.row(g).wear_acceptance.board[0].tribe_exclusions,('dragon',));f.check(g)

    def test_weapon_saved_current_types_must_recompute_from_original_modifiers(self):
        f=self.fixture()
        def work(c):return [change(c.state.entities[c.state.players[1].board[0]],'add',('dragon',),c.source_id)]
        f.spell('change',work);g=f.game(weapon='storm',board=('plain',),hand=('change',));f.cast(g,'change');f.attack(g)
        for mutation in ('erase','different','future'):
            snapshot=g.snapshot();row=snapshot['state']['hero_attack_history'][0]['wear_acceptance']['board'][0]
            if mutation=='erase':row['tribe_changes']=[]
            elif mutation=='different':row['tribe_changes'][0]['tribe_change']['tribes']=['mech']
            else:row['tribe_changes'][0]['id']=snapshot['state']['next_attachment_id']
            with self.subTest(mutation=mutation),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(snapshot),f.fresh())


if __name__=='__main__':unittest.main()
