"""Explicit Rewind face chains and necessary real-source combinations (R-092)."""
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (CardDefinition, CardMetadata, CardClass, CardType, CastSpell,
    CostSpec, Game, Keyword, PlayCard, PlayerSetup, RewindSpec, Scenario, SelectChoice,
    SnapshotError, SpellRepeatSpec, TriggerSpec, Zone, RecastSpell, ResurrectMinion)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, Buff, ChangeControl,
    ChoiceOption, CopyMinion, Damage, Destroy, GainArmor, GrantDeathrattle, RequestChoice,
    ReturnToHand, ShuffleIntoDeck, Silence, Summon, Transform, ModifyCost)
from hs_sim.engine.hand_keywords import GrantStoredKeyword
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import PaymentType, Rarity
from hs_sim.engine.pools import GenerationContext
from hs_sim.engine.registry import Registry
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard


class RewindFormTests(unittest.TestCase):
    def setUp(self):
        self.r=build_registry()
        self.r.register_card(CardDefinition('body','body',CardType.MINION,attack=2,health=5))
    def forms(self, count=3, fn=None, **kw):
        fn=fn or (lambda c:[GainArmor(1,c.rewind_attempt+1)])
        self.r.register_behavior('effect',fn)
        kind=kw.pop('kind',CardType.MINION)
        if kind==CardType.MINION:kw.setdefault('attack',3);kw.setdefault('health',4)
        extra=kw.pop('keywords',())
        for n in range(count,-1,-1):
            self.r.register_card(CardDefinition(f'f{n}',f'form {n}',kind,cost=4,on_play='effect',
                keywords=extra+((Keyword.REWIND,) if n else ()),
                rewind=RewindSpec(n,f'f{n-1}') if n else None,**kw))
    def script(self,name,fn):
        self.r.register_behavior(name,fn);self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name))
    def game(self,hand=('f3',),*,board=(),enemy=(),hero='HERO_01',mana=10,context=GenerationContext('local-2026-09-23','experimental')):
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,max_mana=mana,mana=mana),
            PlayerSetup('HERO_08',board=enemy)),seed=123,generation_context=context),self.r)
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def find(self,g,cid,zone='hand',p=1):return next(i for i in getattr(g.state.players[p],zone) if g.state.entities[i].card_id==cid)
    def play(self,g,cid='f3',target=None):
        source=self.find(g,cid);g.apply(PlayCard(1,source,target));return source
    def choose(self,g,option='retry'):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(option,)))
    def check(self,g):
        snapshot=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snapshot,self.r).snapshot(),snapshot)
        self.assertEqual(g.clone().snapshot(),snapshot)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),snapshot)
    def ref(self,c,cid='f3'):
        return CardReference.capture(next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id==cid))
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as raised:Game.from_snapshot(s,self.r)
        self.assertNotIn('digest mismatch',str(raised.exception))

    def test_chain_changes_same_entity_on_each_retry(self):
        self.forms();g=self.game();source=self.play(g)
        for n in (2,1,0):
            self.choose(g);self.assertEqual(g.state.entities[source].card_id,f'f{n}');self.check(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.state.players[1].board,[source])
        self.assertNotIn(Keyword.REWIND,g.state.entities[source].keywords)
        self.assertEqual((self.hero(g).armor,g.state.players[1].mana),(4,6))

    def test_keep_leaves_original_face(self):
        self.forms();g=self.game();source=self.play(g);self.choose(g,'keep')
        self.assertEqual(g.state.entities[source].card_id,'f3');self.check(g)

    def test_keep_after_retry_preserves_used_face(self):
        self.forms();g=self.game();source=self.play(g);self.choose(g);self.choose(g,'keep')
        self.assertEqual(g.state.entities[source].card_id,'f2');self.check(g)

    def test_one_retry_chain_has_no_extra_terminal_offer(self):
        self.forms(count=1);g=self.game(('f1',));source=self.play(g,'f1');self.choose(g)
        self.assertEqual(g.state.entities[source].card_id,'f0');self.assertIsNone(g.state.pending_choice);self.check(g)

    def test_intermediate_face_has_its_own_remaining_budget(self):
        self.forms();g=self.game(('f2',));source=self.play(g,'f2');self.choose(g);self.choose(g)
        self.assertEqual(g.state.entities[source].card_id,'f0');self.assertEqual(len(g.history),3);self.check(g)

    def test_terminal_face_plays_without_rewind(self):
        self.forms();g=self.game(('f0',));self.play(g,'f0')
        self.assertIsNone(g.state.pending_choice);self.assertIsNone(g.snapshot()['rewind_session']);self.check(g)

    def test_play_and_cast_history_record_executed_face(self):
        self.forms(kind=CardType.SPELL);g=self.game();self.play(g);self.choose(g)
        self.assertEqual(g.state.play_history[-1].card_id,'f2')
        self.assertEqual(g.state.cast_history[-1].card_id,'f2');self.check(g)

    def test_original_specific_cost_modifier_is_consumed_once(self):
        self.forms();self.script('setup',lambda c:[AddCostModifier(1,CostSpec(delta=-4,card_ids=('f3',)),uses_remaining=1)])
        g=self.game(('setup','f3'),mana=1);self.play(g,'setup');self.play(g);self.choose(g);self.choose(g)
        self.assertEqual(g.state.players[1].mana,1);self.assertFalse(g.state.players[1].cost_modifiers)
        self.assertEqual(g.state.play_history[-1].cost,0);self.check(g)

    def test_retry_face_only_modifier_cannot_change_accepted_payment(self):
        self.forms();self.script('setup',lambda c:[AddCostModifier(1,CostSpec(delta=-3,card_ids=('f2',)))])
        g=self.game(('setup','f3'));self.play(g,'setup');self.play(g);self.choose(g)
        self.assertEqual(g.state.players[1].mana,6);self.assertEqual(g.state.play_history[-1].cost,4);self.check(g)

    def test_original_alternate_payment_stays_bound_to_play(self):
        self.forms();self.script('setup',lambda c:[AddCostModifier(1,CostSpec(payment=PaymentType.HEALTH,card_ids=('f3',)))])
        g=self.game(('setup','f3'));self.play(g,'setup');self.play(g);self.choose(g)
        self.assertEqual((g.state.players[1].mana,self.hero(g).health),(10,26));self.check(g)

    def test_local_cost_and_stat_enchantments_survive(self):
        self.forms();self.script('setup',lambda c:[BuffStoredCard(self.ref(c),2,3),ModifyCost(self.ref(c).entity_id,CostSpec(delta=-2))])
        g=self.game(('setup','f3'));self.play(g,'setup');source=self.play(g);self.choose(g)
        entity=g.state.entities[source];self.assertEqual((entity.attack,entity.health,entity.cost),(5,7,2))
        self.assertEqual(g.state.players[1].mana,8);self.check(g)

    def test_granted_keyword_survives_terminal_face(self):
        self.forms(count=1);self.script('setup',lambda c:[GrantStoredKeyword(self.ref(c,'f1'),Keyword.TAUNT)])
        g=self.game(('setup','f1'));self.play(g,'setup');source=self.play(g,'f1');self.choose(g)
        self.assertIn(Keyword.TAUNT,g.state.entities[source].keywords);self.assertNotIn(Keyword.REWIND,g.state.entities[source].keywords);self.check(g)

    def test_retry_reexecutes_final_face_behavior(self):
        self.forms(fn=lambda c:[GainArmor(1,10 if c.source.card_id=='f2' else 1)])
        g=self.game();self.play(g);self.choose(g);self.assertEqual(self.hero(g).armor,10);self.check(g)

    def test_death_history_and_resurrection_use_chosen_face(self):
        self.forms();self.script('kill',lambda c:[Destroy(c.state.players[1].board[0])])
        self.script('res',lambda c:[ResurrectMinion(1,c.state.death_history[-1].id,c.source_id)])
        g=self.game(('f3','kill','res'));self.play(g);self.choose(g);self.choose(g,'keep');self.play(g,'kill');self.play(g,'res')
        self.assertEqual(g.state.death_history[-1].card_id,'f2')
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].card_id,'f2');self.check(g)

    def test_bounce_preserves_remaining_face_and_new_play_budget(self):
        self.forms(fn=lambda c:[ReturnToHand(c.source_id)])
        g=self.game();source=self.play(g);self.choose(g);self.choose(g,'keep')
        self.assertEqual(self.find(g,'f2'),source);self.play(g,'f2');self.choose(g);self.choose(g)
        self.assertEqual(self.find(g,'f0'),source);self.assertEqual(g.state.players[1].mana,2);self.check(g)

    def test_reborn_recreates_chosen_face_without_refunding_retries(self):
        self.forms(keywords=(Keyword.REBORN,))
        self.script('kill',lambda c:[Destroy(c.state.players[1].board[0])])
        g=self.game(('f3','kill'));source=self.play(g);self.choose(g);self.choose(g,'keep');self.play(g,'kill')
        replacement=g.state.entities[g.state.players[1].board[0]]
        self.assertNotEqual(replacement.id,source)
        self.assertEqual((replacement.card_id,replacement.health),('f2',1))
        self.assertNotIn(Keyword.REBORN,replacement.keywords)
        self.assertEqual(g.state.death_history[-1].card_id,'f2');self.check(g)

    def test_silence_then_bounce_restores_only_remaining_face_budget(self):
        self.forms()
        self.script('reset',lambda c:[Silence(c.state.players[1].board[0]),ReturnToHand(c.state.players[1].board[0])])
        g=self.game(('f3','reset'));source=self.play(g);self.choose(g);self.choose(g,'keep');self.play(g,'reset')
        self.assertEqual(self.find(g,'f2'),source)
        self.assertIn(Keyword.REWIND,g.state.entities[source].keywords)
        self.play(g,'f2');self.choose(g);self.choose(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.state.entities[source].card_id,'f0');self.check(g)

    def test_shuffle_preserves_chosen_face(self):
        self.forms();self.script('shuffle',lambda c:[ShuffleIntoDeck(c.state.players[1].board[0])])
        g=self.game(('f3','shuffle'));source=self.play(g);self.choose(g);self.choose(g,'keep');self.play(g,'shuffle')
        self.assertEqual(g.state.entities[source].card_id,'f2');self.assertIn(source,g.state.players[1].deck);self.check(g)

    def test_silence_does_not_restore_original_identity(self):
        self.forms();self.script('silence',lambda c:[Silence(c.state.players[1].board[0])])
        g=self.game(('f3','silence'));source=self.play(g);self.choose(g);self.choose(g,'keep');self.play(g,'silence')
        self.assertEqual(g.state.entities[source].card_id,'f2');self.assertNotIn(Keyword.REWIND,g.state.entities[source].keywords);self.check(g)

    def test_transform_replaces_the_chain_identity(self):
        self.forms();self.script('morph',lambda c:[Transform(c.state.players[1].board[0],'body')])
        g=self.game(('f3','morph'));source=self.play(g);self.choose(g);self.choose(g,'keep');self.play(g,'morph')
        self.assertEqual(g.state.entities[source].card_id,'body');self.check(g)

    def test_control_change_preserves_final_face(self):
        self.forms();self.script('give',lambda c:[ChangeControl(c.state.players[1].board[0],2)])
        g=self.game(('f3','give'));source=self.play(g);self.choose(g);self.choose(g,'keep');self.play(g,'give')
        self.assertEqual((g.state.entities[source].card_id,g.state.entities[source].controller),('f2',2));self.check(g)

    def test_board_copy_preserves_face(self):
        self.forms();self.script('copy',lambda c:[CopyMinion(c.state.players[1].board[0],1)])
        g=self.game(('f3','copy'));self.play(g);self.choose(g);self.choose(g,'keep');self.play(g,'copy')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],['f2','f2']);self.check(g)

    def test_base_and_current_hand_copies_preserve_face(self):
        self.forms(fn=lambda c:[ReturnToHand(c.source_id)])
        self.script('copy',lambda c:[CopyCard(self.ref(c,'f2'),1,mode='base'),CopyCard(self.ref(c,'f2'),1,mode='current')])
        g=self.game(('f3','copy'));self.play(g);self.choose(g);self.choose(g,'keep');self.play(g,'copy')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],['f2']*3);self.check(g)

    def test_transform_during_attempt_does_not_cancel_remaining_chain(self):
        self.forms(fn=lambda c:[Transform(c.source_id,'body')]);g=self.game();source=self.play(g);self.choose(g)
        self.assertEqual(g.state.entities[source].card_id,'body');self.assertEqual(g.state.play_history[-1].card_id,'f2');self.check(g)

    def test_source_dying_during_retry_records_executed_face(self):
        self.forms(fn=lambda c:[Destroy(c.source_id)]);g=self.game();self.play(g);self.choose(g)
        self.assertEqual(g.state.death_history[-1].card_id,'f2');self.check(g)

    def test_pending_inner_choice_records_new_face(self):
        self.forms(fn=lambda c:[RequestChoice(1,(ChoiceOption('x','x',(GainArmor(1,1),)),),source_id=c.source_id)])
        g=self.game();self.play(g);self.choose(g,'x');self.choose(g);self.check(g)
        self.assertEqual(g.state.play_history[-1].card_id,'f2');self.choose(g,'x');self.choose(g,'keep');self.check(g)

    def test_public_face_change_preserves_handle_and_reveals_new_identity(self):
        self.forms();g=self.game();source=self.play(g);old=g.observe(2)['players'][0]['board'][0]['ref'];self.choose(g)
        new=g.observe(2)['players'][0]['board'][0];self.assertEqual((new['ref'],new['card_id']),(old,'f2'))
        events=[e for e in g.player_events(2) if e['kind']=='rewind_face_changed']
        self.assertEqual(events[-1]['source']['card_id'],'f2');self.check(g)

    def test_face_change_invalidates_original_stored_reference(self):
        self.forms();g=self.game();before=CardReference.capture(g.state.entities[self.find(g,'f3')]);source=self.play(g);self.choose(g)
        self.assertGreater(g.state.entities[source].zone_epoch,before.zone_epoch);self.check(g)

    def test_spell_repeat_uses_new_face_for_every_iteration(self):
        self.forms(kind=CardType.SPELL);self.r.register_card(CardDefinition('repeat','repeat',CardType.MINION,health=3,
            spell_repeats=(SpellRepeatSpec(class_mode='any'),)))
        g=self.game(board=('repeat',));self.play(g);self.choose(g)
        self.assertEqual([r.card_id for r in g.state.cast_history],['f2','f2']);self.check(g)

    def test_historical_recast_uses_final_form_without_rewind(self):
        self.forms(kind=CardType.SPELL);self.script('recast',lambda c:[RecastSpell(1,1,c.source_id)])
        g=self.game(('f3','recast'));self.play(g);self.choose(g);self.choose(g,'keep');self.play(g,'recast')
        self.assertEqual(g.state.cast_history[-1].card_id,'f2');self.assertIsNone(g.state.pending_choice);self.check(g)

    def test_automatic_cast_does_not_consume_a_retry_face(self):
        self.forms(kind=CardType.SPELL);self.script('cast',lambda c:[CastSpell(1,'f3',c.source_id)])
        g=self.game(('cast',));self.play(g,'cast');self.assertEqual(g.state.cast_history[-1].card_id,'f3')
        self.assertFalse(any(e.kind=='rewind_face_changed' for e in g.events));self.check(g)

    def test_missing_face_rejected_at_registry_freeze(self):
        self.r.register_behavior('x',lambda c:[])
        self.r.register_card(CardDefinition('x','x',CardType.SPELL,on_play='x',keywords=(Keyword.REWIND,),rewind=RewindSpec(1,'absent')))
        with self.assertRaises(ValueError):self.r.freeze()

    def test_mismatched_retry_count_rejected(self):
        self.forms();r=self.r;r._cards['f2']=replace(r.card('f2'),rewind=RewindSpec(1,'f1'))
        with self.assertRaises(ValueError):r.freeze()

    def test_nonterminal_end_rejected(self):
        self.forms();self.r._cards['f0']=replace(self.r.card('f0'),rewind=RewindSpec(),keywords=(Keyword.REWIND,))
        with self.assertRaises(ValueError):self.r.freeze()

    def test_cycles_and_partial_chain_rejected(self):
        for nxt in ('f3',None):
            r=build_registry();r.register_behavior('x',lambda c:[])
            r.register_card(CardDefinition('f3','f3',CardType.SPELL,on_play='x',keywords=(Keyword.REWIND,),rewind=RewindSpec(2,'f2')))
            r.register_card(CardDefinition('f2','f2',CardType.SPELL,on_play='x',keywords=(Keyword.REWIND,),rewind=RewindSpec(1,nxt)))
            with self.subTest(nxt=nxt),self.assertRaises(ValueError):r.freeze()

    def test_face_cannot_change_cost_stats_behavior_or_type(self):
        self.forms();original=self.r.card('f2')
        for changes in ({'cost':5},{'attack':8},{'health':9},{'on_play':None},{'kind':CardType.SPELL}):
            self.r._cards['f2']=replace(original,**changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.r.validate()

    def test_face_cannot_change_non_rewind_keyword(self):
        self.forms();self.r._cards['f2']=replace(self.r.card('f2'),keywords=(Keyword.REWIND,Keyword.TAUNT))
        with self.assertRaises(ValueError):self.r.freeze()

    def test_card_class_cannot_change_with_face(self):
        self.forms(metadata=CardMetadata(True,(CardClass.MAGE,),Rarity.COMMON))
        self.r._cards['f2']=replace(self.r.card('f2'),metadata=CardMetadata(False,(CardClass.WARRIOR,),Rarity.COMMON))
        with self.assertRaises(ValueError):self.r.freeze()

    def test_noncollectible_faces_can_change_copy_limit_metadata(self):
        self.forms(metadata=CardMetadata(True,(CardClass.MAGE,),Rarity.COMMON,deck_identity='root'))
        for n in range(3):
            self.r._cards[f'f{n}']=replace(self.r.card(f'f{n}'),metadata=CardMetadata(False,(CardClass.MAGE,),Rarity.COMMON,deck_identity=f'f{n}'))
        g=self.game();self.play(g);self.choose(g);self.check(g)

    def test_corrupt_executed_face_is_rejected(self):
        self.forms();g=self.game();self.play(g);self.choose(g);s=g.snapshot();s['state']['play_history'][-1]['card_id']='f3';self.reject(s)

    def test_portal_retry_replaces_card_and_preserves_generated_discount(self):
        g=self.game(('TIME_000',));self.play(g,'TIME_000');first=g.state.players[1].hand[0];self.choose(g)
        last=g.state.players[1].hand[0];entity=g.state.entities[last]
        self.assertNotEqual(first,last);self.assertNotIn(first,g.state.entities)
        self.assertEqual(entity.cost,max(0,self.r.card(entity.card_id).cost-3));self.assertEqual(g.state.players[1].mana,8);self.check(g)

    def test_sands_retries_discovery_with_current_class_only(self):
        g=self.game(('TIME_EVENT_999',),hero='HERO_08');self.play(g,'TIME_EVENT_999');self.check(g)
        self.choose(g,g.state.pending_choice.options[0].id);self.choose(g);self.check(g)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},{'CS2_029','CS2_024'})
        self.choose(g,g.state.pending_choice.options[0].id)
        self.assertEqual(len(g.state.players[1].hand),1);self.assertEqual(g.state.players[1].mana,9);self.check(g)

    def test_sands_keep_does_not_trigger_second_discovery(self):
        g=self.game(('TIME_EVENT_999',),hero='HERO_08');self.play(g,'TIME_EVENT_999')
        chosen=g.state.pending_choice.options[0];self.choose(g,chosen.id);self.choose(g,'keep')
        self.assertEqual(g.state.entities[g.state.players[1].hand[0]].card_id,chosen.card_id);self.check(g)

    def test_representative_pool_is_required_not_inferred_from_registry(self):
        g=self.game(('TIME_000',),context=None);before=g.snapshot()
        with self.assertRaises(ValueError):self.play(g,'TIME_000')
        self.assertEqual(g.snapshot(),before)

    def test_representative_rewind_choices_use_player_port(self):
        g=self.game(('TIME_EVENT_999',),hero='HERO_08');self.play(g,'TIME_EVENT_999');port=g.for_player(1)
        for select in (0,1,0):
            listing=port.legal_actions();result=port.submit({'revision':listing['revision'],'action':listing['actions'][select]})
            self.assertTrue(result['accepted']);self.check(g)
        self.assertIsNone(g.state.pending_choice)


if __name__=='__main__':unittest.main()
