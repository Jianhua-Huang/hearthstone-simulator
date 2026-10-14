"""Original character attack phases share native windows and combat execution."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Keyword,
    ResolutionError, SelectChoice, SnapshotError, character_attacks, character_attack_count)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, Damage, Destroy,
    ForceAttack, Freeze, InvokeBehavior, RequestChoice, ReturnToHand, Transform)
from hs_sim.engine.interrupts import RedirectAttack
from hs_sim.engine.resolver import CombatDamage
from hs_sim.targets import canonical_digest
import test_v134_hero_attack_history as old

SUPPORT=Path(__file__).resolve().parents[1]/'data/support/character-attack-history-basics.json'
PIN='458d0f104d1382964820d30849d89e133e6986fb870f2ce501c12c51a4e2c93e'


class CharacterAttackHistoryTests(unittest.TestCase):
    game=old.HeroAttackHistoryTests.game
    spell=old.HeroAttackHistoryTests.spell
    watcher=old.HeroAttackHistoryTests.watcher
    hero=old.HeroAttackHistoryTests.hero
    cast=old.HeroAttackHistoryTests.cast
    check=old.HeroAttackHistoryTests.check
    choose=old.HeroAttackHistoryTests.choose
    rehash=old.HeroAttackHistoryTests.rehash

    def setUp(self):
        old.HeroAttackHistoryTests.setUp(self)
        self.r.register_card(CardDefinition('charge','Charge fixture',CardType.MINION,attack=1,health=30,
            keywords=(Keyword.CHARGE,)))
        self.r.register_card(CardDefinition('wind','Windfury fixture',CardType.MINION,attack=1,health=30,
            keywords=(Keyword.CHARGE,Keyword.WINDFURY)))

    def count(self,g,p=1,**scope):return character_attack_count(g.state,p,**scope)

    def hit(self,g,*,p=1,index=0,target=None):
        return g.apply(Attack(p,g.state.players[p].board[index],target or self.hero(g,3-p)))

    def test_real_requirement_is_pinned_without_a_white_price_adapter(self):
        value=json.loads(SUPPORT.read_bytes());self.assertEqual(canonical_digest(value),PIN)
        row=value['records'][0];source=next(r for r in json.loads((SUPPORT.parents[1]/'extracted/cards.json').read_bytes()) if r['id']==row['id'])
        self.assertEqual(row['data'],source);self.assertEqual(canonical_digest(row['data']),row['data_sha256'])
        self.assertEqual(value['new_real_card_adapters'],[])

    def test_voluntary_minion_and_hero_share_original_windows_without_new_allocator(self):
        g=self.game(board=('charge',));self.hit(g);g.apply(Attack(1,self.hero(g),self.hero(g,2)))
        rows=character_attacks(g.state,1)
        self.assertEqual([r.source_kind for r in rows],[CardType.MINION,CardType.HERO])
        self.assertEqual(self.count(g),2);self.assertEqual(len(g.state.hero_attack_history),1)
        self.assertEqual([r.declaration.id for r in rows],[1,2]);self.check(g)

    def test_windfury_two_physical_attacks_are_two_completed_roots(self):
        g=self.game(board=('wind',));self.hit(g);self.hit(g)
        self.assertEqual((self.count(g),self.count(g,phase='combat_accepted'),self.count(g,phase='declared')),(2,2,2))
        self.assertEqual(len({r.declaration.id for r in character_attacks(g.state,1)}),2);self.check(g)

    def test_whole_game_original_payer_and_turn_filters_survive_natural_turns(self):
        g=self.game(board=('charge',),enemy=('charge',));self.hit(g);g.apply(EndTurn(1));self.hit(g,p=2)
        g.apply(EndTurn(2));self.hit(g)
        self.assertEqual((self.count(g),self.count(g,2),self.count(g,turn=1),self.count(g,turn=3)),(2,1,1,1))
        self.check(g)

    def test_existing_forced_attack_has_original_origin_without_opportunity_charge(self):
        self.spell('force',lambda c:(ForceAttack(c.state.players[1].board[0],c.state.players[2].hero_id),))
        g=self.game(board=('plain',),hand=('force',));self.cast(g,'force')
        self.assertEqual((self.count(g,forced=True),self.count(g,forced=False),g.state.entities[g.state.players[1].board[0]].attacks_this_turn),(1,0,0))
        self.check(g)

    def test_invalid_forced_pair_does_not_fabricate_a_declaration(self):
        self.spell('force',lambda c:(ForceAttack(c.state.players[1].board[0],c.state.players[1].board[0]),))
        g=self.game(board=('plain',),hand=('force',));self.cast(g,'force')
        self.assertEqual((self.count(g,phase='declared'),g.state.character_attack_history),(0,[]));self.check(g)

    def test_friendly_forced_combat_is_one_original_attack_not_two_damage_packets(self):
        self.spell('force',lambda c:(ForceAttack(c.state.players[1].board[0],c.state.players[1].board[1],combat_relation='friendly_minions'),))
        g=self.game(board=('plain','plain'),hand=('force',));self.cast(g,'force')
        row=character_attacks(g.state,1)[0]
        self.assertEqual((row.declaration.combat_relation,row.combat.target_player_id,self.count(g)),('friendly_minions',1,1))
        self.check(g)

    def test_shield_prevention_still_completes_the_original_attack(self):
        g=self.game(board=('charge',),enemy=('shield',));target=g.state.players[2].board[0];self.hit(g,target=target)
        self.assertEqual((self.count(g),g.state.entities[target].damage),(1,0));self.check(g)

    def test_source_death_during_exchange_preserves_completed_original_root(self):
        g=self.game(board=('fragile',),enemy=('plain',));g.apply(EndTurn(1));g.apply(EndTurn(2))
        source=g.state.players[1].board[0];target=g.state.players[2].board[0];self.hit(g,target=target)
        self.assertNotIn(source,g.state.players[1].board);self.assertEqual(self.count(g),1)
        self.assertEqual(character_attacks(g.state,1)[0].declaration.source_id,source);self.check(g)

    def test_freeze_after_declaration_cancels_without_completed_credit(self):
        self.watcher('freeze',('attack_declared',),lambda c:(Freeze(c.event.source_id),))
        g=self.game(board=('charge','freeze'));self.hit(g)
        self.assertEqual((self.count(g,phase='declared'),self.count(g,phase='combat_accepted'),self.count(g,phase='cancelled'),self.count(g)),(1,0,1,0))
        self.check(g)

    def test_source_return_cancels_original_presence_without_guessing_new_hand_source(self):
        self.watcher('return',('attack_declared',),lambda c:(ReturnToHand(c.event.source_id),))
        g=self.game(board=('charge','return'));source=g.state.players[1].board[0];self.hit(g)
        self.assertIn(source,g.state.players[1].hand);self.assertEqual((self.count(g),self.count(g,phase='cancelled')),(0,1));self.check(g)

    def test_retarget_keeps_declaration_and_actual_delivered_target_separate(self):
        def redirect(c):return (RedirectAttack(dict(c.event.data)['window_id'],c.state.players[2].board[0]),)
        self.watcher('redirect',('attack_declared',),redirect)
        g=self.game(board=('charge','redirect'),enemy=('plain',));self.hit(g);row=character_attacks(g.state,1)[0]
        self.assertEqual(row.declaration.target_id,self.hero(g,2));self.assertEqual(row.delivery.target_id,g.state.players[2].board[0]);self.check(g)

    def test_later_source_control_and_transform_do_not_rewrite_original_player_or_face(self):
        self.spell('control',lambda c:(ChangeControl(c.state.players[1].board[0],2),))
        g=self.game(board=('charge',),hand=('control',));self.hit(g);original=character_attacks(g.state,1)[0]
        self.cast(g,'control');self.assertEqual((self.count(g),self.count(g,2)),(1,0));self.assertEqual(character_attacks(g.state,1)[0],original);self.check(g)
        self.setUp();self.spell('change',lambda c:(Transform(c.state.players[1].board[0],'plain'),))
        g=self.game(board=('charge',),hand=('change',));self.hit(g);self.cast(g,'change')
        self.assertEqual(character_attacks(g.state,1)[0].source_card_id,'charge');self.check(g)

    def test_declaration_waiting_restore_clone_replay_resumes_exactly_once(self):
        self.watcher('wait',('attack_declared',),lambda c:(RequestChoice(1,(ChoiceOption('ok','Continue'),),c.source_id),))
        g=self.game(board=('charge','wait'));self.hit(g)
        self.assertEqual((self.count(g,phase='declared'),self.count(g)),(1,0));self.check(g)
        for branch in (g.clone(),old.Game.from_snapshot(g.snapshot(),self.r),old.replay(old.build_replay(g),self.r)):
            self.choose(branch);self.assertEqual((self.count(branch),len(branch.state.character_attack_history)),(1,1));self.check(branch)

    def test_completion_wait_retains_original_history_before_later_choice(self):
        self.watcher('wait',('attack_finished',),lambda c:(RequestChoice(1,(ChoiceOption('ok','Continue'),),c.source_id),))
        g=self.game(board=('charge','wait'));self.hit(g);self.assertEqual(self.count(g),1);self.check(g)
        self.choose(g);self.assertEqual(self.count(g),1);self.check(g)

    def test_delivered_minion_wait_keeps_the_original_combat_reference(self):
        from hs_sim.engine.interrupts import ResolveAttack, resolve_attack
        from hs_sim.engine.resolver import default_mechanics
        def paused(r,effect):
            tail=resolve_attack(r,effect)
            return (RequestChoice(1,(ChoiceOption('ok','Continue original delivery'),),r.state.players[1].hero_id),*tail)
        mechanics=default_mechanics('character-delivery-test').replace(ResolveAttack,paused)
        g=self.game(board=('charge',),mechanics=mechanics);self.hit(g)
        row=character_attacks(g.state,1,phase='declared')[0]
        self.assertIsNotNone(row.delivery);self.assertIsNone(row.combat);self.check(g,mechanics)
        for branch in (g.clone(),old.Game.from_snapshot(g.snapshot(),self.r,mechanics),old.replay(old.build_replay(g),self.r,mechanics)):
            self.choose(branch);self.assertEqual(self.count(branch),1);self.check(branch,mechanics)

    def test_delivered_reference_cannot_borrow_or_drop_its_window_identity(self):
        from hs_sim.engine.interrupts import ResolveAttack, resolve_attack
        from hs_sim.engine.resolver import default_mechanics
        def paused(r,effect):
            return (RequestChoice(1,(ChoiceOption('ok','Continue original delivery'),),r.state.players[1].hero_id),*resolve_attack(r,effect))
        mechanics=default_mechanics('character-delivery-rejection-test').replace(ResolveAttack,paused)
        g=self.game(board=('charge',),mechanics=mechanics);self.hit(g);saved=g.snapshot()
        for value in (None,True,g.state.next_window_id):
            bad=deepcopy(saved);work=bad['resolution_frame']['fields']['continuation']['tuple']
            tail=next(item for item in work if item.get('type','').endswith('.CombatDamage'))
            tail['fields']['attack_window_id']=value
            with self.subTest(value=value),self.assertRaises(SnapshotError):old.Game.from_snapshot(self.rehash(bad),self.r,mechanics)

    def test_game_terminal_after_declaration_has_an_interruption_not_completion(self):
        self.watcher('kill',('attack_declared',),lambda c:(Damage(c.state.players[2].hero_id,200,c.source_id),))
        g=self.game(board=('charge','kill'));self.hit(g)
        self.assertEqual((self.count(g,phase='declared'),self.count(g,phase='interrupted'),self.count(g)),(1,1,0));self.check(g)

    def test_failure_rolls_back_window_history_damage_and_opportunity(self):
        self.watcher('fail',('attack_declared',),lambda c:(AddToHand(1,'missing.character.attack'),))
        g=self.game(board=('charge','fail'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.hit(g)
        self.assertEqual(g.snapshot(),before)

    def test_legacy_bare_minion_combat_remains_damage_without_window_credit(self):
        self.spell('bare',lambda c:(CombatDamage(c.state.players[1].board[0],c.state.players[2].board[0]),))
        g=self.game(board=('plain',),enemy=('plain',),hand=('bare',));self.cast(g,'bare')
        self.assertEqual((self.count(g,phase='declared'),g.state.entities[g.state.players[1].board[0]].damage),(0,1));self.check(g)

    def test_original_physical_record_strict_roundtrip_and_query_purity(self):
        g=self.game(board=('charge',));self.hit(g);before=g.snapshot();row=character_attacks(g.state,1)[0]
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state);self.assertEqual(codec.decode(codec.encode(row)),row)
        self.assertEqual(self.count(g,before_window_id=row.declaration.id),0)
        for _ in range(3):self.assertEqual(self.count(g),1)
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_query_rejects_boolean_invalid_phase_player_and_bounds(self):
        g=self.game()
        for p in (True,0,3,'1'):
            with self.assertRaises(ValueError):self.count(g,p)
        for key,values in (('phase',(True,'attempt','all')),('forced',(1,'forced')),
                           ('turn',(True,0,'1')),('before_window_id',(True,0,-1))):
            for value in values:
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):self.count(g,**{key:value})

    def test_rehashed_history_rejects_duplicates_future_window_and_original_player(self):
        g=self.game(board=('charge',));self.hit(g);saved=g.snapshot()
        for mode in ('duplicate','future','player','source','missing','lost_record','clock'):
            bad=deepcopy(saved);row=bad['state']['character_attack_history'][0]
            if mode=='duplicate':bad['state']['character_attack_history'].append(deepcopy(row))
            elif mode=='future':row['declaration']['id']=bad['state']['next_window_id']
            elif mode=='player':row['declaration']['player_id']=2
            elif mode=='source':row['source_card_id']='plain'
            elif mode=='lost_record':bad['state']['character_attack_history'].clear()
            elif mode=='clock':row['declaration_action']=0;row['root_action_number']=0
            else:del row['source_kind']
            with self.subTest(mode=mode),self.assertRaises(SnapshotError):old.Game.from_snapshot(self.rehash(bad),self.r)

    def test_waiting_control_tail_cannot_be_removed_or_duplicated(self):
        self.watcher('wait',('attack_declared',),lambda c:(RequestChoice(1,(ChoiceOption('ok','Continue'),),c.source_id),))
        g=self.game(board=('charge','wait'));self.hit(g);saved=g.snapshot()
        for mode in ('remove','duplicate'):
            bad=deepcopy(saved);work=bad['resolution_frame']['fields']['continuation']['tuple']
            if mode=='remove':work.clear()
            else:work.extend(deepcopy(work))
            with self.subTest(mode=mode),self.assertRaises(SnapshotError):old.Game.from_snapshot(self.rehash(bad),self.r)

    def test_player_observation_and_commands_do_not_expose_host_history(self):
        g=self.game(board=('charge',));self.hit(g)
        for p in (1,2):
            data=json.dumps(g.observe(p))+json.dumps(g.for_player(p).legal_actions())
            for key in ('character_attack_history','source_zone_epoch','declaration_event_cursor','delivery_event_cursor'):
                self.assertNotIn(key,data)
        self.check(g)
