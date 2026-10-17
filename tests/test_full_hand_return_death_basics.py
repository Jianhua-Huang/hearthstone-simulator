"""Failed BOARD return is an ordinary death, not a successful zone transfer."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from dataclasses import replace
import json
from pathlib import Path
import unittest
from hs_sim.engine import (CardDefinition,CardType,Game,Keyword,PlayCard,PlayerSetup,
    Registry,ResolutionError,Resource,Ruleset,Scenario,SelectChoice,TargetSpec,Zone)
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,Damage,
    GainArmor,InvokeBehavior,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.representative import build_registry,metadata_from_record
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

ROOT=Path(__file__).resolve().parents[1]
PIN='a3850913bc9ea33181868a2bc07264e3032463866b45496ca1fd24af9bf4ebdc'
NATIVE='EX1_581'
def evidence():
    value=json.loads((ROOT/'data/support/full-hand-return-death-basics.json').read_bytes())
    if canonical_digest(value)!=PIN:raise ValueError('Failed return evidence changed')
    return value

def registry():
    r=Registry('isolated-failed-full-hand-return-v1')
    r.register_card(CardDefinition('hero','Diagnostic hero',CardType.HERO,health=60,metadata=metadata()))
    r.register_card(CardDefinition('plain','Diagnostic filler',CardType.SPELL,metadata=metadata()))
    r.register_behavior('armor',lambda c:(GainArmor(c.player_id,c.death.attack),))
    def fault(c):raise ResolutionError('Deliberate return failure')
    r.register_behavior('fault',fault)
    r.register_behavior('waiting',lambda c:(RequestChoice(c.player_id,(
        ChoiceOption('ok','Continue',(GainArmor(c.player_id,c.death.attack),)),
        ChoiceOption('fault','Fail',(InvokeBehavior('fault',c.source_id,c.player_id),))),c.source_id),))
    for cid,body,keywords,corpse in (('body','armor',(),None),('reborn','armor',(Keyword.REBORN,),None),
        ('waiting','waiting',(),None),('fault.body','fault',(),None),('zero','armor',(),0)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=4,attack=3,health=5,
            keywords=keywords,deathrattle=body,corpse_value=corpse,metadata=metadata()))
    raw=next(x for x in evidence()['records'] if x['id']==NATIVE)
    r.register_behavior('sap',lambda c:(ReturnToHand(c.target_id),))
    r.register_card(CardDefinition(raw['id'],raw['name'],CardType.SPELL,cost=raw['cost'],
        on_play='sap',targeting=TargetSpec(kinds=(CardType.MINION,),zones=(Zone.BOARD,),relation='enemy'),metadata=metadata_from_record(raw)))
    def controlled(c):
        return (ChangeControl(c.state.players[1].board[0],2),AddToHand(1,'plain',c.source_id))
    def owner(c):
        return (AddToHand(1,'plain',c.source_id),ReturnToHand(c.state.players[2].board[0],to_owner=True))
    scripts={
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'twice':lambda c:(ReturnToHand(c.target_id),ReturnToHand(c.target_id)),
        'material':lambda c:(Buff(c.target_id,2,3,c.source_id),Damage(c.target_id,2,c.source_id),ReturnToHand(c.target_id)),
        'silenced':lambda c:(Silence(c.target_id),ReturnToHand(c.target_id)),
        'late.fault':lambda c:(ReturnToHand(c.target_id),InvokeBehavior('fault',c.source_id,c.player_id)),
        'control':controlled,'owner':owner,
        'controller':lambda c:(ReturnToHand(c.state.players[2].board[0]),),
        'no.target':lambda c:(ReturnToHand(999999),),
        'sequential':lambda c:tuple(ReturnToHand(i) for i in c.state.players[2].board)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body)
        targeting=TargetSpec(kinds=(CardType.MINION,),zones=(Zone.BOARD,),relation='enemy') if cid in (
            'bounce','twice','material','silenced','late.fault') else None
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=targeting,metadata=metadata()))
    return r

class FullHandReturnDeathTests(unittest.TestCase):
    def game(self,hand=(NATIVE,),enemy_hand=('plain',)*10,enemy_board=('body',),board=(),rules=None):
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,board=board,deck=('plain',)*4,max_mana=10,mana=10),
            PlayerSetup('hero',hand=enemy_hand,board=enemy_board,deck=('plain',)*4,max_mana=10,mana=10)),seed=152),registry(),rules)
    def play(self,g,cid=NATIVE,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target));return eid
    def target(self,g):return g.state.players[2].board[0]
    def armor(self,g,p=2):return g.state.entities[g.state.players[p].hero_id].armor
    def corpses(self,g,p=2):return g.state.players[p].resources[Resource.CORPSES]
    def choose(self,g,name='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(name,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));h=Game.from_snapshot(s,registry())
        self.assertEqual(h.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),s);return h

    def test_pinned_necessary_source_and_default_registry_stays_unchanged(self):
        raw=next(x for x in evidence()['records'] if x['id']==NATIVE)
        original=next(x for x in json.loads((ROOT/'data/extracted/cards.json').read_bytes()) if x['id']==NATIVE)
        self.assertEqual(raw,original);card=registry().card(NATIVE)
        self.assertEqual((card.cost,card.on_play),(2,'sap'));self.assertEqual(card.metadata,metadata_from_record(raw))
        self.assertNotIn('NEW1_004',registry().cards)
        # The committed Dark Gift expansion added five definitions after this
        # test's original v64/306-definition foundation baseline.
        default = build_registry()
        self.assertEqual((default.version, len(default.cards)), ('representative-m5-v65', 311))
        self.assertEqual(default.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_full_hand_sap_commits_original_death_and_deathrattle(self):
        g=self.game();target=self.target(g);before=g.state.entities[target];self.play(g,target=target)
        self.assertEqual(len(g.state.death_history),1);d=g.state.death_history[0]
        self.assertEqual((d.entity_id,d.zone,d.owner,d.controller),(target,Zone.BOARD,2,2))
        self.assertEqual((d.cause.kind,d.cause.reason,d.cause.target_zone_epoch),('destroy','ReturnToHand',before.zone_epoch))
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual(self.armor(g),3);self.assertEqual(self.corpses(g),1)
        self.assertEqual(len(g.state.players[2].hand),10);self.assertEqual(g.state.players[1].mana,8);self.portable(g)

    def test_failure_has_burn_notice_and_death_without_successful_return(self):
        g=self.game();target=self.target(g);self.play(g,target=target)
        kinds=[e.kind for e in g._events if e.target_id==target or e.source_id==target]
        self.assertEqual(kinds.count('card_burned'),1);self.assertEqual(kinds.count('minion_died'),1)
        self.assertNotIn('card_returned',kinds);self.assertEqual(len(g.state.discard_history),0)
        self.assertEqual(len(g.state.draw_history),0);self.portable(g)

    def test_nonfull_hand_sap_keeps_original_success_path(self):
        g=self.game(enemy_hand=('plain',)*9);target=self.target(g);self.play(g,target=target)
        self.assertIn(target,g.state.players[2].hand);self.assertEqual(len(g.state.players[2].hand),10)
        self.assertEqual(g.state.death_history,[]);self.assertEqual(self.armor(g),0);self.assertEqual(self.corpses(g),0);self.portable(g)

    def test_current_death_material_is_not_reset_before_death(self):
        g=self.game(hand=('material',));target=self.target(g);self.play(g,'material',target)
        d=g.state.death_history[0]
        self.assertEqual((d.attack,d.max_health,d.damage,d.base_cost),(5,8,2,4))
        self.assertTrue(d.enchantments);self.assertEqual(self.armor(g),5);self.portable(g)

    def test_reborn_uses_original_death_and_fresh_board_body(self):
        g=self.game(enemy_board=('reborn',));old=self.target(g);self.play(g,target=old)
        self.assertEqual(len(g.state.death_history),1);self.assertEqual(self.corpses(g),1);self.assertEqual(self.armor(g),3)
        new=g.state.entities[self.target(g)];self.assertNotEqual(old,new.id);self.assertEqual(new.health,1)
        self.assertNotIn(Keyword.REBORN,new.keywords);self.assertEqual(len(g.state.players[2].hand),10);self.portable(g)

    def test_silenced_carrier_dies_without_reinstalling_native_deathrattle(self):
        g=self.game(hand=('silenced',));target=self.target(g);self.play(g,'silenced',target)
        self.assertEqual(len(g.state.death_history),1);self.assertEqual(self.armor(g),0);self.assertEqual(self.corpses(g),1)
        self.assertFalse(any(a.kind=='deathrattle' for a in g.state.death_history[0].abilities));self.portable(g)

    def test_no_corpse_carrier_still_has_ordinary_death_and_body(self):
        g=self.game(enemy_board=('zero',));self.play(g,target=self.target(g))
        self.assertEqual(len(g.state.death_history),1);self.assertEqual(self.armor(g),3);self.assertEqual(self.corpses(g),0);self.portable(g)

    def test_duplicate_request_does_not_allocate_second_death(self):
        g=self.game(hand=('twice',));self.play(g,'twice',self.target(g))
        self.assertEqual(len(g.state.death_history),1);self.assertEqual(self.armor(g),3);self.assertEqual(self.corpses(g),1);self.portable(g)

    def test_sequential_returns_respect_actual_remaining_capacity(self):
        g=self.game(hand=('sequential',),enemy_hand=('plain',)*9,enemy_board=('body','body'))
        first,second=g.state.players[2].board;self.play(g,'sequential')
        self.assertIn(first,g.state.players[2].hand);self.assertEqual(g.state.death_history[0].entity_id,second)
        self.assertEqual(len(g.state.death_history),1);self.assertEqual(self.armor(g),3);self.assertEqual(len(g.state.players[2].hand),10);self.portable(g)

    def test_owner_destination_does_not_change_controller_before_death(self):
        g=self.game(hand=('control','owner')+('plain',)*8,board=('body',),enemy_hand=(),enemy_board=())
        original=g.state.players[1].board[0];self.play(g,'control');self.play(g,'owner')
        d=g.state.death_history[0];self.assertEqual((d.entity_id,d.owner,d.controller),(original,1,2))
        self.assertEqual(g.state.entities[original].controller,2);self.assertEqual(self.armor(g,1),0);self.assertEqual(self.armor(g,2),3)
        self.assertEqual(self.corpses(g,1),0);self.assertEqual(self.corpses(g,2),1)
        burn=next(e for e in g._events if e.kind=='card_burned');self.assertEqual(burn.player_id,1);self.portable(g)

    def test_current_controller_destination_can_succeed_when_owner_hand_is_full(self):
        g=self.game(hand=('control','controller')+('plain',)*8,board=('body',),enemy_hand=(),enemy_board=())
        original=g.state.players[1].board[0];self.play(g,'control');self.play(g,'controller')
        self.assertIn(original,g.state.players[2].hand);self.assertEqual(g.state.death_history,[])
        self.assertEqual(g.state.entities[original].owner,1);self.portable(g)

    def test_configured_capacity_is_used_instead_of_literal_ten(self):
        for count in (11,12):
            with self.subTest(count=count):
                g=self.game(enemy_hand=('plain',)*count,rules=Ruleset(max_hand=12));target=self.target(g);self.play(g,target=target)
                self.assertEqual(len(g.state.players[2].hand),12)
                self.assertEqual(len(g.state.death_history),int(count==12));self.portable(g)

    def test_waiting_deathrattle_restores_and_resumes_once(self):
        g=self.game(enemy_board=('waiting',));self.play(g,target=self.target(g))
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(g.state.death_history),1);self.assertEqual(self.armor(g),0)
        h=self.portable(g);self.choose(g);self.choose(h);self.assertEqual(g.snapshot(),h.snapshot())
        self.assertEqual(self.armor(g),3);self.assertEqual(len(g.state.death_history),1);self.portable(g)

    def test_deathrattle_failure_rolls_back_the_paid_sap_action(self):
        g=self.game(enemy_board=('fault.body',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,target=self.target(g))
        self.assertEqual(g.snapshot(),before)

    def test_failed_waiting_selection_preserves_original_waiting_state(self):
        g=self.game(enemy_board=('waiting',));self.play(g,target=self.target(g));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.portable(g);self.choose(g);self.portable(g)

    def test_late_failure_rolls_back_death_corpse_and_deathrattle(self):
        g=self.game(hand=('late.fault',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'late.fault',self.target(g))
        self.assertEqual(g.snapshot(),before)

    def test_missing_target_is_stale_and_does_not_create_a_death(self):
        g=self.game(hand=('no.target',));self.play(g,'no.target')
        self.assertEqual(g.state.death_history,[]);self.assertEqual(self.corpses(g),0);self.portable(g)

    def test_player_boundary_does_not_expose_private_death_material(self):
        g=self.game(enemy_board=('waiting',));self.play(g,target=self.target(g));before=g.snapshot()
        for p in (1,2):
            view=json.dumps(g.for_player(p).observe());events=json.dumps(g.for_player(p).events())
            g.for_player(p).legal_actions()
            for key in ('death_history','DeathCause','resolution_frame','behavior_id','target_zone_epoch'):
                self.assertNotIn(key,view);self.assertNotIn(key,events)
        self.assertEqual(g.snapshot(),before);self.choose(g);self.portable(g)

if __name__=='__main__':unittest.main()
