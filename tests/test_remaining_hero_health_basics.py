"""Remaining Hero health assignment preserves maximum and bypasses health flows."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,HealthLossReplacementSpec,
    IllegalAction,Keyword,PlayCard,PlayerSetup,Registry,ResolutionError,Scenario,SelectChoice,
    SetHeroHealth,SnapshotError,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.effects import (Buff,ChoiceOption,GainArmor,Heal,InvokeBehavior,
    ReplaceHero,RequestChoice,SetStats)
from hs_sim.engine.health_loss import LoseHealth
from hs_sim.engine.hero_health_history import health_change_count,validate_health_set_event
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

ROOT=Path(__file__).resolve().parents[1]
PIN='37c35154606c7d51c6fdb4a8a2a20aae3209e50e728492a2750f13fbad05659d'
def evidence():
    value=json.loads((ROOT/'data/support/remaining-hero-health-basics.json').read_bytes())
    if canonical_digest(value)!=PIN: raise ValueError('Remaining Hero health evidence changed')
    return value

def registry():
    r=Registry('isolated-remaining-hero-health-v1')
    for name,health,keywords in (('hero',30,()),('small',10,()),('replacement',40,()),
            ('immune',30,(Keyword.IMMUNE,)),('shield',30,(Keyword.DIVINE_SHIELD,))):
        r.register_card(CardDefinition(name,'Diagnostic '+name,CardType.HERO,health=health,keywords=keywords,metadata=metadata()))
    r.register_card(CardDefinition('plain','Diagnostic minion',CardType.MINION,health=5,metadata=metadata()))
    r.register_card(CardDefinition('loss-replacement','Diagnostic existing loss replacement',CardType.MINION,health=5,
        health_loss_replacements=(HealthLossReplacementSpec(),),metadata=metadata()))
    r.register_behavior('notice',lambda c:(GainArmor(c.player_id,1),))
    for name,event in (('healing-watch','healed'),('loss-watch','health_lost'),('damage-watch','damage_dealt')):
        r.register_card(CardDefinition(name,'Diagnostic '+name,CardType.MINION,health=5,
            triggers=(TriggerSpec(event,'notice'),),metadata=metadata()))
    def explode(c): raise ResolutionError('Diagnostic remaining Hero failure')
    r.register_behavior('explode',explode)
    def wait(c):
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('fault','Fail',(InvokeBehavior('explode',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior('waiting',wait)
    r.register_behavior('event-wait',lambda c:(RequestChoice(c.player_id,
        (ChoiceOption('ok','Continue',(GainArmor(c.player_id,abs(c.event.amount)),)),),c.source_id),))
    r.register_card(CardDefinition('event-watch','Diagnostic assignment callback',CardType.MINION,health=5,
        triggers=(TriggerSpec('hero_health_set','event-wait'),),metadata=metadata()))
    def hero(c,p=None): return c.state.players[c.player_id if p is None else p].hero_id
    scripts={
        'set':lambda c:(SetHeroHealth(hero(c),15,c.source_id),),
        'enemy':lambda c:(SetHeroHealth(hero(c,2),15,c.source_id),),
        'setup':lambda c:(LoseHealth(hero(c),20,c.source_id),),
        'heal':lambda c:(Heal(hero(c),5,c.source_id),),
        'maximum':lambda c:(Buff(hero(c),health=10,source_id=c.source_id),),
        'stats':lambda c:(SetStats(hero(c),health=15,source_id=c.source_id),),
        'zero':lambda c:(SetHeroHealth(hero(c),0,c.source_id),),
        'enemy-zero':lambda c:(SetHeroHealth(hero(c,2),0,c.source_id),),
        'system':lambda c:(SetHeroHealth(hero(c),15),),
        'fault':lambda c:(SetHeroHealth(hero(c),15,c.source_id),InvokeBehavior('explode',c.source_id,c.player_id)),
        'bad-source':lambda c:(SetHeroHealth(hero(c),15,999999),),
        'wrong-target':lambda c:(SetHeroHealth(c.state.players[2].board[0],15,c.source_id),),
        'wait':lambda c:(SetHeroHealth(hero(c),15,c.source_id),InvokeBehavior('waiting',c.source_id,c.player_id)),
        'before':lambda c:(RequestChoice(c.player_id,(
            ChoiceOption('set','Set',(SetHeroHealth(hero(c),15,c.source_id),)),),c.source_id),),
        'replace-before':lambda c:(ReplaceHero(2,'replacement'),SetHeroHealth(hero(c,2),15,c.source_id)),
        'sequential':lambda c:(SetHeroHealth(hero(c),15,c.source_id),SetHeroHealth(hero(c),5,c.source_id)),
    }
    for name,script in scripts.items():
        r.register_behavior(name,script)
        r.register_card(CardDefinition(name,'Diagnostic '+name,CardType.SPELL,on_play=name,metadata=metadata()))
    raw=next(x for x in evidence()['records'] if x['id']=='EX1_561')
    r.register_behavior('alex',lambda c:(SetHeroHealth(c.target_id,15,c.source_id),))
    r.register_card(CardDefinition(raw['id'],raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        on_play='alex',targeting=TargetSpec(zones=(Zone.HERO,),kinds=(CardType.HERO,)),metadata=metadata_from_record(raw)))
    return r

class RemainingHeroHealthTests(unittest.TestCase):
    def game(self,hand=('set',),hero='hero',board=()):
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=('plain',)*6,
            armor=9,max_mana=10,mana=10),PlayerSetup('hero',hand=('set',),board=('plain',),deck=('plain',)*6,
            armor=9,max_mana=10,mana=10)),seed=146),registry())
    def hero(self,g,p=1): return g.state.entities[g.state.players[p].hero_id]
    def play(self,g,name,target=None):
        p=g.state.active_player
        card=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==name)
        return g.apply(PlayCard(p,card,target))
    def events(self,g): return [e for e in g.events if e.kind=='hero_health_set']
    def rows(self,g): return g.state.hero_health_change_history
    def portable(self,g):
        s=g.snapshot()
        for h in (Game.from_snapshot(json.loads(json.dumps(s)),registry()),g.clone(),replay(build_replay(g),registry())):
            self.assertEqual(h.snapshot(),s)
            for p in (1,2):
                self.assertEqual(h.observe(p),g.observe(p)); self.assertEqual(h.player_events(p),g.player_events(p))
        return s

    def test_one_real_adapter_keeps_other_six_raw_rows_and_uncalibrated_policy(self):
        value=evidence(); self.assertEqual(len(value['records']),7); self.assertFalse(value['CN_calibrated'])
        self.assertFalse(value['above_maximum_policy_CN_calibrated']); self.assertEqual(value['new_combinations'],0)
        for name in ('VAN_EX1_561','CORE_VAN_EX1_561','MIS_703','CATA_307','GIL_813','SCH_317'):
            self.assertNotIn(name,registry().cards)
        g=self.game(hand=('EX1_561',)); self.play(g,'EX1_561',self.hero(g,2).id)
        self.assertEqual((self.hero(g,2).health,self.hero(g,2).max_health,self.hero(g,2).armor,g.state.players[1].mana),(15,30,9,1))
        self.assertEqual(self.rows(g)[0].event_kind,'hero_health_set'); self.portable(g)

    def test_lowering_current_health_preserves_original_maximum_and_armor(self):
        g=self.game(); self.play(g,'set')
        self.assertEqual((self.hero(g).health,self.hero(g).max_health,self.hero(g).damage,self.hero(g).armor),(15,30,15,9))
        row=self.rows(g)[0]; self.assertEqual((row.health_before,row.health_after,row.max_health_before,row.max_health_after),(30,15,30,30))
        self.assertEqual(self.events(g)[0].amount,-15); self.portable(g)

    def test_raising_current_health_does_not_create_healing(self):
        g=self.game(hand=('setup','set')); self.play(g,'setup'); count=len(g.events); self.play(g,'set')
        self.assertEqual((self.hero(g).health,self.hero(g).max_health,self.hero(g).armor),(15,30,9))
        self.assertFalse({'healed','health_lost','health_resolved','damage_dealt'} & {e.kind for e in g.events[count:]})
        self.assertEqual(g.state.healing_history,[]); self.assertEqual(g.state.damage_history,[]); self.portable(g)

    def test_unchanged_assignment_has_zero_event_without_extra_health_occurrence(self):
        g=self.game(hand=('set','system')); self.play(g,'set'); self.play(g,'system')
        self.assertEqual([e.amount for e in self.events(g)],[-15,0]); self.assertEqual(len(self.rows(g)),1)
        self.assertEqual(health_change_count(g.state,1),1); self.portable(g)

    def test_over_maximum_request_clamps_as_explicit_local_policy(self):
        g=self.game(hero='small'); self.play(g,'set')
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(10,10))
        self.assertEqual(dict(self.events(g)[0].data)['requested'],15)
        self.assertEqual(self.rows(g),[]); self.portable(g)

    def test_later_healing_can_use_preserved_maximum(self):
        g=self.game(hand=('set','heal')); self.play(g,'set'); self.play(g,'heal')
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(20,30)); self.portable(g)

    def test_immunity_and_shield_are_preserved_without_blocking_assignment(self):
        for name in ('immune','shield'):
            with self.subTest(name=name):
                g=self.game(hero=name); before=self.hero(g).keywords; self.play(g,'set')
                self.assertEqual((self.hero(g).health,self.hero(g).armor),(15,9))
                self.assertEqual(self.hero(g).keywords,before); self.portable(g)

    def test_ordinary_health_listeners_do_not_receive_assignment(self):
        g=self.game(board=('healing-watch','loss-watch','damage-watch')); self.play(g,'set')
        self.assertEqual(self.hero(g).armor,9)
        self.assertFalse({'healed','health_lost','health_resolved','damage_dealt','health_spent'} & {e.kind for e in g.events})
        self.portable(g)

    def test_existing_loss_replacement_does_not_intercept_current_assignment(self):
        g=self.game(board=('loss-replacement',)); self.play(g,'set')
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(15,30))
        self.assertFalse(any(e.kind=='health_loss_replaced' for e in g.events)); self.portable(g)

    def test_existing_maximum_enchantment_is_kept_without_new_attachment(self):
        g=self.game(hand=('maximum','set')); self.play(g,'maximum'); before=self.hero(g).enchantments
        allocator=g.state.next_attachment_id; self.play(g,'set')
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(15,40))
        self.assertEqual(self.hero(g).enchantments,before); self.assertEqual(g.state.next_attachment_id,allocator); self.portable(g)

    def test_old_set_stats_retains_its_distinct_maximum_setting_semantics(self):
        g=self.game(hand=('stats',)); self.play(g,'stats')
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(15,15))
        self.assertFalse(self.events(g)); self.assertEqual(self.rows(g)[0].event_kind,'stats_changed'); self.portable(g)

    def test_zero_assignment_uses_existing_hero_death_and_non_damage_cause(self):
        g=self.game(hand=('zero',)); self.play(g,'zero')
        self.assertEqual((g.state.status,g.state.winner),('finished',2))
        cause=self.hero(g).death_cause
        self.assertEqual((cause.kind,cause.reason),('health_state','remaining_health_assignment'))
        self.assertEqual(cause.source_id,self.events(g)[0].source_id)
        self.assertFalse(cause.result); self.assertEqual(g.state.damage_history,[]); self.portable(g)

    def test_opponent_zero_assignment_preserves_actual_target_and_terminal_winner(self):
        g=self.game(hand=('enemy-zero',)); self.play(g,'enemy-zero')
        self.assertEqual((g.state.status,g.state.winner),('finished',1))
        self.assertEqual((self.rows(g)[0].player_id,self.rows(g)[0].active_player),(2,1)); self.portable(g)

    def test_replaced_physical_target_is_skipped_without_aliasing_new_hero(self):
        g=self.game(hand=('replace-before',)); old=self.hero(g,2).id; self.play(g,'replace-before')
        self.assertNotEqual(self.hero(g,2).id,old)
        self.assertEqual((self.hero(g,2).health,self.hero(g,2).max_health),(30,40))
        self.assertFalse(self.events(g)); self.portable(g)

    def test_wrong_minion_and_unknown_source_reject_with_full_rollback(self):
        for name in ('wrong-target','bad-source'):
            with self.subTest(name=name):
                g=self.game(hand=(name,)); before=g.snapshot()
                with self.assertRaises(ResolutionError): self.play(g,name)
                self.assertEqual(g.snapshot(),before)

    def test_source_less_assignment_is_valid_and_keeps_public_target(self):
        g=self.game(hand=('system',)); self.play(g,'system')
        self.assertIsNone(self.events(g)[0].source_id); self.assertEqual(self.events(g)[0].target_id,self.hero(g).id); self.portable(g)

    def test_sequential_assignments_use_current_health_and_original_maximum(self):
        g=self.game(hand=('sequential',)); self.play(g,'sequential')
        self.assertEqual([e.amount for e in self.events(g)],[-15,-10])
        self.assertEqual([(r.health_before,r.health_after) for r in self.rows(g)],[(30,15),(15,5)])
        self.assertEqual(self.hero(g).max_health,30); self.portable(g)

    def test_assignment_waiting_boundary_restores_and_resumes(self):
        g=self.game(hand=('wait',)); self.play(g,'wait'); snapshot=self.portable(g)
        h=Game.from_snapshot(deepcopy(snapshot),registry()); action=SelectChoice(1,g.state.pending_choice.id,('ok',))
        g.apply(action); h.apply(action); self.assertEqual(g.snapshot(),h.snapshot())
        self.assertEqual((self.hero(g).health,self.hero(g).max_health,self.hero(g).armor),(15,30,10)); self.portable(g)

    def test_pending_typed_assignment_effect_restores_before_execution(self):
        g=self.game(hand=('before',)); self.play(g,'before'); snapshot=self.portable(g)
        h=Game.from_snapshot(deepcopy(snapshot),registry()); action=SelectChoice(1,g.state.pending_choice.id,('set',))
        g.apply(action); h.apply(action); self.assertEqual(g.snapshot(),h.snapshot())
        self.assertEqual(self.hero(g).health,15); self.portable(g)

    def test_captured_assignment_event_waiting_frame_preserves_original_transition(self):
        g=self.game(board=('event-watch','event-watch')); self.play(g,'set'); snapshot=self.portable(g)
        h=Game.from_snapshot(deepcopy(snapshot),registry())
        for _ in range(2):
            action=SelectChoice(1,g.state.pending_choice.id,('ok',))
            g.apply(action); h.apply(action); self.assertEqual(g.snapshot(),h.snapshot()); self.portable(g)
        self.assertEqual((self.hero(g).health,self.hero(g).armor),(15,39)); self.portable(g)

    def test_action_and_later_choice_exception_preserve_correct_committed_boundary(self):
        g=self.game(hand=('fault',)); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'fault')
        self.assertEqual(g.snapshot(),before)
        h=self.game(hand=('wait',)); self.play(h,'wait'); before=h.snapshot()
        with self.assertRaises(ResolutionError): h.apply(SelectChoice(1,h.state.pending_choice.id,('fault',)))
        self.assertEqual(h.snapshot(),before); self.portable(h)

    def test_existing_own_turn_quantity_is_pure_and_ignores_opponent_changes(self):
        g=self.game(hand=('enemy','set')); self.play(g,'enemy'); self.play(g,'set'); before=g.snapshot()
        self.assertEqual((health_change_count(g.state,1),health_change_count(g.state,2)),(1,0))
        self.assertEqual(g.snapshot(),before); g.apply(EndTurn(1)); self.play(g,'set')
        self.assertEqual(health_change_count(g.state,2),0); self.portable(g)

    def test_real_target_validation_keeps_payment_and_history_on_one_root(self):
        g=self.game(hand=('EX1_561',)); before=g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g,'EX1_561',g.state.players[2].board[0])
        self.assertEqual(g.snapshot(),before); self.play(g,'EX1_561',self.hero(g).id)
        self.assertEqual((g.state.players[1].mana,len(g.state.play_history),health_change_count(g.state,1)),(1,1,1)); self.portable(g)

    def test_strict_input_and_assignment_envelope_reject_inconsistent_operands(self):
        for health in (True,-1,1.5,'15'):
            with self.subTest(health=health),self.assertRaises(ValueError): SetHeroHealth(1,health)
        g=self.game(); self.play(g,'set'); event=self.events(g)[0]
        validate_health_set_event(event)
        for bad in (replace(event,amount=15),replace(event,player_id=True),replace(event,target_id=True),replace(event,data=())):
            with self.subTest(bad=bad),self.assertRaises(ValueError): validate_health_set_event(bad)
        with self.assertRaises(ValueError): replace(self.rows(g)[0],max_health_after=31)

    def test_rehashed_snapshot_rejects_changed_requested_delta_missing_envelope_and_old_schema(self):
        g=self.game(); self.play(g,'set'); original=self.portable(g)
        for mode in ('amount','requested','missing'):
            bad=deepcopy(original); event=next(e for e in bad['events'] if e['kind']=='hero_health_set')
            if mode=='amount': event['amount']=0
            elif mode=='requested': event['data']['requested']=True
            else: del event['data']['hero_health_transition']
            bad['events_hash']=canonical_hash(bad['events'])
            with self.subTest(mode=mode),self.assertRaises(SnapshotError): Game.from_snapshot(bad,registry())
        bad=deepcopy(original); bad['schema_version']=243
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad,registry())

    def test_player_view_publishes_current_health_and_delta_without_private_transition(self):
        g=self.game(); self.play(g,'set'); before=g.snapshot()
        for p in (1,2):
            view=g.for_player(p).observe()['observation']; events=g.player_events(p)
            self.assertEqual(view['version'],'player-view-v86')
            self.assertEqual((view['players'][0]['hero']['health'],view['players'][0]['hero']['max_health']),(15,30))
            self.assertEqual([e['amount'] for e in events if e['kind']=='hero_health_set'],[-15])
            text=json.dumps({'view':view,'events':events})
            for private in ('hero_health_transition','hero_health_change_id','hero_health_change_history','"requested"'):
                self.assertNotIn(private,text)
        self.assertEqual(g.snapshot(),before); self.portable(g)

if __name__=='__main__': unittest.main()
