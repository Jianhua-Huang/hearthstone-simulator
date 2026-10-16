"""Original current-condition prices, accepted casts and full quotation boundaries."""
from copy import deepcopy
from dataclasses import asdict,replace
import unittest
from hs_sim.cards import build_registry
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,CostSpec,EndTurn,
    Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.cost_presence import capture,from_dict,validate_match
from hs_sim.engine.costs import capture_cost_input,capture_quote_fact,capture_generated_quote_fact,quote_cost
from hs_sim.engine.dormancy import AwakenMinion
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Draw,ModifyCost,RequestChoice,Silence)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.intrinsic_costs import validate_intrinsic_origin,validate_intrinsic_history_prefix
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import CastWhenDrawnSpec,IntrinsicCostSpec,SpellSchool
from hs_sim.engine.model import TribeChangeSpec
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference,MoveCard


def registry(wait=False):
    r=build_registry()
    for cid,tribes in (('dragon',('dragon',)),('all',('all',)),('small',()),('unknown',None)):
        r.register_card(CardDefinition('k09.'+cid,cid,CardType.MINION,cost=1,attack=1,health=4,
            metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=tribes)))
    r.register_card(CardDefinition('k09.dormant','Dormant',CardType.MINION,attack=2,health=4,dormant_turns=2,
        metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())))
    r.register_behavior('k09.noop',lambda c:())
    r.register_card(CardDefinition('k09.location','Location',CardType.LOCATION,durability=2,on_use='k09.noop',
        metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())))
    def held(c,cid):return next(c.state.entities[e] for e in c.state.players[c.player_id].hand if c.state.entities[e].card_id==cid)
    scripts={
      'holy':lambda c:(), 'shadow':lambda c:(), 'arcane':lambda c:(),
      'generate':lambda c:(AddToHand(c.player_id,'k09.dragon'),),
      'move_dragon':lambda c:(MoveCard(CardReference.capture(held(c,'k09.dragon')),c.player_id,Zone.DECK),),
      'awaken':lambda c:(AwakenMinion(next(e for e in c.state.players[c.player_id].board if c.state.entities[e].card_id=='k09.dormant'),c.source_id),),
      'auto':lambda c:(CastSpell(c.player_id,'k09.holy',c.source_id),CastSpell(c.player_id,'k09.shadow',c.source_id)),
      'enemy_auto':lambda c:(CastSpell(3-c.player_id,'k09.holy',c.source_id),CastSpell(3-c.player_id,'k09.shadow',c.source_id)),
      'draw':lambda c:(Draw(c.player_id,source_id=c.source_id),),
      'layers':lambda c:(ModifyCost(held(c,'END_033').id,CostSpec(delta=-1),c.source_id),),
      'add_dragon':lambda c:(ChangeMinionTribes(CardReference.capture(held(c,'k09.small')),TribeChangeSpec('add',('dragon',)),c.source_id),),
      'remove_dragon':lambda c:(ChangeMinionTribes(CardReference.capture(held(c,'k09.dragon')),TribeChangeSpec('remove',('dragon',)),c.source_id),),
    }
    schools={'holy':SpellSchool.HOLY,'shadow':SpellSchool.SHADOW,'arcane':SpellSchool.ARCANE}
    for name,fn in scripts.items():
        r.register_behavior('k09.'+name,fn)
        r.register_card(CardDefinition('k09.'+name,name,CardType.SPELL,on_play='k09.'+name,
            spell_school=schools.get(name),metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())))
    for name,school in (('draw_holy',SpellSchool.HOLY),('draw_shadow',SpellSchool.SHADOW)):
        r.register_card(CardDefinition('k09.'+name,name,CardType.SPELL,spell_school=school,
            keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec(),on_play='k09.holy',
            metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())))
    r.register_behavior('k09.counter',lambda c:(CounterSpell(dict(c.event.data)['window_id']),)
        if c.event.player_id==1 and c.state.entities[c.event.source_id].card_id=='k09.holy' else ())
    r.register_card(CardDefinition('k09.counter','Counter',CardType.MINION,health=5,
        triggers=(TriggerSpec('card_committed','k09.counter'),),metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())))
    if wait:
        def watch(c):
            source=c.state.entities[c.event.source_id]
            if source.card_id not in ('END_033','TIME_022','TLC_819'):return ()
            return (RequestChoice(c.player_id,(ChoiceOption('keep','Continue'),
                ChoiceOption('move','Move dragon',(MoveCard(CardReference.capture(held(c,'k09.dragon')),1,Zone.DECK),))),c.source_id),)
        r.register_behavior('k09.wait',watch)
        r.register_card(CardDefinition('k09.wait','Paid root observer',CardType.MINION,health=6,
            triggers=(TriggerSpec('card_committed','k09.wait'),),metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())))
    return r


class CostPresenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),deck=('k09.small',)*4,enemy_hand=(),wait=False,mana=30):
        return Game.from_scenario(Scenario((PlayerSetup('test.hero',hand=hand,board=board,deck=deck,
            mana=mana,max_mana=mana,mana_cap=30),PlayerSetup('test.hero',hand=enemy_hand,board=enemy)),seed=91),registry(True) if wait else self.r)
    def eid(self,g,cid,p=1):return next(e for e in g.state.players[p].hand if g.state.entities[e].card_id==cid)
    def price(self,g,cid,p=1):return quote_cost(g.state,g.registry,g.state.entities[self.eid(g,cid,p)]).amount
    def fact(self,g,cid):return capture_quote_fact(g.state,g.registry,capture_cost_input(g.state.entities[self.eid(g,cid)]))
    def play(self,g,cid,p=1):
        e=self.eid(g,cid,p);g.apply(PlayCard(p,e));return e
    def portable(self,g,wait=False):
        saved=g.snapshot();other=Game.from_snapshot(saved,registry(wait))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(wait)).snapshot(),saved);return other
    def reject(self,saved,wait=False):
        saved['events_hash']=canonical_hash(saved['events'])
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry(wait))

    def test_other_dragon_excludes_only_the_same_physical_subject(self):
        g=self.game(('END_033',));self.assertEqual(self.price(g,'END_033'),7)
        g=self.game(('END_033','END_033'))
        self.assertEqual([quote_cost(g.state,g.registry,g.state.entities[e]).amount for e in g.state.players[1].hand],[4,4])
        self.play(g,'END_033');self.assertEqual(self.price(g,'END_033'),7);self.portable(g)

    def test_generated_preview_does_not_insert_or_exclude_a_real_hand_dragon(self):
        g=self.game(('END_033',));saved=g.snapshot()
        self.assertEqual(capture_generated_quote_fact(g.state,g.registry,1,'END_033').amount,4)
        self.assertEqual(self.price(g,'END_033'),7);self.assertEqual(g.snapshot(),saved)

    def test_other_dragon_uses_own_hand_not_deck_board_or_opponent(self):
        g=self.game(('END_033',),board=('k09.dragon',),deck=('k09.dragon',),enemy_hand=('k09.dragon',))
        self.assertEqual(self.price(g,'END_033'),7)
        g=self.game(('END_033','k09.all'));self.assertEqual(self.price(g,'END_033'),4)

    def test_real_generation_and_move_requote_without_cached_discount(self):
        g=self.game(('END_033','k09.generate','k09.move_dragon'))
        self.play(g,'k09.generate');self.assertEqual(self.price(g,'END_033'),4)
        self.play(g,'k09.move_dragon');self.assertEqual(self.price(g,'END_033'),7);self.portable(g)

    def test_unknown_later_hand_tribes_cannot_hide_behind_a_true_row(self):
        g=self.game(('END_033','k09.dragon','k09.unknown'))
        with self.assertRaises(UnsupportedDefinitionError):self.price(g,'END_033')

    def test_dormant_presence_checks_both_boards_and_actual_dormancy(self):
        for own,enemy in ((('k09.dormant',),()),((),('k09.dormant',))):
            g=self.game(('TIME_022',),board=own,enemy=enemy)
            self.assertEqual(self.price(g,'TIME_022'),4);self.play(g,'TIME_022')
            self.assertEqual(g.state.play_history[-1].cost,4);self.portable(g)
        g=self.game(('TIME_022',),board=('k09.location',))
        self.assertEqual(self.price(g,'TIME_022'),8)

    def test_actual_awakening_requotes_without_mutating_old_fact(self):
        g=self.game(('TIME_022','k09.awaken'),board=('k09.dormant',));old=self.fact(g,'TIME_022')
        self.play(g,'k09.awaken');self.assertEqual(self.price(g,'TIME_022'),8)
        self.assertEqual(old.amount,4);validate_intrinsic_history_prefix(old.intrinsic,g.state,g.registry)

    def test_holy_and_shadow_both_required_with_current_global_turn(self):
        g=self.game(('TLC_819','k09.holy','k09.shadow','k09.arcane'))
        self.play(g,'k09.holy');self.assertEqual(self.price(g,'TLC_819'),6)
        self.play(g,'k09.arcane');self.assertEqual(self.price(g,'TLC_819'),6)
        self.play(g,'k09.shadow');self.assertEqual(self.price(g,'TLC_819'),1)
        g.apply(EndTurn(1));self.assertEqual(self.price(g,'TLC_819'),6);self.portable(g)

    def test_automatic_casts_count_for_the_actual_caster_but_not_its_opponent(self):
        g=self.game(('TLC_819','k09.auto'));self.play(g,'k09.auto')
        self.assertEqual(self.price(g,'TLC_819'),1);self.assertEqual([r.origin for r in g.state.cast_history],['hand','effect','effect'])
        self.play(g,'TLC_819');self.assertEqual(g.state.play_history[-1].cost,1);self.portable(g)
        g=self.game(('TLC_819','k09.enemy_auto'));self.play(g,'k09.enemy_auto')
        self.assertEqual(self.price(g,'TLC_819'),6)

    def test_draw_cast_origins_share_original_turn_and_school_facts(self):
        g=self.game(('TLC_819','k09.draw'),deck=('k09.draw_holy','k09.draw_shadow','k09.small'))
        self.play(g,'k09.draw');self.assertEqual(self.price(g,'TLC_819'),1)
        self.assertEqual([r.origin for r in g.state.cast_history],['hand','draw','draw']);self.portable(g)

    def test_countered_holy_attempt_is_not_an_accepted_payload(self):
        g=self.game(('TLC_819','k09.holy','k09.shadow'),enemy=('k09.counter',))
        self.play(g,'k09.holy');self.play(g,'k09.shadow')
        self.assertEqual(self.price(g,'TLC_819'),6)
        self.assertEqual(g.state.cast_history[0].failure,'countered');self.portable(g)

    def test_captured_match_roundtrips_typed_and_json_and_reads_are_pure(self):
        g=self.game(('END_033','k09.dragon','TIME_022','TLC_819','k09.auto'),board=('k09.dormant',))
        self.play(g,'k09.auto');saved=g.snapshot()
        from hs_sim.engine.continuations import FrameCodec
        codec=FrameCodec(g.mechanics,g.registry)
        import json
        for cid in ('END_033','TIME_022','TLC_819'):
            fact=self.fact(g,cid);match=fact.intrinsic.condition_facts[0]
            self.assertEqual(from_dict(json.loads(json.dumps(asdict(match)))),match)
            self.assertEqual(codec.decode(codec.encode(match)),match)
            validate_intrinsic_origin(fact.intrinsic,g.state,g.registry)
        self.assertEqual(g.snapshot(),saved)

    def test_local_layer_follows_current_presence_and_actual_payment(self):
        g=self.game(('END_033','k09.dragon','k09.layers'));self.play(g,'k09.layers')
        self.assertEqual(self.price(g,'END_033'),3);self.play(g,'END_033')
        self.assertEqual(g.state.play_history[-1].cost,3);self.portable(g)

    def test_paid_wait_keeps_original_price_after_dragon_leaves_hand(self):
        g=self.game(('END_033','k09.dragon'),board=('k09.wait',),wait=True)
        self.play(g,'END_033');self.assertIsNotNone(g.state.pending_choice);other=self.portable(g,True)
        for x in (g,other):
            q=x.state.pending_choice;x.apply(SelectChoice(1,q.id,('move',)))
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.play_history[-1].cost,4)
        self.assertEqual(g.state.players[1].mana,26);self.portable(g,True)

    def test_failed_quote_and_insufficient_mana_preserve_entire_state(self):
        g=self.game(('END_033',),mana=5);saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'END_033')
        self.assertEqual(g.snapshot(),saved)

    def test_physical_and_hypothetical_quotes_cannot_borrow_another_subject(self):
        g=self.game(('END_033','k09.dragon'));fact=self.fact(g,'END_033');match=fact.intrinsic.condition_facts[0]
        changed=replace(match,source_id=self.eid(g,'k09.dragon'))
        stage=replace(fact.intrinsic,condition_facts=(changed,))
        with self.assertRaises(ValueError):replace(fact,intrinsic=stage)
        generated=capture_generated_quote_fact(g.state,g.registry,1,'END_033')
        with self.assertRaises(ValueError):replace(generated,intrinsic=fact.intrinsic)

    def test_original_window_rejects_omitted_rows_even_when_price_is_same(self):
        g=self.game(('END_033','k09.dragon','k09.small'));fact=self.fact(g,'END_033');match=fact.intrinsic.condition_facts[0]
        changed=replace(match,hand=match.hand[:-1]);validate_match(changed,g.registry)
        with self.assertRaises(ValueError):validate_intrinsic_origin(replace(fact.intrinsic,condition_facts=(changed,)),g.state,g.registry)

    def test_rehashed_paid_record_cannot_remove_presence_operands(self):
        g=self.game(('END_033','k09.dragon'));self.play(g,'END_033');saved=g.snapshot()
        stage=saved['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']
        stage['condition_facts'][0]['hand'].pop();self.reject(saved)

    def test_player_projection_hides_original_operands_and_opponent_hand_identity(self):
        g=self.game(('END_033','k09.dragon','TLC_819'));self.play(g,'END_033')
        import json
        for p in (1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for field in ('condition_facts','cast_rows','next_attachment_id','tribe_changes','CostPresenceMatch'):
                self.assertNotIn('"'+field+'"',public)
        hand=g.for_player(2).observe()['observation']['players'][0]['hand']
        self.assertTrue(all(x['card_id'] is None for x in hand))

    def test_finite_declarations_reject_wrong_profiles_and_foreign_formula_shapes(self):
        for kwargs in (dict(condition='hand_other_dragon',delta=-3),
            dict(condition='board_dormant_minion',set_to=4,history_profile_id='board.current-dormant-minion-v1'),
            dict(condition='turn_holy_and_shadow',delta=-5,history_profile_id='cast.current-turn-holy-shadow-v1')):
            with self.assertRaises(ValueError):IntrinsicCostSpec(**kwargs)

    def test_current_tribe_addition_and_removal_requote_and_freeze_original_material(self):
        g=self.game(('END_033','k09.small','k09.add_dragon'))
        self.assertEqual(self.price(g,'END_033'),7);self.play(g,'k09.add_dragon')
        self.assertEqual(self.price(g,'END_033'),4);self.play(g,'END_033');self.portable(g)
        g=self.game(('END_033','k09.dragon','k09.remove_dragon'))
        old=self.fact(g,'END_033');self.play(g,'k09.remove_dragon')
        self.assertEqual(self.price(g,'END_033'),7)
        validate_intrinsic_history_prefix(old.intrinsic,g.state,g.registry);self.portable(g)


if __name__=='__main__':unittest.main()
