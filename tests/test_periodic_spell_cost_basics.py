"""Periodic spell pricing freezes the physical cast prefix; explicit local policy."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest
from hs_sim.engine import (CardDefinition,CardType,CastWhenDrawnSpec,CostAuraSpec,CostSpec,
    CounterPolicySpec,EndTurn,Game,GrantCounterPolicy,Keyword,MinionReference,PlayCard,
    PlayerSetup,Registry,ResolutionError,Scenario,SelectChoice,SnapshotError,SpellRepeatSpec,
    SpellSchool,TargetSpec,Zone)
from hs_sim.engine.costs import (capture_cost_input,capture_generated_quote_fact,quote_input,
    validate_first_play_cost_prefix)
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,Destroy,Draw,InvokeBehavior,
    RequestChoice,ReturnToHand,Silence,Summon)
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.spell_history import RecastSpell
from hs_sim.engine.intrinsic_costs import validate_generated_quote_fact
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

ROOT=Path(__file__).resolve().parents[1]; KAEL='BT_255'
PIN='de316a2df04b7f78ed2700384b806e670d76aecb0627e55adce4e35994ab8deb'
AURA=CostAuraSpec(CostSpec(set_to=1,card_types=(CardType.SPELL,)),every_nth_per_turn=3)
def evidence():
    p=json.loads((ROOT/'data/support/periodic-spell-cost-basics.json').read_bytes())
    if canonical_digest(p)!=PIN: raise ValueError('Periodic spell raw changed')
    return p
def registry():
    r=Registry('isolated-periodic-physical-spell-cost-v1'); raw=evidence()['records'][0]
    r.register_card(CardDefinition('hero','Diagnostic hero',CardType.HERO,health=80,metadata=metadata()))
    r.register_card(CardDefinition(KAEL,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],
        health=raw['health'],cost_auras=(AURA,),metadata=metadata_from_record(raw)))
    r.register_card(CardDefinition('plain','Diagnostic spell',CardType.SPELL,cost=2,spell_school=SpellSchool.FIRE,metadata=metadata()))
    r.register_card(CardDefinition('body','Diagnostic minion',CardType.MINION,health=5,metadata=metadata()))
    def fault(c): raise ResolutionError('Diagnostic periodic spell failure')
    r.register_behavior('explode',fault)
    def waiting(c): return (RequestChoice(c.player_id,(
        ChoiceOption('ok','Continue',()),ChoiceOption('fault','Fail',(InvokeBehavior('explode',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior('waiting',waiting)
    r.register_card(CardDefinition('waiting','Diagnostic waiting spell',CardType.SPELL,cost=2,on_play='waiting',metadata=metadata()))
    r.register_card(CardDefinition('failing','Diagnostic failing spell',CardType.SPELL,cost=2,on_play='explode',metadata=metadata()))
    r.register_behavior('cast',lambda c:(CastSpell(c.player_id,'plain',c.source_id),))
    r.register_behavior('history',lambda c:(RecastSpell(c.player_id,1,c.source_id),))
    r.register_behavior('draw',lambda c:(Draw(c.player_id),))
    r.register_behavior('no-target',lambda c:(CastSpell(c.player_id,'targeted',c.source_id),))
    for name,script in (('effect-source','cast'),('history-source','history'),('draw-source','draw'),('no-target-source','no-target')):
        r.register_card(CardDefinition(name,'Diagnostic '+name,CardType.MINION,health=5,battlecry=script,metadata=metadata()))
    r.register_card(CardDefinition('drawn','Diagnostic draw spell',CardType.SPELL,cost=2,
        keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec(replacement=False),metadata=metadata()))
    r.register_card(CardDefinition('targeted','Diagnostic no-target spell',CardType.SPELL,cost=2,
        targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy'),metadata=metadata()))
    r.register_card(CardDefinition('repeat-source','Diagnostic existing repeat carrier',CardType.MINION,health=5,
        spell_repeats=(SpellRepeatSpec(2,class_mode='any'),),metadata=metadata()))
    scripts={'silence':lambda c:(Silence(c.target_id),), 'destroy':lambda c:(Destroy(c.target_id,c.source_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),), 'control':lambda c:(ChangeControl(c.target_id,2),),
        'counter':lambda c:(GrantCounterPolicy(MinionReference.capture(c.state.entities[c.target_id]),CounterPolicySpec(CardType.SPELL),c.source_id),)}
    for name,script in scripts.items():
        r.register_behavior(name,script)
        r.register_card(CardDefinition(name,'Diagnostic '+name,CardType.MINION,health=5,battlecry=name,
            requires_target=True,metadata=metadata()))
    return r

class PeriodicSpellCostTests(unittest.TestCase):
    def game(self,hand=('plain',)*6,board=(KAEL,),enemy_board=(),deck=('body',)*4):
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,board=board,deck=deck,max_mana=10,mana=20,temporary_mana=10),
            PlayerSetup('hero',hand=('plain',)*4,board=enemy_board,deck=('body',)*4,max_mana=10,mana=20,temporary_mana=10)),seed=136),registry())
    def card(self,g,name='plain',p=1): return next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==name)
    def play(self,g,name='plain',target=None): return g.apply(PlayCard(g.state.active_player,self.card(g,name,g.state.active_player),target))
    def cost(self,g,p=1):
        return quote_input(g.state,g.registry,capture_cost_input(g.state.entities[self.card(g,p=p)])).amount
    def fact(self,g): return quote_input(g.state,g.registry,capture_cost_input(g.state.entities[self.card(g)]))
    def portable(self,g):
        s=g.snapshot(); self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),registry()).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s); self.assertEqual(replay(build_replay(g),registry()).snapshot(),s); return s
    def two(self,g): self.play(g); self.play(g)

    def test_real_third_cost_is_one_and_scope_is_explicitly_uncalibrated(self):
        p=evidence(); self.assertFalse(p['CN_calibrated']); self.assertEqual(p['new_combinations'],0)
        self.assertEqual((registry().card(KAEL).cost,registry().card(KAEL).attack,registry().card(KAEL).health),(6,4,7))
        self.assertEqual(AURA.cost.set_to,1)

    def test_declaration_keeps_single_type_and_rejects_mixed_conditions(self):
        for kw in ({'first_per_turn':True},{'tribes_any':('dragon',)},{'relation':'any'},
                   {'cost':CostSpec(set_to=1,card_types=(CardType.SPELL,CardType.MINION))}):
            with self.subTest(kw=kw),self.assertRaises(ValueError): replace(AURA,**kw)

    def test_third_and_sixth_manual_spells_use_the_same_original_ordinal(self):
        g=self.game(); prices=[]
        for _ in range(6): prices.append(self.cost(g)); self.play(g)
        self.assertEqual(prices,[2,2,1,2,2,1]); self.assertEqual(g.state.players[1].mana,10)
        self.assertEqual([p.submitted_cost.quote.contributions[0].first_play.ordinal
            for p in g.state.play_history if p.submitted_cost.quote.contributions],[3,6]); self.portable(g)

    def test_generated_and_physical_prices_share_full_cast_prefix_and_are_pure(self):
        g=self.game(); self.two(g); before=g.snapshot(); physical=self.fact(g)
        generated=capture_generated_quote_fact(g.state,g.registry,1,'plain'); validate_generated_quote_fact(g.registry,generated)
        self.assertEqual((physical.amount,generated.amount),(1,1))
        self.assertEqual(physical.contributions[0].first_play.cast_history_length,2)
        self.assertEqual(g.snapshot(),before)

    def test_source_entering_after_spells_does_not_reset_player_ordinal(self):
        g=self.game(hand=('plain','plain',KAEL,'plain'),board=()); self.two(g); self.play(g,KAEL)
        self.assertEqual(self.cost(g),1); self.play(g); self.portable(g)

    def test_effect_casts_count_even_without_paid_hand_spell_roots(self):
        g=self.game(hand=('effect-source','effect-source','plain'))
        self.play(g,'effect-source'); self.play(g,'effect-source')
        self.assertEqual([c.origin for c in g.state.cast_history],['effect','effect'])
        self.assertEqual(self.cost(g),1); self.play(g); self.portable(g)

    def test_drawn_cast_and_hand_cast_share_player_turn_sequence(self):
        g=self.game(hand=('draw-source','plain','plain'),deck=('drawn','body'))
        self.play(g,'draw-source'); self.play(g)
        self.assertEqual(g.state.cast_history[0].origin,'draw'); self.assertEqual(self.cost(g),1)
        self.play(g); self.portable(g)

    def test_history_cast_is_a_new_physical_count_not_another_hand_root(self):
        g=self.game(hand=('plain','history-source','plain')); self.play(g); self.play(g,'history-source')
        self.assertEqual(g.state.cast_history[-1].origin,'history'); self.assertEqual(self.cost(g),1)
        self.play(g); self.portable(g)

    def test_existing_repeated_payloads_are_individual_cast_operands(self):
        g=self.game(hand=('plain','plain'),board=(KAEL,'repeat-source')); self.play(g)
        self.assertEqual([c.origin for c in g.state.cast_history],['hand','repeat']); self.assertEqual(self.cost(g),1)
        self.play(g); self.portable(g)

    def test_no_target_automatic_attempt_does_not_count_under_local_policy(self):
        g=self.game(hand=('no-target-source','plain','plain','plain')); self.play(g,'no-target-source')
        self.assertFalse(g.state.cast_history[0].payload_started); self.two(g)
        self.assertEqual(self.cost(g),1); self.play(g); self.portable(g)

    def test_countered_attempt_does_not_count_under_local_policy(self):
        g=self.game(hand=('counter','plain','plain','plain','plain'),enemy_board=('body',))
        self.play(g,'counter',g.state.players[2].board[0]); self.play(g)
        self.assertEqual(g.state.cast_history[0].failure,'countered'); self.two(g)
        self.assertEqual(self.cost(g),1); self.play(g); self.portable(g)

    def test_unrelated_minion_play_does_not_spend_spell_ordinal(self):
        g=self.game(hand=('plain','body','plain','plain')); self.play(g); self.play(g,'body'); self.play(g)
        self.assertEqual(self.cost(g),1); self.play(g); self.portable(g)

    def test_each_actual_turn_and_player_reads_its_own_cast_prefix(self):
        g=self.game(); self.two(g); self.assertEqual(self.cost(g),1); self.assertEqual(self.cost(g,2),2)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.assertEqual(self.cost(g),2); self.portable(g)

    def test_multiple_same_sources_do_not_have_independent_free_use_budgets(self):
        g=self.game(board=(KAEL,KAEL)); self.two(g); f=self.fact(g)
        self.assertEqual(f.amount,1); self.assertEqual(len(f.contributions),2)
        self.play(g); self.assertEqual(self.cost(g),2); self.portable(g)

    def test_source_silence_death_and_return_remove_live_discount_only(self):
        for script in ('silence','destroy','bounce'):
            with self.subTest(script=script):
                g=self.game(hand=('plain','plain',script,'plain')); self.two(g)
                self.play(g,script,g.state.players[1].board[0]); self.assertEqual(self.cost(g),2); self.portable(g)

    def test_source_control_uses_new_payers_sequence_without_moving_old_counts(self):
        g=self.game(hand=('plain','plain','control','plain')); self.two(g)
        self.play(g,'control',g.state.players[1].board[0]); self.assertEqual(self.cost(g),2)
        g.apply(EndTurn(1)); self.two(g); self.assertEqual(self.cost(g,2),1); self.portable(g)

    def test_waiting_payment_stays_frozen_after_new_quotes_restore_and_resume(self):
        g=self.game(hand=('plain','plain','waiting','plain')); self.two(g); self.play(g,'waiting')
        self.assertEqual(g.state.play_history[-1].submitted_cost.quote.amount,1); s=self.portable(g)
        h=Game.from_snapshot(deepcopy(s),registry()); choice=g.state.pending_choice.id
        g.apply(SelectChoice(1,choice,('ok',))); h.apply(SelectChoice(1,choice,('ok',)))
        self.assertEqual(g.snapshot(),h.snapshot()); self.assertEqual(self.cost(g),2); self.portable(g)

    def test_failed_new_action_and_failed_choice_preserve_count_and_payment(self):
        g=self.game(hand=('plain','plain','failing','waiting')); self.two(g); s=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'failing')
        self.assertEqual(g.snapshot(),s); self.play(g,'waiting'); s=g.snapshot()
        with self.assertRaises(ResolutionError): g.apply(SelectChoice(1,g.state.pending_choice.id,('fault',)))
        self.assertEqual(g.snapshot(),s); self.portable(g)

    def test_cropped_or_changed_original_cast_prefix_is_rejected(self):
        g=self.game(); self.two(g); fact=self.fact(g).contributions[0].first_play
        with self.assertRaises(ValueError): replace(fact,cast_rows=fact.cast_rows[:-1])
        wrong=replace(fact.cast_rows[0],card_id='drawn',spell_school=None)
        with self.assertRaises(ValueError): validate_first_play_cost_prefix(g.state,g.registry,replace(fact,cast_rows=(wrong,*fact.cast_rows[1:])))
        self.play(g); s=self.portable(g)
        bad=deepcopy(s); del bad['state']['play_history'][-1]['submitted_cost']['quote']['contributions'][0]['first_play']['cast_rows']
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad,registry())
        bad=deepcopy(s); bad['schema_version']=238
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad,registry())

    def test_player_views_expose_price_without_full_private_cast_operands(self):
        g=self.game(); self.two(g); before=g.snapshot()
        for p in (1,2):
            text=json.dumps(g.for_player(p).observe())
            for key in ('cast_rows','cast_history_length','submitted_cost','first_play'): self.assertNotIn(key,text)
        self.assertEqual(g.snapshot(),before)

if __name__=='__main__': unittest.main()
