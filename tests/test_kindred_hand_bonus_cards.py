"""Torga's actual two physical selectors and native held bonus slots."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT, historical_definition_digests
from copy import deepcopy
from dataclasses import asdict,replace
import json,unittest
from pathlib import Path
from random import Random

from hs_sim.cards import build_registry
from hs_sim.cards.kindred_hand_bonus_cards import TWISTED,TORGA,BATCH_HASH,load_batch
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,PlayCard,
    PlayerSetup,Scenario,SelectChoice,SnapshotError,SpellSchool,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.bonus_effects import BONUS_EFFECTS,RotatePrintedHandBonuses
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.dark_gifts import GrantDarkGift
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Destroy,Draw,InvokeBehavior,RequestChoice,ReturnToHand)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.physical_draw_groups import DrawGroupSlot,DrawPhysicalGroup,kindred_type_matches
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry as representative
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference,CopyCard,MoveCard
from hs_sim.targets import canonical_digest

ROOT=Path(__file__).resolve().parents[1];YETI='CORE_CS2_182';STORM='TLC_107';FROST='TLC_440';BOLT='CORE_CS2_024';LIZARD='TLC_223'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


def registry():
    r=build_registry();r.register_behavior('k79.noop',lambda c:())
    def fail(c):raise ResolutionError('K79 deliberate failure')
    r.register_behavior('k79.fail',fail)
    for cid,tribes in(('elemental',('elemental',)),('all',('all',)),('unknown',None)):
        r.register_card(CardDefinition('k79.'+cid,cid,CardType.MINION,attack=1,health=2,metadata=replace(META,tribes=tribes)))
    for cid,school in(('frost',SpellSchool.FROST),('nature',SpellSchool.NATURE),('unschooled',None)):
        r.register_card(CardDefinition('k79.'+cid,cid,CardType.SPELL,on_play='k79.noop',spell_school=school,metadata=META))
    def first_draw(c):
        return (c.draw is not None and c.draw.id==1 and c.draw.player_id==c.player_id and c.draw.source_id is not None
            and c.state.entities[c.draw.source_id].card_id==TORGA)
    def wait(c):
        if not first_draw(c):return ()
        ref=CardReference.capture(c.state.entities[c.event.target_id]);source=c.draw.source_id
        return (RequestChoice(c.player_id,(
            ChoiceOption('keep','Continue',()),
            ChoiceOption('give','Give the first card away',(MoveCard(ref,3-c.player_id,Zone.HAND,source_id=c.source_id),)),
            ChoiceOption('transform','Change drawn face',(TransformStoredCard(ref,'k79.nature',c.source_id),)),
            ChoiceOption('kill','Remove original tutor',(Destroy(source,c.source_id),)),
            ChoiceOption('fail','Fail',(InvokeBehavior('k79.fail',c.source_id,c.player_id),))),c.source_id),)
    def nested(c):return (Draw(c.player_id,source_id=c.source_id),)if first_draw(c)else ()
    def fill(c):
        return (AddToHand(c.player_id,YETI,c.source_id),)if c.event.player_id==c.player_id and c.state.entities[c.event.source_id].card_id==TORGA else ()
    for name,event,body in(('wait','card_drawn',wait),('nested','card_drawn',nested),('fill','card_committed',fill)):
        r.register_behavior('k79.'+name,body);r.register_card(CardDefinition('k79.'+name,name,CardType.MINION,health=20,triggers=(TriggerSpec(event,'k79.'+name),),metadata=META))
    def stored(c):return next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==TWISTED)
    scripts={
        'copy':lambda c:(CopyCard(CardReference.capture(stored(c)),c.player_id,Zone.HAND,mode='current',source_id=c.source_id),),
        'gift':lambda c:(GrantDarkGift(CardReference.capture(stored(c)),'EDR_100t6',c.source_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
    }
    for name,body in scripts.items():
        r.register_behavior('k79.'+name,body);r.register_card(CardDefinition('k79.'+name,name,CardType.SPELL,on_play='k79.'+name,targeting=TargetSpec()if name=='bounce'else None,metadata=META))
    return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events']);saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')});return saved


def nodes(value,name):
    if isinstance(value,dict):
        if str(value.get('type','')).endswith('.'+name):yield value
        for item in value.values():yield from nodes(item,name)
    elif isinstance(value,list):
        for item in value:yield from nodes(item,name)


class KindredHandBonusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),*,board=(),deck=(YETI,)*10,enemy_hand=(),enemy_deck=(YETI,)*10,seed=1079):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,deck=enemy_deck,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=seed),self.r)
    def entities(self,g,cid,p=1,zone='hand'):
        s=g.state;return[s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid]
    def first(self,g,cid,p=1,zone='hand'):return self.entities(g,cid,p,zone)[0]
    def play(self,g,cid,target=None):
        eid=self.first(g,cid).id;g.apply(PlayCard(1,eid,target));return eid
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def choose(self,g,key):q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=g.snapshot();self.assertEqual(Game.from_snapshot(saved,registry()).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
    def printed(self,e):return tuple(a.keyword for a in e.abilities if a.kind=='keyword'and a.origin=='printed'and not a.consumed)

    def test_complete_faces_full_source_pin_and_actual_dual_type(self):
        data=load_batch();self.assertEqual(canonical_digest(data),BATCH_HASH);self.assertEqual((len(data['cards']),len(data['dependencies'])),(2,0))
        for row in data['cards']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual(self.r.card(TORGA).metadata.tribes,('beast','undead'));self.assertNotIn(TORGA,self.r.kindred_profiles)
        self.assertEqual(self.r.card(TWISTED).keywords,(Keyword.TAUNT,Keyword.ELUSIVE))
    def test_old1057_complete_definitions_and_default_fingerprint_preserved(self):
        prior=json.loads((ROOT/'outputs/card-integration-20261014/k79-before/definition-digests.json').read_bytes())
        self.assertEqual(len(prior),1057);self.assertEqual(prior,historical_definition_digests(self.r,prior))
        self.assertEqual(representative().fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)
    def test_torga_minion_tutors_native_kindred_then_matching_minion(self):
        g=self.game((TORGA,),deck=(STORM,'k79.elemental',YETI,'k79.nature'));source=self.play(g,TORGA)
        self.assertEqual([row.card_id for row in g.state.draw_history],[STORM,'k79.elemental'])
        self.assertTrue(all(row.source_id==source for row in g.state.draw_history));self.assertFalse(g.state.kindred_history);self.portable(g)
    def test_torga_spell_tutors_same_school_without_minion_or_unschooled_fallback(self):
        g=self.game((TORGA,),deck=(FROST,'k79.nature','k79.frost',YETI,'k79.unschooled'));self.play(g,TORGA)
        self.assertEqual([row.card_id for row in g.state.draw_history],[FROST,'k79.frost'])
    def test_torga_secondary_minion_type_can_activate_actual_kindred(self):
        g=self.game((TORGA,),deck=(LIZARD,'k79.elemental',YETI));self.play(g,TORGA)
        self.assertEqual([row.card_id for row in g.state.draw_history],[LIZARD,'k79.elemental'])
    def test_torga_all_type_candidate_matches_without_primary_type_shortcut(self):
        g=self.game((TORGA,),deck=(STORM,'k79.all',YETI));self.play(g,TORGA)
        self.assertEqual([row.card_id for row in g.state.draw_history],[STORM,'k79.all'])
    def test_torga_no_kindred_in_deck_does_not_draw_or_fatigue_or_spend_rng(self):
        g=self.game((TORGA,),board=(STORM,),deck=(YETI,'k79.elemental'));rng=g._rng.getstate();self.play(g,TORGA)
        self.assertFalse(g.state.draw_history);self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.players[1].fatigue,0)
    def test_torga_empty_deck_does_not_become_two_fatigue_attempts(self):
        g=self.game((TORGA,),deck=());self.play(g,TORGA);self.assertFalse(g.state.draw_history);self.assertEqual(g.state.players[1].fatigue,0)
    def test_torga_no_activator_keeps_first_and_skips_second(self):
        g=self.game((TORGA,),deck=(STORM,YETI,'k79.nature'));self.play(g,TORGA)
        self.assertEqual([row.card_id for row in g.state.draw_history],[STORM]);self.assertEqual(len(g.state.players[1].deck),2)
    def test_torga_another_physical_copy_can_be_the_activator(self):
        g=self.game((TORGA,),deck=(STORM,STORM));self.play(g,TORGA)
        rows=g.state.draw_history;self.assertEqual([row.card_id for row in rows],[STORM,STORM]);self.assertNotEqual(rows[0].entity_id,rows[1].entity_id)
    def test_torga_burned_first_still_supplies_original_type(self):
        g=self.game((TORGA,)+('k79.nature',)*9,board=('k79.fill',),deck=(FROST,'k79.frost'));self.play(g,TORGA)
        self.assertEqual([(row.card_id,row.outcome)for row in g.state.draw_history],[(FROST,'burned'),('k79.frost','burned')]);self.portable(g)
    def test_torga_nested_draw_is_not_the_first_subject_or_second_tutor(self):
        g=self.game((TORGA,),board=('k79.nested',),deck=('k79.nature',STORM,'k79.elemental'));source=self.play(g,TORGA)
        self.assertEqual([row.card_id for row in g.state.draw_history],[STORM,'k79.nature','k79.elemental'])
        self.assertEqual([row.id for row in g.state.draw_history if row.source_id==source],[1,3])
    def test_torga_first_draw_waiting_recovers_original_selector(self):
        g=self.game((TORGA,),board=('k79.wait',),deck=(FROST,'k79.frost','k79.nature'));self.play(g,TORGA)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(g.state.draw_history),1);self.portable(g)
        self.choose(g,'keep');self.assertEqual([row.card_id for row in g.state.draw_history],[FROST,'k79.frost']);self.portable(g)
    def test_torga_first_draw_transform_does_not_change_original_frost_selector(self):
        g=self.game((TORGA,),board=('k79.wait',),deck=(FROST,'k79.frost','k79.nature'));self.play(g,TORGA);self.choose(g,'transform')
        self.assertEqual([row.card_id for row in g.state.draw_history],[FROST,'k79.frost']);self.assertEqual(len(self.entities(g,'k79.nature')),1)
    def test_torga_first_draw_leaving_hand_does_not_remove_second_selector(self):
        g=self.game((TORGA,),board=('k79.wait',),deck=(FROST,'k79.frost'));self.play(g,TORGA);self.choose(g,'give')
        self.assertEqual(len(self.entities(g,FROST,2)),1);self.assertEqual(g.state.draw_history[-1].card_id,'k79.frost')
    def test_torga_source_leaves_after_first_draw_but_original_player_still_draws(self):
        g=self.game((TORGA,),board=('k79.wait',),deck=(FROST,'k79.frost'));source=self.play(g,TORGA);self.choose(g,'kill')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.draw_history),2);self.portable(g)
    def test_torga_unknown_required_metadata_fails_atomically(self):
        g=self.game((TORGA,),deck=(STORM,'k79.unknown'));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,TORGA)
        self.assertEqual(g.snapshot(),saved)
    def test_torga_failed_waiting_choice_is_atomic(self):
        g=self.game((TORGA,),board=('k79.wait',),deck=(FROST,'k79.frost'));self.play(g,TORGA);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved)
    def test_torga_pair_payload_survives_wait_and_rejects_nonboolean_policy(self):
        g=self.game((TORGA,),board=('k79.wait',),deck=(FROST,'k79.frost'));self.play(g,TORGA);saved=g.snapshot()
        request=next(nodes(saved,'CapturePhysicalDrawGroup'));self.assertIs(request['fields']['kindred_pair'],True);request['fields']['kindred_pair']=1
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(saved),registry())
    def test_torga_pair_declaration_requires_exact_two_typed_slots(self):
        for slots in((DrawGroupSlot(),)*2,(DrawGroupSlot(PoolQuery(kinds=(CardType.MINION,CardType.SPELL))),)):
            with self.subTest(slots=slots),self.assertRaises(ValueError):DrawPhysicalGroup(1,1,slots,kindred_pair=True)
        self.assertTrue(kindred_type_matches(self.r,LIZARD,'k79.elemental'));self.assertFalse(kindred_type_matches(self.r,FROST,'k79.nature'))
    def test_twisted_acquisition_keeps_raw_printed_pair_without_hidden_extra_roll(self):
        g=self.game((TWISTED,));self.assertEqual(self.printed(self.first(g,TWISTED)),(Keyword.TAUNT,Keyword.ELUSIVE))
        self.assertEqual(g._rng.getstate(),Random(1079).getstate())
    def test_twisted_owner_start_chooses_two_distinct_complete_pool_keywords(self):
        g=self.game((TWISTED,));rng=Random();rng.setstate(g._rng.getstate());pool=list(BONUS_EFFECTS);expected=[]
        for _ in range(2):selected=rng.choice(pool);pool.remove(selected);expected.append(selected)
        self.cycle(g);self.assertEqual(self.printed(self.first(g,TWISTED)),tuple(expected));self.assertEqual(g._rng.getstate(),rng.getstate());self.portable(g)
    def test_twisted_held_native_pool_includes_rush_without_board_readiness_filter(self):
        g=self.game((TWISTED,),seed=0);self.cycle(g);self.assertIn(Keyword.RUSH,self.printed(self.first(g,TWISTED)))
    def test_twisted_opponent_start_does_not_rotate_own_hand(self):
        g=self.game((TWISTED,));rng=g._rng.getstate();g.apply(EndTurn(1))
        self.assertEqual(self.printed(self.first(g,TWISTED)),(Keyword.TAUNT,Keyword.ELUSIVE));self.assertEqual(g._rng.getstate(),rng)
    def test_twisted_board_and_deck_do_not_listen_as_held_cards(self):
        g=self.game((YETI,),board=(TWISTED,),deck=(YETI,TWISTED));rng=g._rng.getstate();self.cycle(g)
        self.assertEqual(self.printed(self.first(g,TWISTED,zone='board')),(Keyword.TAUNT,Keyword.ELUSIVE))
        self.assertEqual(self.printed(self.first(g,TWISTED,zone='deck')),(Keyword.TAUNT,Keyword.ELUSIVE));self.assertEqual(g._rng.getstate(),rng)
    def test_twisted_draw_after_start_begins_printed_and_rotates_next_start(self):
        g=self.game(deck=(TWISTED,YETI,YETI));self.cycle(g);self.assertEqual(self.printed(self.first(g,TWISTED)),(Keyword.TAUNT,Keyword.ELUSIVE))
        self.assertFalse([e for e in g.events if e.kind=='hand_bonus_rotated']);self.cycle(g)
        self.assertEqual(len([e for e in g.events if e.kind=='hand_bonus_rotated']),1)
    def test_twisted_roll_replaces_native_pair_instead_of_accumulating(self):
        g=self.game((TWISTED,));self.cycle(g);self.cycle(g)
        self.assertEqual(len(self.printed(self.first(g,TWISTED))),2);self.assertEqual(len([e for e in g.events if e.kind=='hand_bonus_rotated']),2)
    def test_twisted_independent_dark_gift_charge_survives_native_rotation(self):
        g=self.game((TWISTED,'k79.gift'));self.play(g,'k79.gift');self.cycle(g);source=self.first(g,TWISTED)
        self.assertIn(Keyword.CHARGE,source.keywords);self.assertEqual(len(self.printed(source)),2);self.portable(g)
    def test_twisted_current_copy_preserves_pair_and_both_continue_independently(self):
        g=self.game((TWISTED,'k79.copy'));self.cycle(g);before=self.printed(self.first(g,TWISTED));self.play(g,'k79.copy')
        self.assertEqual([self.printed(e)for e in self.entities(g,TWISTED)],[before,before]);self.cycle(g)
        self.assertEqual(len(self.entities(g,TWISTED)),2);self.assertTrue(all(len(self.printed(e))==2 for e in self.entities(g,TWISTED)));self.portable(g)
    def test_twisted_play_preserves_selected_slots_and_bounce_resets_native_face(self):
        g=self.game((TWISTED,'k79.bounce'));self.cycle(g);before=self.printed(self.first(g,TWISTED));source=self.play(g,TWISTED)
        self.assertEqual(self.printed(g.state.entities[source]),before);self.play(g,'k79.bounce',source)
        self.assertEqual(self.printed(self.first(g,TWISTED)),(Keyword.TAUNT,Keyword.ELUSIVE));self.portable(g)
    def test_native_rotation_codec_preserves_card_reference_and_rejects_future_epoch(self):
        g=self.game((TWISTED,));source=self.first(g,TWISTED);value=RotatePrintedHandBonuses(CardReference.capture(source),source.id)
        codec=FrameCodec(g.mechanics,self.r,origin_state=g.state,origin_events=g.events);encoded=codec.encode(value)
        self.assertEqual(codec.decode(encoded),value);encoded['fields']['card']['fields']['zone_epoch']=source.zone_epoch+100
        with self.assertRaises(ValueError):codec.decode(encoded)
    def test_queries_and_opponent_projection_do_not_expose_private_pair_producer(self):
        g=self.game((TWISTED,TORGA),deck=(STORM,'k79.elemental'));saved=g.snapshot();g.for_player(1).legal_actions();g.observe(1);enemy=g.observe(2)
        self.assertEqual(g.snapshot(),saved);text=json.dumps(enemy)
        for private in('kindred_pair','RotatePrintedHandBonuses','hand_bonus_rotated','DYNAMIC_KEYWORD1'):self.assertNotIn(private,text)
    def test_previous_schema297_default_and_constructed_saves_are_rejected(self):
        for name in('constructed-v87','default-v65'):
            with self.subTest(name=name),self.assertRaises(SnapshotError):Game.from_snapshot(json.loads((ROOT/f'outputs/card-integration-20261014/k79-before/{name}-core372-schema297.json').read_bytes()),self.r if name.startswith('constructed')else representative())


if __name__=='__main__':unittest.main()
