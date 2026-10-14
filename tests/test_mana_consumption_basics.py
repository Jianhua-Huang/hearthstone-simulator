"""Independent non-cost mana spending, original facts and actual spell quantity."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,IllegalAction,PlayCard,
    PlayerSetup,PlayerSpellManaCostSpec,Registry,ResolutionError,Scenario,SelectChoice,
    SnapshotError,SpellSchool,SpendMana,TargetSpec,TriggerSpec,Zone,mana_consumption_result)
from hs_sim.engine.effects import (ChoiceOption,Damage,DamageKind,GainArmor,
    GainTemporaryMana,InvokeBehavior,RefreshMana,RequestChoice)
from hs_sim.engine.model import ManaConsumptionRecord
from hs_sim.engine.player_spell_mana_costs import capture,validate_prefix
from hs_sim.engine.resources import validate_mana_consumption_events,validate_mana_consumption_history
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

ROOT=Path(__file__).resolve().parents[1]
PIN='b7abef0727271f56bd832184f488e42a8c2eeedcdfdc6da635ef03dc17318afa'
def evidence():
    value=json.loads((ROOT/'data/support/mana-consumption-basics.json').read_bytes())
    if canonical_digest(value)!=PIN: raise ValueError('Mana consumption evidence changed')
    return value

def registry():
    r=Registry('isolated-direct-mana-consumption-v1')
    r.register_card(CardDefinition('hero','Diagnostic hero',CardType.HERO,health=80,metadata=metadata()))
    r.register_card(CardDefinition('plain','Diagnostic minion',CardType.MINION,attack=1,health=30,metadata=metadata()))
    r.register_card(CardDefinition('price','Diagnostic existing spell-mana formula',CardType.MINION,cost=20,health=5,
        player_spell_mana_cost=PlayerSpellManaCostSpec(),metadata=metadata()))
    def explode(c): raise ResolutionError('Diagnostic mana failure')
    r.register_behavior('explode',explode)
    def result(c):
        row=c.mana_result
        if type(row) is not ManaConsumptionRecord or c.state.players[row.player_id].mana!=row.mana_after:
            raise ResolutionError('Mana callback lost original debit context')
        return (GainArmor(c.player_id,row.actual),)
    r.register_behavior('result',result)
    def waiting(c):
        row=c.mana_result
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',(GainArmor(c.player_id,row.actual),)),
            ChoiceOption('fault','Fail',(InvokeBehavior('explode',c.source_id,c.player_id),)),),c.source_id),)
    r.register_behavior('waiting',waiting)
    r.register_behavior('quote-wait',lambda c:(RequestChoice(c.player_id,
        (ChoiceOption('ok','Finish',(GainArmor(c.player_id,1),)),),c.source_id),))
    r.register_card(CardDefinition('affordable-price','Diagnostic same formula paid continuation',CardType.MINION,
        cost=8,health=5,on_play='quote-wait',player_spell_mana_cost=PlayerSpellManaCostSpec(),metadata=metadata()))
    scripts={
        'all':lambda c:(SpendMana(c.player_id,source_id=c.source_id),),
        'fixed':lambda c:(SpendMana(c.player_id,5,c.source_id),),
        'zero':lambda c:(SpendMana(c.player_id,0,c.source_id),),
        'enemy':lambda c:(SpendMana(2,5,c.source_id),),
        'system':lambda c:(SpendMana(1,5),),
        'result':lambda c:(SpendMana(1,5,c.source_id,'result'),),
        'wait':lambda c:(SpendMana(1,5,c.source_id,'waiting'),),
        'fault':lambda c:(SpendMana(1,5,c.source_id),InvokeBehavior('explode',c.source_id,1)),
        'bad-source':lambda c:(SpendMana(1,5,999999),),
        'bad-callback':lambda c:(SpendMana(1,5,c.source_id,'unknown'),),
        'two':lambda c:(SpendMana(1,3,c.source_id),SpendMana(1,source_id=c.source_id)),
        'refresh':lambda c:(RefreshMana(1,10),),
        'temporary':lambda c:(GainTemporaryMana(1,3),),
        'auto':lambda c:(CastSpell(1,'all',c.source_id),),
    }
    for name,script in scripts.items():
        behavior='spell.'+name
        r.register_behavior(behavior,script)
        r.register_card(CardDefinition(name,'Diagnostic '+name,CardType.SPELL,on_play=behavior,
            cost=2 if name=='all' else 0,metadata=metadata()))
    r.register_behavior('react',lambda c:(GainTemporaryMana(c.event.player_id,2),))
    r.register_card(CardDefinition('reactor','Diagnostic consumption reaction',CardType.MINION,health=5,
        triggers=(TriggerSpec('mana_consumed','react'),),metadata=metadata()))
    r.register_behavior('native-spend',lambda c:(SpendMana(c.player_id,source_id=c.source_id),))
    r.register_card(CardDefinition('native','Diagnostic non-spell source',CardType.MINION,health=5,
        on_play='native-spend',metadata=metadata()))
    raw=next(x for x in evidence()['records'] if x['id']=='OG_086')
    r.register_behavior('flame',lambda c:(SpendMana(c.player_id,source_id=c.source_id,on_result='flame-result'),))
    r.register_behavior('flame-result',lambda c:(Damage(c.cast.target_id,c.mana_result.actual,c.source_id,DamageKind.SPELL),))
    r.register_card(CardDefinition('OG_086',raw['name'],CardType.SPELL,cost=0,on_play='flame',
        spell_school=SpellSchool.FIRE,targeting=TargetSpec(kinds=(CardType.MINION,),zones=(Zone.BOARD,)),metadata=metadata_from_record(raw)))
    return r

class ManaConsumptionTests(unittest.TestCase):
    def game(self,hand=('fixed','price'),mana=8,temporary=3,locked=2,owed=0,spent=None,board=()):
        g=Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,board=board,deck=('plain',)*6,
            max_mana=10,mana=mana,temporary_mana=temporary,overload_locked=locked,overload_owed=owed),
            PlayerSetup('hero',hand=('plain',),board=('plain',),deck=('plain',)*6,max_mana=10,mana=10)),seed=144),registry())
        if spent is not None: self.assertEqual(g.state.players[1].mana_spent,spent)
        return g
    def play(self,g,name,target=None):
        card=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name)
        return g.apply(PlayCard(1,card,target))
    def player(self,g,p=1): return g.state.players[p]
    def armor(self,g,p=1): return g.state.entities[g.state.players[p].hero_id].armor
    def rows(self,g): return g.state.mana_consumption_history
    def fact(self,g): return capture(g.state,g.registry,1,g.registry.card('price'),20)
    def portable(self,g):
        s=g.snapshot()
        for h in (Game.from_snapshot(json.loads(json.dumps(s)),registry()),g.clone(),replay(build_replay(g),registry())):
            self.assertEqual(h.snapshot(),s)
            for viewer in (1,2):
                self.assertEqual(h.observe(viewer),g.observe(viewer)); self.assertEqual(h.player_events(viewer),g.player_events(viewer))
        return s

    def test_only_one_necessary_real_adapter_and_all_raw_rows_retained(self):
        value=evidence(); self.assertEqual(len(value['records']),12); self.assertFalse(value['CN_calibrated'])
        self.assertEqual(value['new_combinations'],0)
        for name in ('OG_051','EDR_520','TSC_829'): self.assertNotIn(name,registry().cards)
        g=self.game(hand=('OG_086','price')); target=self.player(g,2).board[0]
        self.play(g,'OG_086',target)
        self.assertEqual((self.player(g).mana,g.state.entities[target].health),(0,22))
        self.assertEqual((g.state.play_history[-1].cost,self.rows(g)[0].actual),(0,8))
        self.assertEqual(self.fact(g).quantity,8); self.portable(g)

    def test_fixed_debit_uses_existing_temporary_first_projection(self):
        g=self.game(spent=3); self.play(g,'fixed'); p=self.player(g); row=self.rows(g)[0]
        self.assertEqual((p.max_mana,p.mana,p.temporary_mana,p.mana_spent,p.overload_locked),(10,3,0,5,2))
        self.assertEqual((row.mana_before,row.mana_after,row.actual,row.temporary_before,row.spent_before),(8,3,5,3,3))
        self.portable(g)

    def test_request_larger_than_balance_is_capped(self):
        g=self.game(mana=2,temporary=0); self.play(g,'fixed')
        self.assertEqual((self.player(g).mana,self.rows(g)[0].requested,self.rows(g)[0].actual),(0,5,2)); self.portable(g)

    def test_all_spends_post_payment_balance_without_rewriting_original_cost(self):
        g=self.game(hand=('all','price')); self.play(g,'all')
        self.assertEqual((g.state.play_history[-1].cost,self.rows(g)[0].mana_before,self.rows(g)[0].actual),(2,6,6))
        self.assertEqual((self.player(g).max_mana,self.player(g).mana),(10,0))
        self.assertEqual(self.fact(g).quantity,8); self.portable(g)

    def test_zero_and_empty_balance_keep_result_without_positive_reaction(self):
        for name,mana in (('zero',8),('fixed',0)):
            with self.subTest(name=name):
                g=self.game(hand=(name,),mana=mana,temporary=0,board=('reactor',)); self.play(g,name)
                self.assertEqual((self.player(g).mana,self.rows(g)[0].actual),(mana,0))
                self.assertFalse(any(e.kind=='mana_consumed' for e in g.events)); self.portable(g)

    def test_unbounded_temporary_mana_and_locked_permanent_balance_remain_correct(self):
        g=self.game(hand=('fixed',),mana=18,temporary=20,locked=12)
        self.play(g,'fixed'); p=self.player(g)
        self.assertEqual((p.mana,p.temporary_mana,p.mana_spent,p.max_mana,p.overload_locked),(13,15,0,10,12)); self.portable(g)

    def test_direct_debit_keeps_crystals_and_pending_overload(self):
        g=self.game(owed=4); self.play(g,'fixed')
        self.assertEqual((self.player(g).max_mana,self.player(g).overload_owed),(10,4)); self.portable(g)

    def test_other_player_and_system_sources_have_explicit_attribution(self):
        g=self.game(hand=('enemy','system','price')); self.play(g,'enemy'); self.play(g,'system')
        enemy,system=self.rows(g)
        self.assertEqual((enemy.player_id,enemy.source_player_id,enemy.actual),(2,1,5))
        self.assertIsNone(system.source_id); self.assertEqual((self.player(g,2).mana,self.player(g).mana),(5,3))
        self.assertEqual(self.fact(g).quantity,0); self.portable(g)

    def test_non_spell_source_consumption_is_not_spell_quantity(self):
        g=self.game(hand=('native','price')); self.play(g,'native')
        self.assertEqual((self.rows(g)[0].source_kind,self.rows(g)[0].actual),(CardType.MINION,8))
        self.assertIsNone(self.rows(g)[0].cast_id); self.assertEqual(self.fact(g).quantity,0); self.portable(g)

    def test_effect_cast_has_own_original_spell_debit_without_extra_hand_payment(self):
        g=self.game(hand=('auto','price')); self.play(g,'auto')
        row=self.rows(g)[0]; cast=g.state.cast_history[row.cast_id-1]
        self.assertEqual((cast.origin,row.source_card_id,row.actual),('effect','all',8))
        self.assertEqual(len(g.state.play_history),1); self.assertEqual(self.fact(g).quantity,8); self.portable(g)

    def test_callback_and_normal_reactions_use_frozen_actual_result(self):
        g=self.game(hand=('result','price'),board=('reactor',)); self.play(g,'result')
        self.assertEqual((self.player(g).mana,self.armor(g)),(5,5))
        row=self.rows(g)[0]; self.assertEqual((row.mana_after,row.actual),(3,5))
        consumed=next(e.sequence for e in g.events if e.kind=='mana_consumed')
        gained=next(e.sequence for e in g.events if e.kind=='armor_gained')
        self.assertLess(consumed,gained); self.portable(g)

    def test_sequential_spends_requery_current_balance(self):
        g=self.game(hand=('two','price')); self.play(g,'two')
        self.assertEqual([(row.mana_before,row.mana_after,row.actual) for row in self.rows(g)],[(8,5,3),(5,0,5)])
        self.assertEqual(self.fact(g).quantity,8); self.portable(g)

    def test_refresh_does_not_erase_original_consumption_or_frozen_quote(self):
        g=self.game(hand=('fixed','refresh','price')); before=self.fact(g); self.play(g,'fixed'); frozen=self.fact(g)
        self.play(g,'refresh'); self.assertEqual(self.fact(g).quantity,5)
        validate_prefix(before,g.state,g.registry); validate_prefix(frozen,g.state,g.registry)
        self.assertEqual((before.quantity,frozen.quantity),(0,5)); self.portable(g)

    def test_actual_turn_reset_preserves_history_and_resets_accounts(self):
        g=self.game(hand=('fixed','price')); self.play(g,'fixed'); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual((self.player(g).mana,self.player(g).mana_spent,self.player(g).overload_locked),(10,0,0))
        self.assertEqual(self.fact(g).quantity,5); self.portable(g)

    def test_waiting_result_restores_and_resumes_from_original_actual_amount(self):
        g=self.game(hand=('wait','price'),board=('reactor',)); self.play(g,'wait'); s=self.portable(g)
        h=Game.from_snapshot(deepcopy(s),registry()); action=SelectChoice(1,g.state.pending_choice.id,('ok',))
        g.apply(action); h.apply(action)
        self.assertEqual(g.snapshot(),h.snapshot()); self.assertEqual((self.armor(g),self.player(g).mana),(5,5)); self.portable(g)

    def test_original_formula_payment_freezes_direct_prefix_through_waiting_recovery(self):
        g=self.game(hand=('fixed','affordable-price')); self.play(g,'fixed')
        self.play(g,'affordable-price')
        paid=g.state.play_history[-1]
        self.assertEqual((paid.cost,self.player(g).mana),(3,0))
        fact=paid.submitted_cost.quote.intrinsic.player_spell_mana
        self.assertEqual((fact.quantity,fact.consumption_history_length,len(fact.consumption_rows)),(5,1,1))
        snapshot=self.portable(g); h=Game.from_snapshot(deepcopy(snapshot),registry())
        action=SelectChoice(1,g.state.pending_choice.id,('ok',)); g.apply(action); h.apply(action)
        self.assertEqual(g.snapshot(),h.snapshot()); self.assertEqual(self.fact(g).quantity,5); self.portable(g)

    def test_action_and_later_choice_failure_keep_original_transaction_boundary(self):
        g=self.game(hand=('fault',)); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'fault')
        self.assertEqual(g.snapshot(),before)
        h=self.game(hand=('wait',)); self.play(h,'wait'); before=h.snapshot()
        with self.assertRaises(ResolutionError): h.apply(SelectChoice(1,h.state.pending_choice.id,('fault',)))
        self.assertEqual(h.snapshot(),before); self.portable(h)

    def test_unknown_physical_source_and_callback_reject_before_debit(self):
        for name in ('bad-source','bad-callback'):
            with self.subTest(name=name):
                g=self.game(hand=(name,)); before=g.snapshot()
                with self.assertRaises(ResolutionError): self.play(g,name)
                self.assertEqual(g.snapshot(),before)

    def test_strict_requested_amount_and_result_projection(self):
        for amount in (True,-1,2.5,'5'):
            with self.subTest(amount=amount),self.assertRaises(ValueError): SpendMana(1,amount)
        with self.assertRaises(ValueError): SpendMana(1,on_result='result')
        g=self.game(); self.play(g,'fixed'); row=self.rows(g)[0]
        for change in ({'actual':6},{'temporary_after':1},{'spent_after':4},{'mana_after':2},{'player_id':True},{'cast_id':0}):
            with self.subTest(change=change),self.assertRaises(ValueError): replace(row,**change)

    def test_query_is_pure_and_uses_complete_payment_and_consumption_prefixes(self):
        g=self.game(hand=('all','price')); self.play(g,'all'); before=g.snapshot(); fact=self.fact(g)
        self.assertEqual((fact.play_history_length,len(fact.rows),fact.consumption_history_length,len(fact.consumption_rows)),(1,1,1,1))
        self.assertEqual(fact.quantity,8); self.assertEqual(g.snapshot(),before)
        with self.assertRaises(ValueError): replace(fact,consumption_rows=())
        with self.assertRaises(ValueError): replace(fact,quantity=2,after=18)

    def test_history_rejects_changed_cast_source_future_record_and_missing_events(self):
        g=self.game(); self.play(g,'fixed'); state=g.state; row=self.rows(g)[0]
        for changed in (replace(row,source_card_id='all'),replace(row,cast_id=9999),replace(row,id=2)):
            bad=deepcopy(state); bad.mana_consumption_history[0]=changed
            with self.subTest(changed=changed),self.assertRaises(ValueError): validate_mana_consumption_history(bad,g.registry)
        events=[e for e in g.events if e.kind!='mana_consumed']
        with self.assertRaises(ValueError): validate_mana_consumption_events(g.state,events)

    def test_rehashed_snapshot_rejects_changed_delta_removed_fact_and_missing_field(self):
        g=self.game(); self.play(g,'fixed'); original=self.portable(g)
        for mode in ('delta','missing','event'):
            bad=deepcopy(original)
            if mode=='delta': bad['state']['mana_consumption_history'][0]['actual']=6
            elif mode=='missing': del bad['state']['mana_consumption_history']
            else:
                row=next(e for e in bad['events'] if e['kind']=='mana_consumption_resolved'); row['amount']=6
            bad['events_hash']=canonical_hash(bad['events'])
            bad['state_hash']=canonical_hash({k:v for k,v in bad.items() if k not in ('schema_version','events','events_hash','state_hash')})
            with self.subTest(mode=mode),self.assertRaises(SnapshotError): Game.from_snapshot(bad,registry())
        bad=deepcopy(original); bad['schema_version']=242
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad,registry())

    def test_player_view_exposes_current_mana_and_public_delta_without_original_facts(self):
        g=self.game(); self.play(g,'fixed'); before=g.snapshot()
        for p in (1,2):
            view=g.for_player(p).observe()['observation']; events=g.player_events(p)
            self.assertEqual(view['version'],'player-view-v85'); self.assertEqual(view['players'][0]['mana'],3)
            self.assertEqual([e['amount'] for e in events if e['kind']=='mana_consumed'],[5])
            text=json.dumps({'view':view,'events':events})
            self.assertNotIn('mana_consumption_history',text); self.assertNotIn('mana_consumption_resolved',text)
            self.assertNotIn('"result"',text); self.assertNotIn('consumption_rows',text)
        self.assertEqual(g.snapshot(),before); self.portable(g)

    def test_real_target_validation_and_zero_mana_do_not_invent_card_cost(self):
        g=self.game(hand=('OG_086',),mana=0,temporary=0); before=g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g,'OG_086',self.player(g,2).hero_id)
        self.assertEqual(g.snapshot(),before)
        target=self.player(g,2).board[0]; self.play(g,'OG_086',target)
        self.assertEqual((self.rows(g)[0].actual,g.state.entities[target].health,g.state.play_history[-1].cost),(0,30,0)); self.portable(g)

if __name__=='__main__': unittest.main()
