"""Native four-button policy; diagnostic bodies isolate the real keyword rules."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest
from hs_sim.engine import (ActivatedAbilitySpec,Attack,CardClass,CardDefinition,CardType,EndTurn,
    Game,IllegalAction,Keyword,MakeDormant,PlayCard,PlayerSetup,Registry,ResolutionError,Scenario,
    SelectChoice,SnapshotError,UseMinionAbility,Zone)
from hs_sim.engine.construction import DeckPolicy,DeckSpec,validate_deck
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,CopyMinion,Freeze,GainArmor,
    GrantKeyword,InvokeBehavior,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.pools import (GenerationContext,GenerationPolicy,PoolCard,PoolDefinition,
    PoolMember,PoolQuery,resolve_candidates)
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

ROOT=Path(__file__).resolve().parents[1]

def registry(wind=None,waiting=False,fault=False,attack=3):
    r=Registry('old-god-independent-diagnostics-v1')
    r.register_behavior('noop',lambda c:())
    r.register_card(CardDefinition('hero','Diagnostic hero',CardType.HERO,health=60,initial_hero_power='power',metadata=metadata(CardClass.MAGE,collectible=False)))
    r.register_card(CardDefinition('power','Diagnostic power',CardType.HERO_POWER,on_use='noop',metadata=metadata(CardClass.MAGE,collectible=False)))
    r.register_card(CardDefinition('plain','Diagnostic ordinary minion',CardType.MINION,attack=1,health=3,metadata=metadata()))
    for n in range(1,5):r.register_behavior('a'+str(n),lambda c,n=n:(GainArmor(c.player_id,n),))
    def fail(c):raise ResolutionError('Diagnostic ability failure')
    r.register_behavior('fail',fail)
    r.register_behavior('wait',lambda c:(RequestChoice(c.player_id,(
        ChoiceOption('finish','Finish',(GainArmor(c.player_id,4),)),
        ChoiceOption('fail','Fail',(InvokeBehavior('fail',c.source_id,c.player_id),))),c.source_id),))
    specs=tuple(ActivatedAbilitySpec('a'+str(n),'fail' if fault and n==1 else 'wait' if waiting and n==4 else 'a'+str(n)) for n in range(1,5))
    keywords=(Keyword.OLD_GOD,) if wind is None else (Keyword.OLD_GOD,wind)
    for name in ('god','god2'):
        r.register_card(CardDefinition(name,'Diagnostic four-button Old God',CardType.MINION,attack=attack,health=9,
            keywords=keywords,activated_abilities=specs,metadata=metadata()))
    bodies={'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'basecopy':lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),),
        'freeze':lambda c:(Freeze(c.target_id),),'silence':lambda c:(Silence(c.target_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),'control':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        'sleep':lambda c:(MakeDormant(c.target_id,1),),
        'grant':lambda c:(GrantKeyword(c.target_id,Keyword.OLD_GOD),)}
    for name,fn in bodies.items():
        r.register_behavior(name,fn);r.register_card(CardDefinition(name,'Diagnostic '+name,CardType.SPELL,on_play=name,requires_target=True,metadata=metadata()))
    for name in ('god','plain'):
        if name not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(name)))
    r.register_pool(PoolDefinition('pool','v1','diagnostic-old-god','experimental',(PoolMember('god'),PoolMember('plain'))))
    return r

class OldGodBasicsTests(unittest.TestCase):
    def game(self,board=('god',),hand=(),wind=None,waiting=False,fault=False,attack=3):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',board=board,hand=hand,deck=('plain',)*12,hero_power_card_id='power',max_mana=10,mana=10),
            PlayerSetup('hero',deck=('plain',)*12,hero_power_card_id='power',max_mana=10,mana=10)),seed=163),registry(wind,waiting,fault,attack))
    def unit(self,g,pos=0,player=1):return g.state.entities[g.state.players[player].board[pos]]
    def use(self,g,n,pos=0):return g.apply(UseMinionAbility(g.state.active_player,self.unit(g,pos,g.state.active_player).id,'a'+str(n)))
    def play(self,g,name,target=None):
        p=g.state.active_player;eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==name)
        return g.apply(PlayCard(p,eid,target))
    def next_turn(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def portable(self,g):
        d=g.registry.card('god');wind=next((k for k in d.keywords if k in (Keyword.WINDFURY,Keyword.MEGA_WINDFURY)),None)
        waiting=d.activated_abilities[3].behavior_id=='wait';fault=d.activated_abilities[0].behavior_id=='fail'
        s=g.snapshot();self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),registry(wind,waiting,fault,d.attack)).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(wind,waiting,fault,d.attack)).snapshot(),s);return s
    def attack(self,g,pos=0):return g.apply(Attack(1,self.unit(g,pos).id,g.state.players[2].hero_id))

    def test_four_distinct_abilities_and_independent_keyword_are_required(self):
        d=registry().card('god')
        for kw in ({'activated_abilities':d.activated_abilities[:3]},
                {'activated_abilities':(d.activated_abilities[0],)*4},
                {'keywords':()},{'keywords':(Keyword.TITAN,Keyword.OLD_GOD)}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):Registry('invalid').register_card(replace(d,**kw))

    def test_first_use_is_free_second_spends_attack_and_third_is_rejected(self):
        g=self.game();self.use(g,1);self.assertTrue(self.unit(g).old_god_free_used);self.assertEqual(self.unit(g).attacks_this_turn,0)
        self.use(g,2);self.assertEqual(self.unit(g).attacks_this_turn,1);s=g.snapshot()
        with self.assertRaises(IllegalAction):self.use(g,3)
        self.assertEqual(g.snapshot(),s);self.portable(g)

    def test_remaining_abilities_block_voluntary_attack(self):
        g=self.game();s=g.snapshot()
        with self.assertRaisesRegex(IllegalAction,'Old God'):self.attack(g)
        self.assertEqual(g.snapshot(),s)

    def test_normal_two_turn_exhaustion_leaves_attack_for_third_turn(self):
        g=self.game();self.use(g,1);self.use(g,2);self.next_turn(g);self.use(g,3);self.use(g,4)
        with self.assertRaises(IllegalAction):self.attack(g)
        self.next_turn(g);self.attack(g)
        with self.assertRaises(IllegalAction):self.attack(g)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,57);self.portable(g)

    def test_only_final_ability_first_then_one_attack(self):
        g=self.game();self.use(g,1);self.use(g,2);self.next_turn(g);self.use(g,3);self.next_turn(g);self.use(g,4)
        self.assertEqual(self.unit(g).attacks_this_turn,0);self.attack(g);self.portable(g)

    def test_native_windfury_budget_is_three_abilities_without_implicit_keyword(self):
        g=self.game(wind=Keyword.WINDFURY)
        for n in (1,2,3):self.use(g,n)
        with self.assertRaises(IllegalAction):self.use(g,4)
        self.assertEqual(self.unit(g).attacks_this_turn,2);self.portable(g)

    def test_native_mega_budget_allows_four_abilities_then_one_attack(self):
        g=self.game(wind=Keyword.MEGA_WINDFURY)
        for n in (1,2,3,4):self.use(g,n)
        self.assertEqual(self.unit(g).attacks_this_turn,3);self.attack(g)
        with self.assertRaises(IllegalAction):self.attack(g)
        self.portable(g)

    def test_last_free_skill_preserves_two_native_windfury_attacks(self):
        g=self.game(wind=Keyword.WINDFURY)
        for n in (1,2,3):self.use(g,n)
        self.next_turn(g);self.use(g,4);self.attack(g);self.attack(g);self.portable(g)

    def test_newly_played_minion_can_use_abilities(self):
        g=self.game(board=(),hand=('god',));self.play(g,'god');self.use(g,1);self.use(g,2);self.portable(g)

    def test_physical_carriers_have_separate_free_opportunities(self):
        g=self.game(board=('god','god2'));self.use(g,1,0);self.use(g,1,1)
        self.assertEqual([self.unit(g,p).attacks_this_turn for p in (0,1)],[0,0]);self.portable(g)

    def test_zero_attack_still_has_two_skill_opportunities(self):
        g=self.game(attack=0);self.use(g,1);self.use(g,2);self.assertEqual(self.unit(g).attacks_this_turn,1);self.portable(g)

    def test_primary_rule_evidence_is_pinned_but_full_native_card_is_not_claimed(self):
        p=json.loads((ROOT/'data/support/old-god-foundation-audit.json').read_bytes())
        self.assertEqual(canonical_digest(p),'ef63533342f3009ecb34fd82f663920a7bf45356ca9483032ac1c6ce7ae5aac2')
        self.assertEqual(len(p['records']),6);self.assertFalse(p['full_native_cthun_adapter'])
        self.assertFalse(p['CN_runtime_calibrated']);self.assertNotIn('BE_013',registry().cards)

    def test_current_copy_keeps_consumed_material_and_fresh_budget(self):
        g=self.game(hand=('copy',));self.use(g,1);self.use(g,2);self.play(g,'copy',self.unit(g).id)
        copied=self.unit(g,1);self.assertFalse(copied.old_god_free_used);self.assertEqual(copied.attacks_this_turn,0)
        self.assertEqual([a.consumed for a in copied.abilities if a.kind=='activated'],[True,True,False,False])
        self.use(g,3,1);self.use(g,4,1);self.portable(g)

    def test_exhausted_current_copy_attacks_immediately_once(self):
        g=self.game(hand=('copy',));self.use(g,1);self.use(g,2);self.next_turn(g);self.use(g,3);self.use(g,4)
        self.play(g,'copy',self.unit(g).id);self.attack(g,1)
        with self.assertRaises(IllegalAction):self.attack(g,1)
        self.assertNotIn(Keyword.WINDFURY,self.unit(g,1).keywords);self.portable(g)

    def test_base_copy_has_fresh_ability_material(self):
        g=self.game(hand=('basecopy',));self.use(g,1);self.use(g,2);self.play(g,'basecopy',self.unit(g).id)
        self.assertFalse(any(a.consumed for a in self.unit(g,1).abilities if a.kind=='activated'))
        self.use(g,1,1);self.use(g,2,1);self.portable(g)

    def test_return_and_replay_use_original_physical_reset_policy(self):
        g=self.game(hand=('bounce',));eid=self.unit(g).id;self.use(g,1);self.play(g,'bounce',eid)
        self.assertFalse(g.state.entities[eid].old_god_free_used);self.play(g,'god');self.use(g,1);self.use(g,2);self.portable(g)

    def test_free_use_then_freeze_thaws_at_following_turn(self):
        g=self.game(hand=('freeze',));self.use(g,1);self.play(g,'freeze',self.unit(g).id)
        with self.assertRaises(IllegalAction):self.use(g,2)
        g.apply(EndTurn(1));self.assertFalse(self.unit(g).frozen);self.portable(g)

    def test_spent_ordinary_opportunity_then_freeze_waits_for_next_owner_end(self):
        g=self.game(hand=('freeze',));self.use(g,1);self.use(g,2);self.play(g,'freeze',self.unit(g).id)
        self.next_turn(g);self.assertTrue(self.unit(g).frozen)
        with self.assertRaises(IllegalAction):self.use(g,3)
        g.apply(EndTurn(1));self.assertFalse(self.unit(g).frozen);self.portable(g)

    def test_control_does_not_refresh_current_free_marker_or_consumed_skills(self):
        g=self.game(hand=('control',));eid=self.unit(g).id;self.use(g,1);self.play(g,'control',eid)
        self.assertTrue(g.state.entities[eid].old_god_free_used)
        self.assertTrue(next(a for a in g.state.entities[eid].abilities if a.kind=='activated').consumed)
        g.apply(EndTurn(1));self.assertFalse(g.state.entities[eid].old_god_free_used)
        self.use(g,2);self.assertEqual(self.unit(g,player=2).attacks_this_turn,0);self.portable(g)

    def test_silence_removes_native_policy_and_future_skills(self):
        g=self.game(hand=('silence',));self.use(g,1);self.play(g,'silence',self.unit(g).id)
        self.assertNotIn(Keyword.OLD_GOD,self.unit(g).keywords);self.attack(g);self.portable(g)

    def test_dormancy_disables_abilities(self):
        g=self.game(hand=('sleep',));self.play(g,'sleep',self.unit(g).id)
        with self.assertRaises(IllegalAction):self.use(g,1)
        self.portable(g)

    def test_arbitrary_keyword_grant_is_rejected_and_rolls_back(self):
        g=self.game(board=('plain',),hand=('grant',));s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'grant',self.unit(g).id)
        self.assertEqual(g.snapshot(),s)

    def test_waiting_fourth_skill_preserves_consumption_payment_and_resume(self):
        g=self.game(waiting=True);self.use(g,1);self.use(g,2);self.next_turn(g);self.use(g,3);self.next_turn(g);self.use(g,4)
        s=self.portable(g);h=Game.from_snapshot(deepcopy(s),registry(waiting=True));choice=g.state.pending_choice.id
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,choice,('fail',)))
        self.assertEqual(g.snapshot(),s)
        for game in (g,h):game.apply(SelectChoice(1,choice,('finish',)))
        self.assertEqual(g.snapshot(),h.snapshot());self.attack(g);self.portable(g)

    def test_activation_failure_rolls_back_free_and_consumed_state(self):
        g=self.game(fault=True);s=g.snapshot()
        with self.assertRaises(ResolutionError):self.use(g,1)
        self.assertEqual(g.snapshot(),s);self.portable(g)

    def test_boolean_marker_missing_skill_and_old_schema_rejected(self):
        g=self.game();self.use(g,1);s=self.portable(g);eid=str(self.unit(g).id)
        for value in (0,1,None,'false'):
            bad=deepcopy(s);bad['state']['entities'][eid]['old_god_free_used']=value
            with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())
        bad=deepcopy(s);bad['state']['entities'][eid]['abilities'].pop()
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())
        with self.assertRaises(SnapshotError):Game.from_snapshot({**s,'schema_version':250},registry())

    def test_public_command_and_dto_hide_internal_marker(self):
        g=self.game();s=g.snapshot();p=g.for_player(1);listing=p.legal_actions()
        action=next(a for a in listing['actions'] if a['type']=='use_minion_ability' and a['ability_id']=='a1')
        self.assertNotIn('old_god_free_used',json.dumps(p.observe()));self.assertEqual(g.snapshot(),s)
        self.assertTrue(p.submit({'revision':listing['revision'],'action':action})['accepted']);self.use(g,2)
        self.assertFalse(any(a['type']=='use_minion_ability' for a in p.legal_actions()['actions']));self.portable(g)

    def test_main_deck_global_old_god_limit(self):
        r=registry();p=DeckPolicy('diagnostic','diagnostic-old-god','experimental',tuple(r.cards),deck_size=2)
        one=DeckSpec('hero','power',CardClass.MAGE,('god','plain'));two=replace(one,cards=('god','god2'))
        self.assertTrue(validate_deck(one,r,p).valid)
        self.assertIn('old_god_limit',[x.code for x in validate_deck(two,r,p).issues])

    def test_random_generation_excludes_old_god_unless_named_permission(self):
        r=registry();context=GenerationContext('diagnostic-old-god','experimental');query=PoolQuery(kinds=(CardType.MINION,))
        self.assertEqual([x.card_id for x in resolve_candidates(r,context,'pool',query)],['plain'])
        allowed=resolve_candidates(r,context,'pool',query,policy=GenerationPolicy((Keyword.OLD_GOD,)))
        self.assertEqual([x.card_id for x in allowed],['god','plain'])

if __name__=='__main__':unittest.main()
