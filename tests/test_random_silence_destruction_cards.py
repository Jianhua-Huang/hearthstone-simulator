"""Cease to Exist follows one physical residence through native Silence."""
from dataclasses import fields,is_dataclass,replace
import json,random,re,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.random_silence_destruction_cards import CEASE,load_batch
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,Zone
from hs_sim.engine.board_presence import capture_board_presence
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import ChangeControl,ChoiceOption,GainArmor,InvokeBehavior,RequestChoice,ReturnToHand,Transform
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BoardPresenceReference,GameState,LimitedTriggerSpec,TargetMode,TargetSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.spell_targets import ApplyResidentSpellTarget,ApplySpellTarget,RandomSpellTarget
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

P='k117.test.';YETI='CORE_CS2_182';REBORN=P+'reborn';DORMANT=P+'sleep';OBSERVER=P+'observer'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=(),factions=(),subtypes=())

def registry(mode=None):
    r=build_registry()
    r.register_behavior(P+'death',lambda c:(GainArmor(c.player_id,5),))
    for cid,extra in((REBORN,dict(keywords=(Keyword.REBORN,),deathrattle=P+'death')),(DORMANT,dict(dormant_turns=2)),
            (P+'immune',dict(keywords=(Keyword.IMMUNE,))),(P+'stealth',dict(keywords=(Keyword.STEALTH,))),
            (P+'elusive',dict(keywords=(Keyword.ELUSIVE,)))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=2,health=4,metadata=META,**extra))
    scripts={'gift':lambda c:(ChangeControl(c.target_id,2,until_end_of_turn=True,source_id=c.source_id),),
        'auto':lambda c:(CastSpell(1,CEASE,c.source_id,choices='random'),),
        'fail':lambda c:(_ for _ in()).throw(ResolutionError('K117 deliberate reaction failure')),
        'resummon':lambda c:(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),2,cause=SummonCause.capture(c)),)}
    for name,body in scripts.items():
        r.register_behavior(P+name,body)
        if name!='resummon':r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,metadata=META,
            targeting=TargetSpec(TargetMode.REQUIRED,zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly')if name=='gift'else None))
    if mode:
        event='random_choice'if mode in('random_return','random_control')else'silenced'
        def watch(c):
            target=c.event.target_id
            if mode=='fail':return(InvokeBehavior(P+'fail',c.source_id,1),)
            if mode=='random_control':return(ChangeControl(target,1),)
            if mode=='face':return(Transform(target,YETI),)
            if mode=='reenter':return(ReturnToHand(target),InvokeBehavior(P+'resummon',c.source_id,1,target))
            options=(ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,1),)))
            return((ReturnToHand(target),)if mode=='random_return'else())+(RequestChoice(1,options,c.source_id),)
        r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(OBSERVER,'Native reaction observer',CardType.MINION,health=5,metadata=META,
            limited_triggers=(LimitedTriggerSpec(event,P+'watch'),)))
    r.validate();return r

def resident_request(value):
    if type(value)is GameState:return None
    if type(value)is ApplyResidentSpellTarget:return value
    if is_dataclass(value):
        for field in fields(value):
            if field.name=='captured_state':continue
            found=resident_request(getattr(value,field.name))
            if found is not None:return found
    elif type(value)in(tuple,list):
        for child in value:
            found=resident_request(child)
            if found is not None:return found
    return None

class RandomSilenceDestructionTests(unittest.TestCase):
    def game(self,hand=(CEASE,),board=(),enemy=(REBORN,),mode=None):
        self.mode=mode
        if mode:board=(*board,OBSERVER)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_09',hand=hand,board=board,deck=(YETI,)*6,mana=20,max_mana=20,mana_cap=20),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*6)),seed=117),registry(mode))
    def play(self,g,cid=CEASE,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid);g.apply(PlayCard(1,eid,target));return eid
    def choose(self,g,key='keep'):g.apply(SelectChoice(1,g.state.pending_choice.id,(key,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(self.mode));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(self.mode)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('resolution_frame','rng_state','ApplyResidentSpellTarget','presence_id','rewind_session'):self.assertNotIn('"'+key+'"',public)
        return other

    def test_full_raw_primary_faces_native_rewind_spell_and_no_invented_school(self):
        data=load_batch();raw=data['cards'][0]['record'];r=registry();c=r.card(CEASE);self.assertEqual(canonical_digest(raw),data['cards'][0]['record_sha256']);self.assertEqual(c.metadata,metadata_from_record(raw));self.assertEqual((c.cost,c.kind,c.keywords),(3,CardType.SPELL,(Keyword.REWIND,)));self.assertIsNotNone(c.rewind);self.assertIsNone(c.spell_school);self.assertIsNone(c.targeting)
        norm=lambda s:re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for o in data['official_observations']['observations']:
            en=o['locale']=='en_US';self.assertEqual(o['face']['name'],raw['name_en'if en else'name']);self.assertEqual(norm(o['face']['text']),norm(raw['text_en'if en else'text']))
        self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated'])

    def test_native_silence_precedes_death_and_suppresses_deathrattle_and_reborn(self):
        g=self.game();target=g.state.players[2].board[0];rng=g._rng.getstate();self.play(g)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertTrue(g.state.entities[target].silenced);self.assertFalse(g.state.players[2].board);self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,0);self.assertEqual(len(g.state.death_history),1);self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.players[1].mana,17)
        self.assertLess(next(e.sequence for e in g.events if e.kind=='silenced'),next(e.sequence for e in g.events if e.kind=='minion_died'));self.portable(g);self.choose(g);self.assertEqual(g.state.players[1].mana,17)

    def test_random_selection_ignores_friendly_and_dormant_and_samples_once(self):
        g=self.game(board=(YETI,),enemy=(YETI,REBORN,DORMANT));eligible=g.state.players[2].board[:2];rng=random.Random();rng.setstate(g._rng.getstate());expected=rng.choice(eligible);self.play(g)
        self.assertEqual(g.state.entities[expected].zone,Zone.GRAVEYARD);self.assertEqual(g._rng.getstate(),rng.getstate());self.assertEqual(len(g.state.players[1].board),1);self.assertEqual(len(g.state.death_history),1);self.portable(g)

    def test_empty_or_dormant_enemy_is_rng_neutral_and_still_has_native_rewind(self):
        for enemy in((),(DORMANT,)):
            with self.subTest(enemy=enemy):
                g=self.game(enemy=enemy);rng=g._rng.getstate();self.play(g);self.assertEqual(g._rng.getstate(),rng);self.assertFalse(g.state.death_history);self.assertIsNotNone(g.state.pending_choice);self.choose(g);self.assertEqual(g.state.players[1].mana,17);self.portable(g)

    def test_random_spell_can_silence_immune_stealth_or_elusive_minion(self):
        for cid in(P+'immune',P+'stealth',P+'elusive'):
            with self.subTest(cid=cid):
                g=self.game(enemy=(cid,));target=g.state.players[2].board[0];self.play(g);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertTrue(g.state.entities[target].silenced)

    def test_silence_reverting_temporary_control_still_destroys_same_residence(self):
        g=self.game(hand=(P+'gift',CEASE),board=(YETI,),enemy=());target=g.state.players[1].board[0];presence=g.state.entities[target].board_presence_id;self.play(g,P+'gift',target);self.assertEqual(g.state.entities[target].controller,2);self.play(g)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[target].controller,1);self.assertEqual(len(g.state.death_history),1);self.assertGreater(presence,0);self.portable(g)

    def test_random_choice_control_reaction_cannot_rebind_or_drop_selected_body(self):
        g=self.game(enemy=(YETI,REBORN),mode='random_control');self.play(g);selected=next(e.target_id for e in g.events if e.kind=='random_choice');self.assertEqual(g.state.entities[selected].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[selected].controller,1);self.assertTrue(g.state.entities[selected].silenced);self.assertEqual(len(g.state.death_history),1);self.portable(g)

    def test_silence_reaction_same_id_reentry_is_not_destroyed(self):
        g=self.game(enemy=(YETI,),mode='reenter');target=g.state.players[2].board[0];presence=g.state.entities[target].board_presence_id;self.play(g)
        self.assertEqual(g.state.entities[target].zone,Zone.BOARD);self.assertNotEqual(g.state.entities[target].board_presence_id,presence);self.assertFalse(g.state.death_history);self.portable(g)

    def test_same_residence_transformation_after_silence_is_still_destroyed(self):
        g=self.game(enemy=(REBORN,),mode='face');target=g.state.players[2].board[0];self.play(g);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[target].card_id,YETI);self.assertEqual(len(g.state.death_history),1);self.portable(g)

    def test_waiting_after_silence_keeps_unscheduled_death_and_original_payment(self):
        g=self.game(mode='wait');target=g.state.players[2].board[0];self.play(g);self.assertTrue(g.state.entities[target].silenced);self.assertEqual(g.state.entities[target].zone,Zone.BOARD);self.assertFalse(g.state.death_history);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for game in(g,other):self.choose(game,'ok')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(g.state.players[1].mana,17);self.choose(g);self.portable(g)

    def test_departure_in_random_reaction_is_skipped_without_second_draw(self):
        g=self.game(enemy=(YETI,REBORN),mode='random_return');self.play(g);selected=next(e.target_id for e in g.events if e.kind=='random_choice');self.assertEqual(g.state.entities[selected].zone,Zone.HAND);rng=g._rng.getstate();other=self.portable(g)
        for game in(g,other):self.choose(game,'ok')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g._rng.getstate(),rng);self.assertFalse(g.state.death_history);self.assertFalse([e for e in g.events if e.kind=='silenced']);self.choose(g)

    def test_native_retry_retains_one_committed_death_and_one_payment(self):
        g=self.game(enemy=(YETI,REBORN));self.play(g);self.choose(g,'retry');self.assertIsNone(g.state.pending_choice);self.assertEqual(len(g.state.death_history),1);self.assertEqual(len(g.state.players[2].board),1);self.assertEqual(g.state.players[1].mana,17);self.portable(g)

    def test_automatic_cast_has_no_printed_cost_payment(self):
        g=self.game(hand=(P+'auto',));self.play(g,P+'auto');self.assertEqual(g.state.players[1].mana,20);self.assertEqual(len(g.state.death_history),1);self.assertTrue(g.state.entities[g.state.death_history[0].entity_id].silenced);self.portable(g)

    def test_silence_reaction_failure_rolls_back_selection_silence_death_and_payment(self):
        g=self.game(enemy=(YETI,REBORN),mode='fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),saved)

    def test_actual_pending_codec_rejects_future_presence_and_nonspell_source(self):
        g=self.game(mode='wait');self.play(g);request=resident_request(g._frame);self.assertIsNotNone(request);self.assertEqual(request.operation,'destroy');codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state);encoded=codec.encode(request);self.assertEqual(codec.decode(encoded),request)
        bad=json.loads(json.dumps(encoded));bad['fields']['target']['fields']['presence_id']=g.state.next_order+99
        with self.assertRaises((ValueError,SnapshotError)):codec.decode(bad)
        bad=json.loads(json.dumps(encoded));bad['fields']['source_id']=g.state.players[1].hero_id
        with self.assertRaises((ValueError,SnapshotError)):codec.decode(bad)

    def test_finite_operation_rejects_hero_damage_amount_and_unknown_steps(self):
        g=self.game();target=g.state.entities[g.state.players[2].board[0]];ref=MinionReference.capture(target)
        for args in(((g.state.players[2].hero_id,),1,'silence_destroy',0),((ref,),1,'silence_destroy',1),((ref,),1,'silence_damage',0)):
            with self.assertRaises(ValueError):RandomSpellTarget(*args)
        with self.assertRaises(ValueError):ApplySpellTarget(g.state.players[2].hero_id,1,'silence_destroy')
        with self.assertRaises(ValueError):ApplyResidentSpellTarget(capture_board_presence(g.state,target.id),1,'damage')

    def test_default_311_identity_schema_unchanged_and_old_core_is_rejected(self):
        from hs_sim.engine.representative import build_registry as defaults
        r=defaults();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667');self.assertGreaterEqual(SNAPSHOT_SCHEMA_VERSION,328);g=self.game();s=g.snapshot();s['mechanics_version']['version']='core-effects-v407'
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry(self.mode))

if __name__=='__main__':unittest.main()
